import sys
import os
import uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_register_login_create_note():
    email = f"test_{uuid.uuid4().hex}@example.com"
    pw = "password123"
    r = client.post("/inregistrare", json={"email": email, "password": pw})
    assert r.status_code in (200, 201)

    r = client.post("/autentificare", data={"username": email, "password": pw})
    assert r.status_code == 200
    token = r.json().get("access_token")
    assert token

    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/notes", json={"title": "t1", "content": "c1"}, headers=headers)
    assert r.status_code == 201
    note = r.json()
    assert note["title"] == "t1"
