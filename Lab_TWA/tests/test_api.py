import sys
import os
import uuid
import tempfile

# ensure package imports work from tests folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Use an isolated temporary DB for tests to avoid clobbering developer DB
DB_PATH = os.path.join(tempfile.gettempdir(), f"test_notes_{uuid.uuid4().hex}.db")
os.environ["DATABASE_PATH"] = DB_PATH

from fastapi.testclient import TestClient
import backend.main as main

# Ensure DB tables are initialized for the test database before instantiating TestClient
main.initialize_db()
client = TestClient(main.app)


def register_and_login():
    email = f"test_{uuid.uuid4().hex}@example.com"
    pw = "password123"
    r = client.post("/inregistrare", json={"email": email, "password": pw})
    assert r.status_code in (200, 201)

    r = client.post("/autentificare", data={"username": email, "password": pw})
    assert r.status_code == 200
    token = r.json().get("access_token")
    assert token
    return {"Authorization": f"Bearer {token}"}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_unauthorized_access():
    r = client.get("/api/notes")
    assert r.status_code == 401


def test_crud_flow():
    headers = register_and_login()

    # Create note (API)
    r = client.post("/api/notes", json={"title": "api note", "content": "api content"}, headers=headers)
    assert r.status_code == 201
    note = r.json()
    nid = note["id"]
    assert note["title"] == "api note"

    # Get note
    r = client.get(f"/api/notes/{nid}", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == nid

    # List notes
    r = client.get("/api/notes", headers=headers)
    assert r.status_code == 200
    assert any(n["id"] == nid for n in r.json())

    # Update note (PUT)
    r = client.put(f"/api/notes/{nid}", json={"title": "updated", "pinned": True}, headers=headers)
    assert r.status_code == 200
    updated = r.json()
    assert updated["title"] == "updated"
    # pinned stored as integer 0/1
    assert int(updated.get("pinned", 0)) == 1

    # Delete (API)
    r = client.delete(f"/api/notes/{nid}", headers=headers)
    assert r.status_code == 204
    r = client.get(f"/api/notes/{nid}", headers=headers)
    assert r.status_code == 404


def test_htmx_endpoints():
    headers = register_and_login()

    # Create via HTMX endpoint (returns HTML fragment)
    r = client.post("/notes/create", data={"title": "htmx note", "content": "c", "tags": "t"}, headers=headers)
    assert r.status_code == 200
    assert "<" in r.text

    # Create via API to get an ID for subsequent HTMX actions
    r = client.post("/api/notes", json={"title": "htmx2", "content": "c2"}, headers=headers)
    assert r.status_code == 201
    note = r.json()
    nid = note["id"]

    # Edit form (GET)
    r = client.get(f"/notes/{nid}/edit", headers=headers)
    assert r.status_code == 200
    assert "<form" in r.text

    # Update via HTMX (POST form)
    r = client.post(f"/notes/{nid}/update", data={"title": "htmx-updated"}, headers=headers)
    assert r.status_code == 200
    assert "htmx-updated" in r.text

    # Delete via HTMX
    r = client.post(f"/notes/{nid}/delete", headers=headers)
    assert r.status_code == 200
    r = client.get(f"/api/notes/{nid}", headers=headers)
    assert r.status_code == 404
