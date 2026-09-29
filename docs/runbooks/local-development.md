# Local Development Runbook

## Prerequisites

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose (optional for pure unit testing, required for sandbox runner)

## Fast Setup (Windows PowerShell)

```powershell
# 1. Backend environment
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 2. Configure environment
Copy-Item ..\.env.example ..\.env

# 3. Run backend unit tests
python -m pytest -m "not docker and not db" -q

# 4. Start API server
uvicorn app.main:app --reload --port 8000
```

## Running Frontend

```powershell
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```
