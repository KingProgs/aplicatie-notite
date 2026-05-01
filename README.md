# Lab_TWA — Aplicație de notițe (FastAPI + SQLite + HTMX)

Proiect minimal pentru laborator: backend FastAPI, SQLite (serverless), autentificare JWT.

Rulare locală:

```bash
cd Lab_TWA
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: http://localhost:8000/docs
- Dacă folosiți `.env`, copiați `backend/.env.example` → `backend/.env` și modificați `SECRET_KEY`.

Testare
------

Un test simplu este furnizat în `tests/test_api.py`. Pentru a rula testele:

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
pytest -q
```

Deploy (Render)
----------------

Am inclus un fișier `render.yaml` în rădăcină care configurează un Web Service pentru Render.com. Pași rapizi:

1. Commit & push repository pe GitHub.
2. Conectați repository-ul în Render și creați un nou Web Service folosind `render.yaml` (sau configurați manual start/build commands).
3. Asigurați-vă că `DATABASE_PATH` este setat la `/tmp/notes.db` (sau folosiți o bază externă pentru persistență).

Notă: fișierul SQLite local este efemer în multe medii cloud; pentru păstrarea datelor folosiți o bază de date gestionată.
