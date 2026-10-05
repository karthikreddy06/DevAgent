# DevAgent

DevAgent is an autonomous software engineering agent system that investigates codebases, diagnoses bugs and features, proposes structured patches, and verifies fixes inside isolated Docker execution sandboxes with strict security boundaries and human-in-the-loop approval gates.

---

## Features

- **Autonomous Repository Analysis**: Ingests Git repositories, indexes AST chunks, and builds semantic understanding.
- **RAG-Based Code Understanding**: Hybrid vector search (pgvector) and full-text keyword retrieval (PostgreSQL FTS) to identify relevant source files.
- **Bug Investigation & Root-Cause Analysis**: Specialized multi-agent reasoning to diagnose regressions, test failures, and bug reports.
- **Structured Patch Proposals**: Generates structured file changes and diffs validated in isolated temporary workspaces before presentation.
- **Human Approval Workflow**: Strict approval gate ensures no changes are applied to the active repository without explicit human authorization.
- **Isolated Workspace**: Dedicated task workspaces prevent accidental modifications to host files or adjacent projects.
- **Docker Sandbox Execution**: Untrusted repository test commands execute in isolated, non-root `runner-python` containers with `--network none` and resource limits.
- **Automated Testing & Smart Selection**: Automatically selects and executes targeted unit tests before and after applying changes.
- **Retry & Failure Handling**: Automatic repair loops feed test failures and stack traces back to the debugging agent (up to configurable limits).
- **Git Branch Isolation**: Verified patches are committed to local `devagent/task-*` branches without pushing remotely.
- **Persistent Task Events**: Real-time event logging streamed via Server-Sent Events (SSE) to the frontend dashboard.
- **NO_CONFIRMED_BUG Safety Outcome**: Exits gracefully with an explanatory report instead of hallucinating speculative modifications when no bug exists.
- **Ollama Local Inference**: Fully functional with local open-source models (`llama3.2:1b`, `nomic-embed-text:latest`) and cloud providers (OpenAI / Anthropic).

---

## Architecture

```text
React Frontend (Vite)
        │
        ▼ (REST / SSE)
FastAPI Backend (API Server)
        │
        ▼ (arq Queue / Redis)
Task Orchestrator & Worker
        │
        ▼
RAG Hybrid Retrieval ──► Multi-Agent Team:
                           ├── Planner Agent (deconstructs task & strategy)
                           ├── Codebase Agent (explores symbols & dependencies)
                           └── Debugger Agent (reproduces issue & drafts fix)
        │
        ▼
Structured Patch Proposal (Validated in Temp Directory)
        │
        ▼
Human Approval Gate (AWAITING_APPROVAL)
        │
        ▼ (On Human Approve)
Isolated Workspace Branching
        │
        ▼
Docker Sandbox Execution (Network-Isolated runner container)
        │
        ▼
Automated Pytest Verification
        │
        ▼
Status: COMPLETED (Verified) / FAILED / REJECTED
```

### Specialized Agents

- **Planner Agent**: Analyzes task description, determines required stages, establishes file boundaries, and selects testing strategy.
- **Codebase Agent**: Navigates AST symbols, file headers, import hierarchies, and search results to isolate bug locations.
- **Debugger Agent**: Hypothesizes root cause, executes non-destructive tests in the sandbox, and crafts exact unified diff proposals.

---

## Tech Stack

- **Backend**: Python 3.11+ / FastAPI, SQLAlchemy 2.0 (Async), asyncpg, Alembic, Pydantic v2, structlog.
- **Database**: PostgreSQL 16 with `pgvector` extension (compatible with Supabase).
- **Queue / PubSub**: Redis 7, arq worker.
- **Sandbox Execution**: Docker Engine API, ephemeral `runner-python:3.12` containers with non-root user and strict Linux namespaces.
- **Frontend**: React 18, TypeScript, Vite, Tailwind-free glassmorphic design system, Lucide icons.
- **LLM / Embeddings**: Ollama (`llama3.2:1b`, `nomic-embed-text:latest`), OpenAI, or Anthropic.

---

## Project Structure

