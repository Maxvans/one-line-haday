"""Tests for membership, retention, and export features."""
import pytest


@pytest.mark.asyncio
async def test_add_and_list_members(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_set_member_role(jid, "bob", "co_editor")

    members = store.list_members(jid)
    assert members["alice"] == "owner"
    assert members["bob"] == "co_editor"


@pytest.mark.asyncio
async def test_cannot_remove_last_owner(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    with pytest.raises(ValueError):
        await store.async_remove_member(jid, "alice")


@pytest.mark.asyncio
async def test_remove_member_allowed_when_not_last_owner(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_set_member_role(jid, "bob", "owner")
    await store.async_remove_member(jid, "alice")

    members = store.list_members(jid)
    assert "alice" not in members
    assert members["bob"] == "owner"


@pytest.mark.asyncio
async def test_retention_expires_old_entries(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_set_retention(jid, 7)

    await store.async_create_entry(jid, "alice", "2026-01-01", "Old line", "household")
    await store.async_create_entry(jid, "alice", "2026-07-27", "Recent line", "household")

    expired = store.find_expired_entries(jid, "2026-07-28")
    assert len(expired) == 1
    assert expired[0]["body"] == "Old line"


@pytest.mark.asyncio
async def test_no_retention_means_nothing_expires(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_create_entry(jid, "alice", "2020-01-01", "Ancient line", "household")

    expired = store.find_expired_entries(jid, "2026-07-28")
    assert expired == []


@pytest.mark.asyncio
async def test_export_includes_entries_permissions_and_photos(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    eid = await store.async_create_entry(
        jid, "alice", "2026-07-28", "Line", "shared",
        permissions=[{"ha_user_id": "bob", "role": "viewer"}],
    )
    await store.async_add_photo(eid, "a.jpg", "image/jpeg", f"one_line_haday/photos/{eid}/a.jpg")

    export = store.export_journal(jid)
    assert export["journal"]["id"] == jid
    assert len(export["entries"]) == 1
    assert export["entry_permissions"][eid]["bob"] == "viewer"
    assert len(export["photos"]) == 1


@pytest.mark.asyncio
async def test_invalid_role_rejected(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    with pytest.raises(ValueError):
        await store.async_set_member_role(jid, "bob", "superadmin")
