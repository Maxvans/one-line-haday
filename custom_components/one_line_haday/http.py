"""HTTP views for One Line HaDay.

Registered under Home Assistant's built-in `http` component, so all
requests are authenticated by Home Assistant itself (session cookie or
long-lived token) — there is no separate auth layer to maintain. The
authenticated user is available on `request["hass_user"]`.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import uuid
from pathlib import Path

from aiohttp import web
from aiohttp.web import Request, Response

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import ALLOWED_PHOTO_TYPES, DOMAIN, MAX_PHOTO_BYTES
from .storage import OneLineHaDayStore

_LOGGER = logging.getLogger(__name__)


def _photo_dir(hass: HomeAssistant, entry_id: str) -> Path:
    path = Path(hass.config.path("www", "one_line_haday", "photos", entry_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _require_user(request: Request) -> str:
    user = request.get("hass_user")
    if user is None:
        raise web.HTTPUnauthorized(text="Authentication required")
    return user.id


class JournalsView(HomeAssistantView):
    """List and create journals."""

    url = "/api/one_line_haday/journals"
    name = "api:one_line_haday:journals"
    requires_auth = True

    async def get(self, request: Request) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)
        journals = store.list_journals_for_user(ha_user_id)
        if not journals:
            await store.async_ensure_default_journal(ha_user_id)
            journals = store.list_journals_for_user(ha_user_id)
        return self.json(journals)

    async def post(self, request: Request) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)
        body = await request.json()
        title = (body.get("title") or "Household Journal").strip()
        visibility = body.get("visibility", "household")
        try:
            jid = await store.async_create_journal(ha_user_id, title, visibility)
        except ValueError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"id": jid}, status_code=201)


class EntriesView(HomeAssistantView):
    """List and create entries."""

    url = "/api/one_line_haday/entries"
    name = "api:one_line_haday:entries"
    requires_auth = True

    async def get(self, request: Request) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)

        journal_id = request.query.get("journal_id")
        if not journal_id or store.is_member(journal_id, ha_user_id) is None:
            raise web.HTTPForbidden(text="Not a member of this journal")

        author_filter = request.query.get("author_ha_user_id")
        date_from = request.query.get("date_from")
        date_to = request.query.get("date_to")

        entries = store.list_entries(journal_id, author_filter, date_from, date_to)
        visible = [e for e in entries if store.can_read_entry(e, ha_user_id)]
        for e in visible:
            e = dict(e)
        return self.json([
            {**e, "photos": store.list_photos(e["id"])} for e in visible
        ])

    async def post(self, request: Request) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)
        body = await request.json()

        journal_id = body.get("journal_id")
        if not journal_id or store.is_member(journal_id, ha_user_id) is None:
            raise web.HTTPForbidden(text="Not a member of this journal")

        try:
            eid = await store.async_create_entry(
                journal_id=journal_id,
                author_ha_user_id=ha_user_id,
                entry_date=body["entry_date"],
                body=body["body"],
                visibility=body.get("visibility", "household"),
                permissions=body.get("permissions"),
            )
        except (KeyError, ValueError) as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"id": eid}, status_code=201)


class EntryView(HomeAssistantView):
    """Update or delete a single entry."""

    url = "/api/one_line_haday/entries/{entry_id}"
    name = "api:one_line_haday:entry"
    requires_auth = True

    async def patch(self, request: Request, entry_id: str) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)

        entry = store.get_entry(entry_id)
        if not entry:
            raise web.HTTPNotFound()
        if not store.can_write_entry(entry, ha_user_id):
            raise web.HTTPForbidden()

        body = await request.json()
        try:
            await store.async_update_entry(entry_id, body.get("body"), body.get("visibility"))
        except ValueError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"status": "ok"})

    async def delete(self, request: Request, entry_id: str) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)

        entry = store.get_entry(entry_id)
        if not entry:
            raise web.HTTPNotFound()
        if not store.can_write_entry(entry, ha_user_id):
            raise web.HTTPForbidden()

        photos = await store.async_delete_entry(entry_id)
        for photo in photos:
            file_path = Path(hass.config.path("www", photo["relative_path"]))
            file_path.unlink(missing_ok=True)
        return web.Response(status=204)


class PhotosView(HomeAssistantView):
    """Upload a photo to an entry."""

    url = "/api/one_line_haday/entries/{entry_id}/photos"
    name = "api:one_line_haday:photos"
    requires_auth = True

    async def post(self, request: Request, entry_id: str) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)

        entry = store.get_entry(entry_id)
        if not entry:
            raise web.HTTPNotFound()
        if not store.can_write_entry(entry, ha_user_id):
            raise web.HTTPForbidden()

        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            raise web.HTTPBadRequest(text="Missing file field")

        content_type = field.headers.get("Content-Type", "application/octet-stream")
        if content_type not in ALLOWED_PHOTO_TYPES:
            raise web.HTTPUnsupportedMediaType(text=f"Unsupported type: {content_type}")

        ext = mimetypes.guess_extension(content_type) or ".jpg"
        filename = f"{uuid.uuid4()}{ext}"
        photo_dir = await hass.async_add_executor_job(_photo_dir, hass, entry_id)
        dest = photo_dir / filename

        size = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = await field.read_chunk(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_PHOTO_BYTES:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise web.HTTPRequestEntityTooLarge(max_size=MAX_PHOTO_BYTES, actual_size=size)
                fh.write(chunk)

        relative_path = f"one_line_haday/photos/{entry_id}/{filename}"
        photo_id = await store.async_add_photo(entry_id, filename, content_type, relative_path)
        return self.json({"id": photo_id, "url": f"/local/{relative_path}"}, status_code=201)


class PhotoView(HomeAssistantView):
    """Delete a single photo."""

    url = "/api/one_line_haday/photos/{photo_id}"
    name = "api:one_line_haday:photo"
    requires_auth = True

    async def delete(self, request: Request, photo_id: str) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)

        photo = store.get_photo(photo_id)
        if not photo:
            raise web.HTTPNotFound()
        entry = store.get_entry(photo["entry_id"])
        if not entry or not store.can_write_entry(entry, ha_user_id):
            raise web.HTTPForbidden()

        await store.async_delete_photo(photo_id)
        file_path = Path(hass.config.path("www", photo["relative_path"]))
        file_path.unlink(missing_ok=True)
        return web.Response(status=204)


def async_register_views(hass: HomeAssistant) -> None:
    hass.http.register_view(JournalsView())
    hass.http.register_view(EntriesView())
    hass.http.register_view(EntryView())
    hass.http.register_view(PhotosView())
    hass.http.register_view(PhotoView())
    hass.http.register_view(MembersView())
    hass.http.register_view(MemberView())
    hass.http.register_view(RetentionView())
    hass.http.register_view(ExportView())


class MembersView(HomeAssistantView):
    """List, add, or update journal members. Owner-only for mutation."""

    url = "/api/one_line_haday/journals/{journal_id}/members"
    name = "api:one_line_haday:members"
    requires_auth = True

    async def get(self, request: Request, journal_id: str) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)
        if store.is_member(journal_id, ha_user_id) is None:
            raise web.HTTPForbidden(text="Not a member of this journal")
        return self.json(store.list_members(journal_id))

    async def post(self, request: Request, journal_id: str) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)
        if store.is_member(journal_id, ha_user_id) != "owner":
            raise web.HTTPForbidden(text="Only the journal owner can manage members")

        body = await request.json()
        target_user = body.get("ha_user_id")
        role = body.get("role", "viewer")
        if not target_user:
            raise web.HTTPBadRequest(text="ha_user_id is required")
        try:
            await store.async_set_member_role(journal_id, target_user, role)
        except ValueError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return self.json({"status": "ok"})


class MemberView(HomeAssistantView):
    """Remove a single member from a journal. Owner-only."""

    url = "/api/one_line_haday/journals/{journal_id}/members/{ha_user_id}"
    name = "api:one_line_haday:member"
    requires_auth = True

    async def delete(self, request: Request, journal_id: str, ha_user_id: str) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        caller_id = _require_user(request)
        if store.is_member(journal_id, caller_id) != "owner":
            raise web.HTTPForbidden(text="Only the journal owner can manage members")
        try:
            await store.async_remove_member(journal_id, ha_user_id)
        except ValueError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        return web.Response(status=204)


class RetentionView(HomeAssistantView):
    """Set a journal's retention window (owner-only)."""

    url = "/api/one_line_haday/journals/{journal_id}/retention"
    name = "api:one_line_haday:retention"
    requires_auth = True

    async def post(self, request: Request, journal_id: str) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)
        if store.is_member(journal_id, ha_user_id) != "owner":
            raise web.HTTPForbidden(text="Only the journal owner can change retention")
        body = await request.json()
        retention_days = body.get("retention_days")
        try:
            await store.async_set_retention(journal_id, retention_days)
        except KeyError as err:
            raise web.HTTPNotFound() from err
        return self.json({"status": "ok"})


class ExportView(HomeAssistantView):
    """Export a full journal (entries, permissions, photo metadata) as JSON."""

    url = "/api/one_line_haday/journals/{journal_id}/export"
    name = "api:one_line_haday:export"
    requires_auth = True

    async def get(self, request: Request, journal_id: str) -> Response:
        hass: HomeAssistant = request.app["hass"]
        store: OneLineHaDayStore = hass.data[DOMAIN]["store"]
        ha_user_id = _require_user(request)
        if store.is_member(journal_id, ha_user_id) is None:
            raise web.HTTPForbidden(text="Not a member of this journal")
        export = store.export_journal(journal_id)
        # Only include entries the caller is allowed to read.
        export["entries"] = [e for e in export["entries"] if store.can_read_entry(e, ha_user_id)]
        readable_ids = {e["id"] for e in export["entries"]}
        export["photos"] = [p for p in export["photos"] if p["entry_id"] in readable_ids]
        response = web.json_response(export)
        response.headers["Content-Disposition"] = f'attachment; filename="one_line_haday_{journal_id}.json"'
        return response
