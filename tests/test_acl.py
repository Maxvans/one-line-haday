"""Tests for journal/entry ACL logic in OneLineHaDayStore."""
import pytest


@pytest.mark.asyncio
async def test_household_entry_visible_to_all_members(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_add_member(jid, "bob", "viewer")

    eid = await store.async_create_entry(jid, "alice", "2026-07-28", "Went for a run", "household")
    entry = store.get_entry(eid)

    assert store.can_read_entry(entry, "alice") is True
    assert store.can_read_entry(entry, "bob") is True
    assert store.can_read_entry(entry, "stranger") is False


@pytest.mark.asyncio
async def test_private_entry_visible_only_to_author(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_add_member(jid, "bob", "viewer")

    eid = await store.async_create_entry(jid, "alice", "2026-07-28", "Private thoughts", "private")
    entry = store.get_entry(eid)

    assert store.can_read_entry(entry, "alice") is True
    assert store.can_read_entry(entry, "bob") is False


@pytest.mark.asyncio
async def test_shared_entry_visible_only_to_grantees(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_add_member(jid, "bob", "viewer")
    await store.async_add_member(jid, "carol", "viewer")

    eid = await store.async_create_entry(
        jid, "alice", "2026-07-28", "Just for Bob", "shared",
        permissions=[{"ha_user_id": "bob", "role": "viewer"}],
    )
    entry = store.get_entry(eid)

    assert store.can_read_entry(entry, "bob") is True
    assert store.can_read_entry(entry, "carol") is False


@pytest.mark.asyncio
async def test_only_author_or_grantee_can_write(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_add_member(jid, "bob", "viewer")

    eid = await store.async_create_entry(jid, "alice", "2026-07-28", "Line", "household")
    entry = store.get_entry(eid)

    assert store.can_write_entry(entry, "alice") is True
    assert store.can_write_entry(entry, "bob") is False


@pytest.mark.asyncio
async def test_co_editor_grant_allows_write_on_shared_entry(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_add_member(jid, "bob", "viewer")

    eid = await store.async_create_entry(
        jid, "alice", "2026-07-28", "Editable", "shared",
        permissions=[{"ha_user_id": "bob", "role": "co_editor"}],
    )
    entry = store.get_entry(eid)

    assert store.can_write_entry(entry, "bob") is True


@pytest.mark.asyncio
async def test_multiple_users_can_write_same_day(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_add_member(jid, "bob", "co_editor")

    e1 = await store.async_create_entry(jid, "alice", "2026-07-28", "Alice line", "household")
    e2 = await store.async_create_entry(jid, "bob", "2026-07-28", "Bob line", "household")

    entries = store.list_entries(jid)
    dates = {e["entry_date"] for e in entries}
    authors = {e["author_ha_user_id"] for e in entries}

    assert dates == {"2026-07-28"}
    assert authors == {"alice", "bob"}
    assert {e1, e2} == {e["id"] for e in entries}


@pytest.mark.asyncio
async def test_filter_entries_by_author(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    await store.async_add_member(jid, "bob", "co_editor")

    await store.async_create_entry(jid, "alice", "2026-07-28", "Alice line", "household")
    await store.async_create_entry(jid, "bob", "2026-07-28", "Bob line", "household")

    bob_entries = store.list_entries(jid, author_ha_user_id="bob")
    assert len(bob_entries) == 1
    assert bob_entries[0]["author_ha_user_id"] == "bob"


@pytest.mark.asyncio
async def test_cannot_create_entry_with_invalid_visibility(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    with pytest.raises(ValueError):
        await store.async_create_entry(jid, "alice", "2026-07-28", "Line", "public")


@pytest.mark.asyncio
async def test_cannot_create_empty_entry(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    with pytest.raises(ValueError):
        await store.async_create_entry(jid, "alice", "2026-07-28", "   ", "household")


@pytest.mark.asyncio
async def test_delete_entry_removes_photos(store):
    await store.async_load()
    jid = await store.async_create_journal("alice", "Family")
    eid = await store.async_create_entry(jid, "alice", "2026-07-28", "Line", "household")
    await store.async_add_photo(eid, "a.jpg", "image/jpeg", f"one_line_haday/photos/{eid}/a.jpg")

    assert len(store.list_photos(eid)) == 1
    photos = await store.async_delete_entry(eid)
    assert len(photos) == 1
    assert store.get_entry(eid) is None
    assert store.list_photos(eid) == []
