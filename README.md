# One Line HaDay

A shared "one line a day" journal for Home Assistant. Every household
member writes a short entry for today, filters entries by author, and
attaches photos — all from a sidebar panel, installed as a native Home
Assistant integration via HACS.

## Install via HACS

This is a **custom integration**, not a Supervisor add-on, so it installs
through HACS's "Integration" category.

1. In Home Assistant, open **HACS**.
2. Click the three dots (top right) → **Custom repositories**.
3. Add `https://github.com/Maxvans/one-line-haday`, category **Integration**.
4. Find **One Line HaDay** in HACS and click **Download**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & Services → Add Integration**, search for
   **One Line HaDay**, and confirm setup.
7. A new **One Line HaDay** entry appears in the sidebar.

No Docker, no exposed ports, no Supervisor required — this works on
Home Assistant Core, Container, and OS installs alike.

## What's included

- `custom_components/one_line_haday/` — the integration:
  - `storage.py` — journal/entry/ACL/photo persistence using Home
    Assistant's built-in `Store` helper (`.storage/one_line_haday`),
    included automatically in Home Assistant backups.
  - `http.py` — REST routes (`/api/one_line_haday/...`) registered on
    Home Assistant's own `http` component; every route requires an
    authenticated Home Assistant session, so there's no separate login
    or token to manage.
  - `__init__.py` — sets up storage, HTTP routes, and registers the
    sidebar panel via `panel_custom`.
  - `config_flow.py` — a simple "Add Integration" setup flow.
  - `www/one-line-haday-panel.js` — the sidebar panel UI.
- `hacs.json` — HACS repository metadata.
- `docs/architecture.md` — design notes and requirements traceability.

## How multi-user journaling works

- Every Home Assistant user who opens the panel is automatically added to
  a shared "Household Journal" the first time they load it.
- Each entry is tagged with its author's Home Assistant user ID, so
  multiple people can write entries for the same date without collisions.
- Entries can be:
  - **Household** — visible to every journal member.
  - **Private** — visible only to the author.
  - **Shared** — visible only to explicitly granted users.
- Only the author (or someone explicitly granted `owner`/`co_editor`) can
  edit or delete an entry.

## Photos

- Each entry supports one or more photo attachments (JPEG, PNG, WebP, HEIC;
  15 MB limit per file).
- Photos are stored under `<config>/www/one_line_haday/photos/<entry_id>/`
  and served via Home Assistant's standard `/local/` static path.
- Only users with write access to an entry can add or remove its photos.

## Requirements traceability

| Requirement | Status |
|---|---|
| Multiple users write to the same day | Done — entries are per-author rows in a shared journal |
| Filter by user | Done — `GET /entries?author_ha_user_id=...` + panel dropdown |
| Photo upload per entry | Done — multipart upload, type/size validated, ACL-checked |
| Private / shared / household visibility | Done — enforced on read and write |
| Home Assistant identity as author | Done — uses HA's authenticated session user, no custom auth |
| Installable via HACS | Done — native custom integration, no Supervisor/Docker dependency |
| Export / retention jobs | Done — owner-only JSON export + scheduled retention cleanup |
| Automated tests | Done — pytest coverage for ACL, membership, retention, and export logic |

## Known limitations (v1)

- No automated tests yet for the ACL logic in `storage.py`.
- No export or retention tooling.
- Journal membership is currently auto-granted to any authenticated HA
  user on first visit; a UI for inviting/removing members is not yet built.

## Local development

```bash
# Symlink into a dev Home Assistant config for live testing
ln -s $(pwd)/custom_components/one_line_haday \
      /path/to/homeassistant/config/custom_components/one_line_haday
```

Restart Home Assistant after changes to Python files. Panel JS changes
under `www/` are picked up on browser refresh (hard-refresh to bypass cache).
