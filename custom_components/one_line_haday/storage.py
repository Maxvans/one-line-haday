"""Persistent storage for One Line HaDay.

Uses Home Assistant's built-in Store helper so all journal/entry/photo
metadata lives in `.storage/one_line_haday` and is automatically included
in Home Assistant backups. Photo binaries are written to
`<config>/www/one_line_haday/photos/<entry_id>/` so they are servable
as static files without a custom auth layer.
"""
from __future__ import annotations

import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION, ROLES, VISIBILITIES


def _empty_state() -> dict[str, Any]:
    return {"journals": {}, "journal_members": {}, "entries": {}, "entry_permissions": {}, "photos": {}}


class OneLineHaDayStore:
    """Wraps a Home Assistant Store with journal/entry/ACL/photo helpers."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = _empty_state()

    async def async_load(self) -> None:
        loaded = await self._store.async_load()
        if loaded:
            self._data = {**_empty_state(), **loaded}

    async def _save(self) -> None:
        await self._store.async_save(self._data)

    # ---------------------------------------------------------------
    # Journals
    # ---------------------------------------------------------------

    async def async_ensure_default_journal(self, owner_ha_user_id: str) -> str:
        for jid, journal in self._data["journals"].items():
            member = self._data["journal_members"].get(jid, {})
            if owner_ha_user_id in member:
                return jid
        return await self.async_create_journal(owner_ha_user_id, "Household Journal", "household")

    async def async_create_journal(self, owner_ha_user_id: str, title: str, visibility: str = "household") -> str:
        if visibility not in VISIBILITIES:
            raise ValueError(f"invalid visibility: {visibility}")
        jid = str(uuid.uuid4())
        self._data["journals"][jid] = {
            "id": jid,
            "title": title,
            "owner_ha_user_id": owner_ha_user_id,
            "visibility": visibility,
        }
        self._data["journal_members"].setdefault(jid, {})[owner_ha_user_id] = "owner"
        await self._save()
        return jid

    def list_journals_for_user(self, ha_user_id: str) -> list[dict]:
        result = []
        for jid, journal in self._data["journals"].items():
            if ha_user_id in self._data["journal_members"].get(jid, {}):
                result.append(journal)
        return result

    def is_member(self, journal_id: str, ha_user_id: str) -> str | None:
        return self._data["journal_members"].get(journal_id, {}).get(ha_user_id)

    async def async_add_member(self, journal_id: str, ha_user_id: str, role: str) -> None:
        if role not in ROLES:
            raise ValueError(f"invalid role: {role}")
        self._data["journal_members"].setdefault(journal_id, {})[ha_user_id] = role
        await self._save()

    # ---------------------------------------------------------------
    # Entries
    # ---------------------------------------------------------------

    async def async_create_entry(
        self,
        journal_id: str,
        author_ha_user_id: str,
        entry_date: str,
        body: str,
        visibility: str = "household",
        permissions: list[dict] | None = None,
    ) -> str:
        if visibility not in VISIBILITIES:
            raise ValueError(f"invalid visibility: {visibility}")
        if not body.strip():
            raise ValueError("body must not be empty")
        eid = str(uuid.uuid4())
        self._data["entries"][eid] = {
            "id": eid,
            "journal_id": journal_id,
            "author_ha_user_id": author_ha_user_id,
            "entry_date": entry_date,
            "body": body,
            "visibility": visibility,
        }
        for perm in permissions or []:
            if perm.get("role") in ROLES:
                self._data["entry_permissions"].setdefault(eid, {})[perm["ha_user_id"]] = perm["role"]
        await self._save()
        return eid

    def get_entry(self, entry_id: str) -> dict | None:
        return self._data["entries"].get(entry_id)

    def list_entries(
        self,
        journal_id: str,
        author_ha_user_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        entries = [e for e in self._data["entries"].values() if e["journal_id"] == journal_id]
        if author_ha_user_id:
            entries = [e for e in entries if e["author_ha_user_id"] == author_ha_user_id]
        if date_from:
            entries = [e for e in entries if e["entry_date"] >= date_from]
        if date_to:
            entries = [e for e in entries if e["entry_date"] <= date_to]
        return sorted(entries, key=lambda e: (e["entry_date"], e["id"]), reverse=True)

    async def async_update_entry(self, entry_id: str, body: str | None, visibility: str | None) -> None:
        entry = self._data["entries"].get(entry_id)
        if not entry:
            raise KeyError(entry_id)
        if body is not None:
            if not body.strip():
                raise ValueError("body must not be empty")
            entry["body"] = body
        if visibility is not None:
            if visibility not in VISIBILITIES:
                raise ValueError(f"invalid visibility: {visibility}")
            entry["visibility"] = visibility
        await self._save()

    async def async_delete_entry(self, entry_id: str) -> list[dict]:
        self._data["entries"].pop(entry_id, None)
        self._data["entry_permissions"].pop(entry_id, None)
        photos = [p for p in self._data["photos"].values() if p["entry_id"] == entry_id]
        for p in photos:
            self._data["photos"].pop(p["id"], None)
        await self._save()
        return photos

    # ---------------------------------------------------------------
    # ACL checks
    # ---------------------------------------------------------------

    def can_read_entry(self, entry: dict, ha_user_id: str) -> bool:
        if entry["author_ha_user_id"] == ha_user_id:
            return True
        if entry["visibility"] == "household":
            return self.is_member(entry["journal_id"], ha_user_id) is not None
        if entry["visibility"] == "private":
            return False
        if entry["visibility"] == "shared":
            return ha_user_id in self._data["entry_permissions"].get(entry["id"], {})
        return False

    def can_write_entry(self, entry: dict, ha_user_id: str) -> bool:
        if entry["author_ha_user_id"] == ha_user_id:
            return True
        role = self._data["entry_permissions"].get(entry["id"], {}).get(ha_user_id)
        return role in ("owner", "co_editor")

    # ---------------------------------------------------------------
    # Photos
    # ---------------------------------------------------------------

    async def async_add_photo(self, entry_id: str, filename: str, mime_type: str, relative_path: str) -> str:
        pid = str(uuid.uuid4())
        self._data["photos"][pid] = {
            "id": pid,
            "entry_id": entry_id,
            "filename": filename,
            "mime_type": mime_type,
            "relative_path": relative_path,
        }
        await self._save()
        return pid

    def get_photo(self, photo_id: str) -> dict | None:
        return self._data["photos"].get(photo_id)

    def list_photos(self, entry_id: str) -> list[dict]:
        return [p for p in self._data["photos"].values() if p["entry_id"] == entry_id]

    async def async_delete_photo(self, photo_id: str) -> dict | None:
        photo = self._data["photos"].pop(photo_id, None)
        if photo:
            await self._save()
        return photo
