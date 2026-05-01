import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
import jinja2
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import jwt
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # backend/
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "notes.db")
DATABASE_PATH = os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH)
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

# Config
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = os.environ.get("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("EXPIRARE_TOKEN_MINUTE", "30"))

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/autentificare")

# Database initialization

def initialize_db():
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT,
        tags TEXT,
        pinned INTEGER DEFAULT 0,
        archived INTEGER DEFAULT 0,
        owner_id INTEGER NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME,
        FOREIGN KEY(owner_id) REFERENCES users(id)
    )
    """)
    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
    except Exception:
        pass
    try:
        yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_db()
    yield


app = FastAPI(title="Aplicație de notițe", lifespan=lifespan)

# CORS (development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates for HTMX UI
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
template_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
)

# Pydantic models
class UserRegister(BaseModel):
    email: str = Field(min_length=5, max_length=100)
    password: str = Field(min_length=8, max_length=100)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Adresa de email nu este validă.")
        return v.lower()


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: Optional[str] = None
    tags: Optional[str] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[str] = None
    pinned: Optional[bool] = None
    archived: Optional[bool] = None


# Utilities
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: sqlite3.Connection = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Token invalid.")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirat.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalid.")

    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Utilizatorul nu există.")
    return user


# Auth endpoints
@app.post("/inregistrare", status_code=201)
async def register(request: Request):
    """Register a new user. Accepts JSON or form data. Returns a JWT token on success."""
    try:
        ct = request.headers.get('content-type', '')
        if 'application/json' in ct:
            body = await request.json()
            email = body.get('email')
            password = body.get('password')
        else:
            form = await request.form()
            email = form.get('email') or form.get('username')
            password = form.get('password')
        u = UserRegister(email=email, password=password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (u.email,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Adresa de email este deja înregistrată.")
        conn.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (u.email, hash_password(u.password)))
        conn.commit()
        # create token so client can be logged-in immediately
        token = create_access_token({"sub": u.email})
        return {"access_token": token, "token_type": "bearer"}
    finally:
        conn.close()


@app.post("/autentificare")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: sqlite3.Connection = Depends(get_db)):
    user = db.execute("SELECT * FROM users WHERE email = ?", (form_data.username,)).fetchone()
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email sau parolă incorectă.")
    token = create_access_token({"sub": user["email"]})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/notes")
def list_notes(db: sqlite3.Connection = Depends(get_db), current_user = Depends(get_current_user)):
    rows = db.execute("SELECT * FROM notes WHERE owner_id = ? ORDER BY created_at DESC", (current_user["id"],)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/notes", status_code=201)
def create_note(note: NoteCreate, current_user = Depends(get_current_user)):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("INSERT INTO notes (title, content, tags, owner_id) VALUES (?, ?, ?, ?)", (note.title, note.content, note.tags, current_user["id"]))
        conn.commit()
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@app.get("/api/notes/{note_id}")
def get_note(note_id: int, db: sqlite3.Connection = Depends(get_db), current_user = Depends(get_current_user)):
    row = db.execute("SELECT * FROM notes WHERE id = ? AND owner_id = ?", (note_id, current_user["id"])).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Notă negăsită.")
    return dict(row)


@app.delete("/api/notes/{note_id}", status_code=204)
def delete_note(note_id: int, current_user = Depends(get_current_user)):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM notes WHERE id = ? AND owner_id = ?", (note_id, current_user["id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Notă negăsită.")
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        conn.commit()
        return
    finally:
        conn.close()


@app.put("/api/notes/{note_id}")
def update_note(note_id: int, data: NoteUpdate, current_user = Depends(get_current_user)):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM notes WHERE id = ? AND owner_id = ?", (note_id, current_user["id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Notă negăsită.")
        current = dict(row)
        title = data.title if data.title is not None else current["title"]
        content = data.content if data.content is not None else current["content"]
        tags = data.tags if data.tags is not None else current["tags"]
        pinned = int(data.pinned) if data.pinned is not None else current["pinned"]
        archived = int(data.archived) if data.archived is not None else current["archived"]
        conn.execute("UPDATE notes SET title = ?, content = ?, tags = ?, pinned = ?, archived = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (title, content, tags, pinned, archived, note_id))
        conn.commit()
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ui", response_class=HTMLResponse)
def ui_index(request: Request):
    """Main UI page (HTMX + Jinja) - uses client-side login to obtain JWT."""
    content = template_env.get_template("index.html").render()
    return HTMLResponse(content)


@app.get("/notes/fragment", response_class=HTMLResponse)
def notes_fragment(request: Request, q: Optional[str] = None, db: sqlite3.Connection = Depends(get_db), current_user = Depends(get_current_user)):
    if q:
        pattern = f"%{q}%"
        rows = db.execute(
            "SELECT * FROM notes WHERE owner_id = ? AND (title LIKE ? OR content LIKE ? OR tags LIKE ?) ORDER BY pinned DESC, created_at DESC",
            (current_user["id"], pattern, pattern, pattern),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM notes WHERE owner_id = ? ORDER BY pinned DESC, created_at DESC", (current_user["id"],)).fetchall()
    notes = [dict(r) for r in rows]
    pinned = [n for n in notes if n.get('pinned')]
    others = [n for n in notes if not n.get('pinned')]
    content = template_env.get_template("notes_list.html").render(pinned=pinned, notes=others, search_query=q)
    return HTMLResponse(content)


@app.post("/notes/create", response_class=HTMLResponse)
def notes_create(request: Request, title: str = Form(...), content: str = Form(None), tags: str = Form(None), current_user = Depends(get_current_user)):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("INSERT INTO notes (title, content, tags, owner_id) VALUES (?, ?, ?, ?)", (title, content, tags, current_user["id"]))
        conn.commit()
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (cur.lastrowid,)).fetchone()
        content = template_env.get_template("_note_item.html").render(note=dict(row))
        return HTMLResponse(content)
    finally:
        conn.close()


@app.get("/notes/{note_id}/edit", response_class=HTMLResponse)
def notes_edit(note_id: int, request: Request, db: sqlite3.Connection = Depends(get_db), current_user = Depends(get_current_user)):
    row = db.execute("SELECT * FROM notes WHERE id = ? AND owner_id = ?", (note_id, current_user["id"])).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Notă negăsită.")
    content = template_env.get_template("note_form.html").render(note=dict(row), action=f"/notes/{note_id}/update")
    return HTMLResponse(content)


@app.post("/notes/{note_id}/update", response_class=HTMLResponse)
def notes_update(note_id: int, request: Request, title: str = Form(None), content: str = Form(None), tags: str = Form(None), current_user = Depends(get_current_user)):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM notes WHERE id = ? AND owner_id = ?", (note_id, current_user["id"])) .fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Notă negăsită.")
        title_final = title if title is not None else row["title"]
        content_final = content if content is not None else row["content"]
        tags_final = tags if tags is not None else row["tags"]
        conn.execute("UPDATE notes SET title = ?, content = ?, tags = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (title_final, content_final, tags_final, note_id))
        conn.commit()
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        content = template_env.get_template("_note_item.html").render(note=dict(row))
        return HTMLResponse(content)
    finally:
        conn.close()


@app.post("/notes/{note_id}/toggle_pin", response_class=HTMLResponse)
def notes_toggle_pin(note_id: int, request: Request, db: sqlite3.Connection = Depends(get_db), current_user = Depends(get_current_user)):
    row = db.execute("SELECT * FROM notes WHERE id = ? AND owner_id = ?", (note_id, current_user["id"])).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Notă negăsită.")
    new = 0 if row["pinned"] else 1
    db.execute("UPDATE notes SET pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new, note_id))
    db.commit()
    row = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    content = template_env.get_template("_note_item.html").render(note=dict(row))
    return HTMLResponse(content)


@app.post("/notes/{note_id}/delete", response_class=HTMLResponse)
def notes_delete(note_id: int, request: Request, current_user = Depends(get_current_user)):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM notes WHERE id = ? AND owner_id = ?", (note_id, current_user["id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Notă negăsită.")
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        conn.commit()
        return HTMLResponse("")
    finally:
        conn.close()


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
