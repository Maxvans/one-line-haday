# One Line HaDay

A "one line a day" journaling add-on for Home Assistant. Multiple household
members can write entries for the same day, filter entries by author, attach
photos, and control who can see each entry.

## Status: functional v1

This version includes a working backend and a Home Assistant panel UI.
It is not yet a published/signed add-on — see [Next steps](#next-steps).

## What's included

- FastAPI backend (`addon/app.py`) with SQLite persistence for journals,
  entries, ACLs (owner / co-editor / viewer), and photos
- Authentication via the `X-Remote-User-Id` header, populated by Home
  Assistant's ingress proxy — no anonymous access
- Visibility model per entry: `household` (all journal members),
  `private` (author only), `shared` (explicit grantees only)
- Entry CRUD: create, list (filterable by author and date range), edit, delete
- Photo upload/list/delete per entry, served only to users with read access
  to the parent entry
- Home Assistant custom panel (`panel/one-line-haday-panel.js`) wired to the
  live API: write today's entry, filter by author, upload photos, delete entries
- Multi-arch add-on packaging (`addon/build.yaml`, `addon/Dockerfile`) using
  Home Assistant's official Python base images
- Ingress-enabled add-on config (`addon/config.yaml`) — no exposed host port,
  sidebar icon/title driven by Home Assistant itself

## Repository layout

```
addon/
  app.py            FastAPI backend
  config.yaml       Home Assistant add-on manifest (ingress, map, arch)
  build.yaml        Multi-arch base image mapping
  Dockerfile        Add-on container build
  requirements.txt  Python dependencies
panel/
  one-line-haday-panel.js   Home Assistant custom panel frontend
docs/
  architecture.md   Design notes and requirements traceability
```

## Requirements traceability

| Requirement | Status |
|---|---|
| Multiple users write to the same day | Implemented — entries are per-author rows scoped to a shared journal |
| Filter by user | Implemented — `GET /entries?author_ha_user_id=...` and panel filter dropdown |
| Photo upload per entry | Implemented — multipart upload, size/type validated, ACL-checked retrieval |
| Private vs shared vs household visibility | Implemented — enforced in both list and read/write checks |
| Home Assistant identity as author | Implemented — backend requires `X-Remote-User-Id`; panel reads `hass.user` |
| Installable as an add-on | Partial — packaging is add-on-shaped but not yet published to a store repo |
| Export / retention jobs | Not yet implemented |
| Automated tests | Not yet implemented |

## Next steps

1. Add a `repository.yaml` at the repo root so this can be added as a Home
   Assistant add-on repository.
2. Add automated tests for the ACL logic in `app.py` (this is the highest-risk
   area for regressions).
3. Implement retention/export jobs referenced in `journals.retention_days`.
4. Add a translations file (`translations/en.yaml`) for the add-on config UI.
