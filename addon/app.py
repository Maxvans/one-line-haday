"""One Line HaDay backend API.

FastAPI service providing journals, entries, ACLs, and photo storage
for the One Line HaDay Home Assistant add-on. All routes require the
calling Home Assistant user id to be supplied via the
`X-Remote-User-Id` header, which is set by the Home Assistant
ingress proxy for authenticated requests.
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Header, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from pathlib import Path
from typing import Optional
import sqlite3
import uuid
import shutil

BASE = Path("/data")
DB_PATH = BASE / "one_line_haday.db"
PHOTO_ROOT = BASE / "photos"
BASE.mkdir(parents=True, exist_ok=True)
PHOTO_ROOT.mkdir(parents=True, exist_ok=True)

VISIBILITIES = {"household", "private", "shared"}
ROLES = {"owner", "co_editor", "viewer"}
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
MAX_PHOTO_BYTES = 15 * 1024 * 1024  # 15 MB per photo

app = FastAPI(title="One Line HaDay API")


def get_conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init_db():
    with get_conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS journals (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                owner_ha_user_id TEXT NOT NULL,
                visibility TEXT NOT NULL,
                retention_days INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS journal_members (
                journal_id TEXT NOT NULL REFERENCES journals(id) ON DELETE CASCADE,
                ha_user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY (journal_id, ha_user_id)
            );
            CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY,
                journal_id TEXT NOT NULL REFERENCES journals(id) ON DELETE CASCADE,
                author_ha_user_id TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                body TEXT NOT NULL,
                visibility TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_entries_journal_date
                ON entries(journal_id, entry_date);
            CREATE INDEX IF NOT EXISTS idx_entries_author
                ON entries(author_ha_user_id);
            CREATE TABLE IF NOT EXISTS entry_permissions (
                entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                ha_user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY (entry_id, ha_user_id)
            );
            CREATE TABLE IF NOT EXISTS photos (
                id TEXT PRIMARY KEY,
                entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                secure_path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        c.commit()


init_db()


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class JournalIn(BaseModel):
    title: str
    visibility: str = "household"
    retention_days: Optional[int] = None

    @field_validator("visibility")
    @classmethod
    def check_visibility(cls, v):
        if v not in VISIBILITIES:
            raise ValueError(f"visibility must be one of {VISIBILITIES}")
        return v


class EntryIn(BaseModel):
    journal_id: str
    entry_date: str
    body: str
    visibility: str = "household"
    permissions: list[dict] = []

    @field_validator("visibility")
    @classmethod
    def check_visibility(cls, v):
        if v not in VISIBILITIES:
            raise ValueError(f"visibility must be one of {VISIBILITIES}")
        return v

    @field_validator("body")
    @classmethod
    def check_body(cls, v):
        if not v.strip():
            raise ValueError("body must not be empty")
        return v


class EntryUpdate(BaseModel):
    body: Optional[str] = None
    visibility: Optional[str] = None

    @field_validator("visibility")
    @classmethod
    def check_visibility(cls, v):
        if v is not None and v not in VISIBILITIES:
            raise ValueError(f"visibility must be one of {VISIBILITIES}")
        return v


# --------------------------------------------------------------------------
# Auth / access-control helpers
# --------------------------------------------------------------------------

def current_user(x_remote_user_id: Optional[str] = Header(default=None)) -> str:
    """Resolve the calling Home Assistant user id.

    Home Assistant's ingress proxy injects the authenticated user's id.
    Reject the request outright if it is missing so the API is never
    reachable anonymously.
    """
    if not x_remote_user_id:
        raise HTTPException(status_code=401, detail="Missing Home Assistant user identity")
    return x_remote_user_id


def is_journal_member(c, journal_id: str, ha_user_id: str) -> Optional[str]:
    row = c.execute(
        "select role from journal_members where journal_id=? and ha_user_id=?",
        (journal_id, ha_user_id),
    ).fetchone()
    return row["role"] if row else None


def can_read_entry(c, entry_row, ha_user_id: str) -> bool:
    if entry_row["author_ha_user_id"] == ha_user_id:
        return True
    if entry_row["visibility"] == "household":
        return is_journal_member(c, entry_row["journal_id"], ha_user_id) is not None
    if entry_row["visibility"] == "private":
        return False
    if entry_row["visibility"] == "shared":
        perm = c.execute(
            "select 1 from entry_permissions where entry_id=? and ha_user_id=?",
            (entry_row["id"], ha_user_id),
        ).fetchone()
        return perm is not None
    return False


def can_write_entry(c, entry_row, ha_user_id: str) -> bool:
    if entry_row["author_ha_user_id"] == ha_user_id:
        return True
    perm = c.execute(
        "select role from entry_permissions where entry_id=? and ha_user_id=?",
        (entry_row["id"], ha_user_id),
    ).fetchone()
    return bool(perm and perm["role"] in ("owner", "co_editor"))


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"ok": True}


@app.post("/journals")
def create_journal(data: JournalIn, user_id: str = Header(alias="X-Remote-User-Id")):
    jid = str(uuid.uuid4())
    with get_conn() as c:
        c.execute(
            "insert into journals (id,title,owner_ha_user_id,visibility,retention_days) values (?,?,?,?,?)",
            (jid, data.title, user_id, data.visibility, data.retention_days),
        )
        c.execute(
            "insert or replace into journal_members (journal_id,ha_user_id,role) values (?,?,?)",
            (jid, user_id, "owner"),
        )
        c.commit()
    return {"id": jid}


@app.get("/journals")
def list_journals(user_id: str = Header(alias="X-Remote-User-Id")):
    with get_conn() as c:
        rows = c.execute(
            """
            select j.* from journals j
            join journal_members m on m.journal_id = j.id
            where m.ha_user_id = ?
            order by j.created_at desc
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/journals/{journal_id}/members")
def add_member(journal_id: str, ha_user_id: str, role: str, user_id: str = Header(alias="X-Remote-User-Id")):
    if role not in ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {ROLES}")
    with get_conn() as c:
        requester_role = is_journal_member(c, journal_id, user_id)
        if requester_role != "owner":
            raise HTTPException(status_code=403, detail="Only the journal owner can add members")
        c.execute(
            "insert or replace into journal_members (journal_id,ha_user_id,role) values (?,?,?)",
            (journal_id, ha_user_id, role),
        )
        c.commit()
    return {"ok": True}


