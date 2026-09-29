# DevAgent

DevAgent is an autonomous software engineering agent system that explores, investigates, fixes, and tests codebases inside isolated docker sandboxes with strict security boundaries and human-in-the-loop approval gates.

## Architecture

- **Backend**: FastAPI + SQLAlchemy 2.0 (asyncpg) + pgvector + Redis (arq worker).
- **Frontend**: React 18 + TypeScript + Vite with a dark, glassmorphic UI.
- **Worker**: arq worker with docker daemon access for running ephemeral sandbox test containers.
- **Docker Sandbox**: `runner-python:3.12` container with `--network none`, non-root user, and resource limits.

## Quickstart

### 1. Environment Setup

```powershell
Copy-Item .env.example .env
```

### 2. Backend

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -m "not docker and not db" -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```powershell
cd frontend
npm install
npm run dev
```

### 4. Running the Complete Stack with Docker

```bash
docker compose up -d --build
```
Open [http://localhost:8080](http://localhost:8080) for the frontend or [http://localhost:8000/docs](http://localhost:8000/docs) for the OpenAPI swagger UI.

## Testing

| Command | Description |
|---|---|
| `pytest -m "not docker and not db" -q` | Fast unit tests (no DB or docker required) |
| `pytest -m db -q` | Database & pgvector integration tests |
| `pytest -m docker -q` | Docker sandbox runner tests |
