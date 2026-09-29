# DevAgent backend

FastAPI API + arq worker for DevAgent. See the repository root `README.md` for
the full product and architecture documentation.

## Layout

```
app/
  api/            HTTP routes (thin), dependencies, SSE gateway, error handlers
  agents/         planner, codebase, debugger, tester (security/docs/git are stubs)
  core/           settings, logging + redaction, errors, security, paths, rate limiting
  database/       async engine, session, declarative base
  llm/            provider-independent LLM + embedding abstraction
  models/         SQLAlchemy models (one module per domain area)
  orchestration/  task state machine, orchestrator, budgets, repair loop
  retrieval/      discovery, ignore rules, parsers, chunking, indexing, hybrid retrieval
  schemas/        Pydantic request/response models
  services/       orchestration-free business logic used by API + worker
  tools/          permissioned tool registry: filesystem, search, git, docker sandbox
  workers/        arq settings + job functions (long-running, isolated from the API)
```

## Local development (Windows)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item ..\.env.example ..\.env      # then edit if needed
.\.venv\Scripts\python.exe -m pytest -m "not docker and not db" -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

The worker is started separately (it owns the docker socket and git writes):

```powershell
.\.venv\Scripts\python.exe -m arq app.workers.settings.WorkerSettings
```

## Tests

| Marker   | Requires                             | Command                                     |
| -------- | ------------------------------------ | ------------------------------------------- |
| (none)   | nothing (pure units)                 | `pytest -m "not docker and not db" -q`      |
| `db`     | `TEST_DATABASE_URL` (Postgres+pgvector) | `pytest -m db -q`                        |
| `docker` | running Docker daemon + runner image | `pytest -m docker -q`                       |
| `e2e`    | database + docker + fixture repo     | `pytest -m e2e -q`                           |