@app.post("/entries")
def create_entry(data: EntryIn, user_id: str = Header(alias="X-Remote-User-Id")):
    with get_conn() as c:
        if is_journal_member(c, data.journal_id, user_id) is None:
            raise HTTPException(status_code=403, detail="Not a member of this journal")
        eid = str(uuid.uuid4())
        c.execute(
            """insert into entries
               (id,journal_id,author_ha_user_id,entry_date,body,visibility)
               values (?,?,?,?,?,?)""",
            (eid, data.journal_id, user_id, data.entry_date, data.body, data.visibility),
        )
        for p in data.permissions:
            if p.get("role") not in ROLES:
                continue
            c.execute(
                "insert or replace into entry_permissions (entry_id,ha_user_id,role) values (?,?,?)",
                (eid, p["ha_user_id"], p["role"]),
            )
        c.commit()
    return {"id": eid}


@app.get("/entries")
def list_entries(
    journal_id: str,
    author_ha_user_id: Optional[str] = Query(default=None, description="Filter by author"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    user_id: str = Header(alias="X-Remote-User-Id"),
):
    with get_conn() as c:
        if is_journal_member(c, journal_id, user_id) is None:
            raise HTTPException(status_code=403, detail="Not a member of this journal")
        sql = "select * from entries where journal_id = ?"
        params: list = [journal_id]
        if author_ha_user_id:
            sql += " and author_ha_user_id = ?"
            params.append(author_ha_user_id)
        if date_from:
            sql += " and entry_date >= ?"
            params.append(date_from)
        if date_to:
            sql += " and entry_date <= ?"
            params.append(date_to)
        sql += " order by entry_date desc, created_at desc"
        rows = c.execute(sql, params).fetchall()
        visible = [dict(r) for r in rows if can_read_entry(c, r, user_id)]
    return visible


@app.patch("/entries/{entry_id}")
def update_entry(entry_id: str, data: EntryUpdate, user_id: str = Header(alias="X-Remote-User-Id")):
    with get_conn() as c:
        row = c.execute("select * from entries where id=?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entry not found")
        if not can_write_entry(c, row, user_id):
            raise HTTPException(status_code=403, detail="No write access to this entry")
        fields, params = [], []
        if data.body is not None:
            fields.append("body = ?")
            params.append(data.body)
        if data.visibility is not None:
            fields.append("visibility = ?")
            params.append(data.visibility)
        if fields:
            fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(entry_id)
            c.execute(f"update entries set {', '.join(fields)} where id = ?", params)
            c.commit()
    return {"updated": entry_id}


@app.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, user_id: str = Header(alias="X-Remote-User-Id")):
    with get_conn() as c:
        row = c.execute("select * from entries where id=?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entry not found")
        if not can_write_entry(c, row, user_id):
            raise HTTPException(status_code=403, detail="No write access to this entry")
        photos = [r["secure_path"] for r in c.execute(
            "select secure_path from photos where entry_id=?", (entry_id,)
        )]
        c.execute("delete from entries where id=?", (entry_id,))
        c.commit()
    for p in photos:
        Path(p).unlink(missing_ok=True)
    return {"deleted": entry_id}


