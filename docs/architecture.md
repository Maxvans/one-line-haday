# Architecture

## Overview

One Line HaDay is a native Home Assistant **custom integration**
(`custom_components/one_line_haday/`), installable via HACS. It has no
Docker container, no Supervisor add-on, and no exposed network port —
everything runs inside the Home Assistant Core process and is authenticated
by Home Assistant's own session/token system.

## Why an integration instead of an add-on

The original design used a Supervisor add-on (FastAPI + Docker). HACS does
not support installing Supervisor add-ons — it only manages custom
integrations, frontend resources, themes, and Python scripts. Since the
goal was "install and test through HACS," the whole backend was rewritten
as a `custom_components` integration:

- Persistence moved from SQLite to Home Assistant's `Store` helper.
- The FastAPI server was replaced with `HomeAssistantView` classes
  registered on Home Assistant's built-in `http` component.
- Authentication moved from a custom `X-Remote-User-Id` header to Home
  Assistant's own `requires_auth` mechanism, which populates
  `request["hass_user"]` from the caller's session or long-lived token.
- The panel is registered via `panel_custom` from within `async_setup_entry`
  instead of via ingress.

This also means the integration works identically on Home Assistant Core,
Container, Supervised, and OS installs — ingress and Supervisor-specific
features are no longer required.

## Data model

Stored as a single JSON document under Home Assistant's `.storage/one_line_haday`,
with the following top-level shape:

- **journals** — `{id, title, owner_ha_user_id, visibility}`
- **journal_members** — `{journal_id: {ha_user_id: role}}`
- **entries** — `{id, journal_id, author_ha_user_id, entry_date, body, visibility}`
- **entry_permissions** — `{entry_id: {ha_user_id: role}}` (used for `shared` entries)
- **photos** — `{id, entry_id, filename, mime_type, relative_path}`
- **retention_days** — stored on each journal and used by the cleanup job

Photo binaries live outside the JSON store, under
`<config>/www/one_line_haday/photos/<entry_id>/`, and are served through
Home Assistant's existing `/local/` static path — no custom file-serving
route was needed for reads.

## Access control

- `can_read_entry` — true if the caller is the author, or the entry is
  `household` and the caller is a journal member, or the entry is `shared`
  and the caller has an explicit grant. `private` entries are never
  readable by anyone but the author.
- `can_write_entry` — true if the caller is the author, or the caller has
  an `owner`/`co_editor` grant on that specific entry.
- Photo upload/delete routes re-check `can_write_entry` on the parent entry
  before touching any file.

## HACS packaging

- `hacs.json` at the repo root declares the repository as a HACS-managed
  Integration with `content_in_root: false` (content lives under
  `custom_components/one_line_haday/`).
- `manifest.json` declares `config_flow: true` and dependencies on `http`,
  `frontend`, and `websocket_api`, which HACS validates before allowing
  the repository to be added.
- `config_flow.py` provides a minimal "Add Integration" step so setup
  happens through Home Assistant's standard Settings UI rather than YAML.

## Known limitations (v1)

- No browser automation tests yet for the custom panel UI.
- Membership management uses Home Assistant user IDs instead of friendly
  display-name lookup.
- Per-entry edit history is not implemented.