```text
devagent/
├── backend/
│   ├── alembic/                # Database schema migrations
│   ├── app/
│   │   ├── agents/             # Autonomous agent implementations (Planner, Codebase, Debugger)
│   │   ├── api/                # FastAPI routers (auth, tasks, changes, repos, health)
│   │   ├── core/               # Configuration, security, error handling, redaction
│   │   ├── database/           # Async SQLAlchemy session and connection lifecycle
│   │   ├── llm/                # LLM & Embedding provider implementations (Ollama, OpenAI, Anthropic)
│   │   ├── models/             # SQLAlchemy ORM models (Task, Approval, User, Repository)
│   │   ├── orchestration/      # State machine, proposal validator, budget tracker
│   │   ├── retrieval/          # AST chunking, PostgreSQL hybrid search (vector + FTS)
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── services/           # Business logic layer
│   │   ├── tools/              # Agent tools (Docker execution, filesystem, git, search)
│   │   └── workers/            # arq background worker settings and task jobs
│   ├── tests/                  # Unit and integration test suites
│   └── pyproject.toml          # Backend dependencies and tool configurations
├── frontend/
│   ├── src/
│   │   ├── api/                # API client with JWT handling and SSE streaming
│   │   ├── components/         # Reusable UI components (DiffViewer, Modals, Navbar, Sidebar)
│   │   ├── pages/              # Views (Dashboard, Repositories, Tasks, TaskDetail, Docs)
│   │   └── styles/             # Curated dark glassmorphism design system tokens
│   ├── index.html              # Frontend entry point
│   ├── package.json            # Node.js dependencies
│   └── vite.config.ts          # Vite configuration and development proxy
├── infra/
│   ├── backend.Dockerfile      # Multi-stage production build for backend & worker
│   ├── frontend.Dockerfile     # Multi-stage production build for React + Nginx
│   ├── nginx.conf              # Nginx reverse proxy configuration for frontend and SSE
│   └── sandbox/
│       └── runner-python.Dockerfile # Hardened sandbox execution container
├── docker-compose.yml          # Local and multi-container development configuration
├── docker-compose.prod.yml     # Production Docker Compose overrides (internal ports)
├── .env.example                # Documented configuration template
├── pytest.ini                  # Root pytest configuration
└── README.md                   # Project documentation
```

---

## Local Setup

### 1. Clone Repository
```bash
git clone https://github.com/your-org/devagent.git
cd devagent
```

### 2. Configure Environment
```bash
# PowerShell
Copy-Item .env.example .env

# Bash
cp .env.example .env
```
Edit `.env` to configure your PostgreSQL connection string, Redis URL, and LLM preferences.

### 3. Setup Ollama (Local Inference)
If using local Ollama for inference:
```bash
# Pull model and embedding model
ollama pull llama3.2:1b
ollama pull nomic-embed-text:latest

# Ensure Ollama is serving
ollama serve
```

### 4. Setup Backend Environment
```bash
cd backend
py -3.11 -m venv .venv

# Activate virtual environment
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

# Install dependencies in editable mode
pip install -e ".[dev]"
```

### 5. Setup Database & Run Migrations
Ensure PostgreSQL with `pgvector` extension is running (e.g. Supabase or local PostgreSQL 16):
```bash
# From backend directory
python -m alembic upgrade head
```

### 6. Start Backend API
```bash
# From backend directory
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```
API docs available at: `http://127.0.0.1:8010/docs`

### 7. Start Background Worker (Optional for local queue)
```bash
# From backend directory with Redis running
arq app.workers.settings.WorkerSettings
```
*(Note: If Redis is offline, the API falls back gracefully to in-process execution for local testing).*