@app.post("/entries/{entry_id}/photos")
async def upload_photo(entry_id: str, file: UploadFile = File(...), user_id: str = Header(alias="X-Remote-User-Id")):
    with get_conn() as c:
        row = c.execute("select * from entries where id=?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entry not found")
        if not can_write_entry(c, row, user_id):
            raise HTTPException(status_code=403, detail="No write access to this entry")

    if file.content_type not in ALLOWED_PHOTO_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported content type: {file.content_type}")

    photo_id = str(uuid.uuid4())
    safe_name = Path(file.filename or "photo").name
    dest_dir = PHOTO_ROOT / entry_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{photo_id}-{safe_name}"

    size = 0
    with dest.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_PHOTO_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Photo exceeds 15MB limit")
            f.write(chunk)

    with get_conn() as c:
        c.execute(
            "insert into photos (id,entry_id,filename,mime_type,secure_path) values (?,?,?,?,?)",
            (photo_id, entry_id, safe_name, file.content_type, str(dest)),
        )
        c.commit()
    return {"id": photo_id}


@app.get("/entries/{entry_id}/photos")
def list_photos(entry_id: str, user_id: str = Header(alias="X-Remote-User-Id")):
    with get_conn() as c:
        row = c.execute("select * from entries where id=?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entry not found")
        if not can_read_entry(c, row, user_id):
            raise HTTPException(status_code=403, detail="No read access to this entry")
        photos = c.execute("select id, filename, mime_type from photos where entry_id=?", (entry_id,)).fetchall()
    return [dict(p) for p in photos]


@app.get("/photos/{photo_id}")
def get_photo(photo_id: str, user_id: str = Header(alias="X-Remote-User-Id")):
    with get_conn() as c:
        photo = c.execute("select * from photos where id=?", (photo_id,)).fetchone()
        if not photo:
            raise HTTPException(status_code=404)
        entry = c.execute("select * from entries where id=?", (photo["entry_id"],)).fetchone()
        if not entry or not can_read_entry(c, entry, user_id):
            raise HTTPException(status_code=403, detail="No read access to this photo")
    path = Path(photo["secure_path"])
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type=photo["mime_type"], filename=photo["filename"])


@app.delete("/photos/{photo_id}")
def delete_photo(photo_id: str, user_id: str = Header(alias="X-Remote-User-Id")):
    with get_conn() as c:
        photo = c.execute("select * from photos where id=?", (photo_id,)).fetchone()
        if not photo:
            raise HTTPException(status_code=404)
        entry = c.execute("select * from entries where id=?", (photo["entry_id"],)).fetchone()
        if not entry or not can_write_entry(c, entry, user_id):
            raise HTTPException(status_code=403, detail="No write access to this photo")
        c.execute("delete from photos where id=?", (photo_id,))
        c.commit()
    Path(photo["secure_path"]).unlink(missing_ok=True)
    return {"deleted": photo_id}