### 8. Setup & Start Frontend
```bash
cd ../frontend
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Docker Setup

### 1. Build the Sandbox Runner Image
Before running sandbox tests, build the execution runner image:
```bash
docker build -f infra/sandbox/runner-python.Dockerfile -t devagent/runner-python:3.12 infra/sandbox
```

### 2. Run Complete Stack with Docker Compose
```bash
# Build and start services
docker compose up -d --build
```

Access points:
- **Frontend Dashboard**: [http://localhost:8080](http://localhost:8080)
- **Backend API Docs**: [http://localhost:8010/docs](http://localhost:8010/docs) (or proxied via frontend at `http://localhost:8080/api/docs`)
- **Health Check**: [http://localhost:8010/api/healthz](http://localhost:8010/api/healthz)

### 3. Production Compose Mode
To run in production mode with internal-only ports for Redis and Backend:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

---

## Environment Variables

| Variable | Description | Default / Example |
|---|---|---|
| `ENV` | Environment mode (`development`, `test`, `production`) | `development` |
| `DEBUG` | Enable verbose debugging (must be `false` in production) | `false` |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins | `http://localhost:5173,http://localhost:8080` |
| `SECRET_KEY` | Application secret key for signing | Secure 48+ char string |
| `JWT_SECRET` | Secret key for JWT access/refresh tokens | Secure 48+ char string |
| `DATABASE_URL` | PostgreSQL + pgvector connection string | `postgresql://user:pass@host:5432/dbname` |
| `REDIS_URL` | Redis connection URL for worker queue | `redis://localhost:6379/0` |
| `LLM_PROVIDER` | Inference provider (`ollama`, `openai`, `anthropic`) | `ollama` |
| `LLM_MODEL` | Model identifier | `llama3.2:1b` (Ollama) / `gpt-4o-mini` (OpenAI) |
| `LLM_BASE_URL` | Base URL for LLM provider (e.g. Ollama endpoint) | `http://localhost:11434` |
| `LLM_API_KEY` | API key (required for OpenAI / Anthropic) | *(Empty for Ollama)* |
| `EMBEDDING_PROVIDER`| Embedding provider (`ollama`, `openai`) | `ollama` |
| `EMBEDDING_MODEL` | Embedding model | `nomic-embed-text:latest` |
| `EMBEDDING_DIM` | Embedding vector dimensionality | `768` (Ollama) / `1536` (OpenAI) |
| `SANDBOX_ENABLED` | Enable Docker sandbox for test execution | `true` |
| `SANDBOX_IMAGE` | Docker image for Python test execution | `devagent/runner-python:3.12` |
| `VITE_API_BASE_URL`| Frontend API endpoint base | `/api` |

---

## Database Configuration

DevAgent uses PostgreSQL with the `pgvector` extension for storing repositories, tasks, audit logs, file chunks, and embeddings:
- Compatible with self-hosted PostgreSQL 16+ or Supabase.
- Migrations are tracked via Alembic:
  - `001_initial_schema`: Base tables, vector extension, indexes, and constraints.
  - `002_task_types`: Extended task categories (`bug_fix`, `refactor`, `test`, `documentation`).

To apply migrations manually:
```bash
cd backend
python -m alembic upgrade head
```

---

## Testing

### Backend Unit & Integration Tests
```bash
# Run all unit tests from project root
python -m pytest backend/tests

# Run with coverage report
python -m pytest backend/tests --cov=app
```

### Frontend Tests & Typecheck
```bash
cd frontend

# Run unit tests
npm test -- --run

# Run TypeScript compilation check
npx tsc --noEmit

# Run production build validation
npm run build
```

---

## Security Model & Invariants

DevAgent strictly enforces ten core security invariants:
1. **AI cannot modify target repository before approval**: The agent only reads and proposes. File writes to the target project are forbidden before explicit human review.
2. **AWAITING_APPROVAL is required before APPLYING**: The state machine forbids transitioning to `APPLYING` without an approval record.
3. **No approval means no patch application**: If an approval is rejected or missing, patch application aborts immediately.
4. **Code execution remains sandboxed**: Testing and command execution only occur inside ephemeral, capability-dropped, network-isolated Docker containers.
5. **Repository workspace paths remain contained**: Path traversal attacks (`../`, symlinks) are blocked at the tool boundary.
6. **Tool write permissions are strictly restricted**: Write tools are restricted based on current task phase and state.
7. **No remote Git push is performed automatically**: Changes are preserved on local Git branches inside the workspace; remote repositories are never modified.
8. **User credentials/secrets are never returned in API responses**: Automatic redaction scrubs credentials, database connection strings, and tokens from logs and payloads.
9. **No fabricated patch can bypass validation**: Patches undergo syntactic diff validation and test dry-run in a temporary directory prior to approval.
10. **NO_CONFIRMED_BUG prevents patch generation**: When no bug is confirmed, the agent concludes safely without proposing changes.

---

## Task Lifecycle

Tasks move deterministically through the following state machine:

```text
CREATED
   │
   ▼
PLANNING ────────────► ANALYZING ────────────► INVESTIGATING
                                                      │
         ┌────────────────────────────────────────────┴──────────────────────┐
         ▼                                                                   ▼
    FIX_PROPOSED                                                       NO_CONFIRMED_BUG
         │                                                                   │
         ▼                                                                   ▼
 AWAITING_APPROVAL                                                       COMPLETED
         │
   ┌─────┴─────────────────────┐
   ▼                           ▼
APPLYING                    REJECTED
   │
   ▼
TESTING
   │
   ├───────────────────────────┬───────────────────────────┐
   ▼                           ▼                           ▼
COMPLETED (Verified)         FAILED                 RETRY (Auto Repair)
                                                           │
                                                           ▼
                                                     INVESTIGATING
```

---

## Deployment Guidelines

### Container Deployment (Docker / VPS)
1. Provision a host running Linux with Docker Engine and Docker Compose.
2. Clone repository and configure `.env` with production secrets:
   ```bash
   python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
   python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))"
   ```
3. Set `ENV=production`, `DEBUG=false`, and configure `DATABASE_URL`.
4. Deploy the stack:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```

### Reverse Proxy & SSL
For HTTPS production deployments:
- Configure a reverse proxy (e.g. Caddy, Traefik, or AWS ALB) in front of the frontend container (port 80).
- Forward `Host`, `X-Real-IP`, and `X-Forwarded-For` headers.
- Disable proxy buffering for `/api/tasks/*/events` and `/api/chats/*/stream` to ensure Server-Sent Events stream smoothly without buffering.

---

## Screenshots / Demo

*(Screenshots and live demonstration link can be placed here).*

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
