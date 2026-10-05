# Contributing to DevAgent

Thank you for your interest in contributing to DevAgent! We welcome contributions from the community.

## Code of Conduct

Please maintain a respectful, constructive, and inclusive environment for everyone.

## Development Workflow

### 1. Prerequisites
- Python 3.11 or 3.12
- Node.js 20+ (recommended 24) and npm
- Docker Engine (for sandbox test execution)
- Git

### 2. Local Environment Setup
```bash
# Clone the repository
git clone https://github.com/your-org/devagent.git
cd devagent

# Setup backend environment
cd backend
py -3.11 -m venv .venv
# On Linux/macOS: source .venv/bin/activate
# On Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Setup frontend environment
cd ../frontend
npm install
```

### 3. Environment Configuration
Copy `.env.example` to `.env` in the repository root and configure your database, Redis, and LLM endpoints:
```bash
cp .env.example .env
```

### 4. Running Verification Checks
Before submitting a PR, make sure all checks pass:

#### Backend
```bash
# Run from repository root
python -m pytest backend/tests

# Check formatting and linting
ruff check backend/app backend/tests
ruff format --check backend/app backend/tests
mypy --config-file backend/pyproject.toml backend/app
```

#### Frontend
```bash
cd frontend
npm run lint
npx tsc --noEmit
npm test -- --run
npm run build
```

## Security Invariants

All contributions must preserve DevAgent's core security invariants:
1. **Human Approval Gate**: The agent cannot apply patches to a target repository without explicit human approval (`AWAITING_APPROVAL -> APPLYING`).
2. **Sandbox Isolation**: Untrusted repository test commands only execute inside isolated Docker containers with `--network none`, dropped capabilities, and non-root users.
3. **Workspace Isolation**: Repository workspaces remain strictly contained within allocated directories. No paths may escape the workspace directory.
4. **Git Branch Isolation**: Changes are staged to local `devagent/task-*` branches and are never pushed to remote remotes automatically.
5. **Secret Redaction**: Credentials, tokens, and passwords are never returned in API responses or logs.
6. **NO_CONFIRMED_BUG Outcome**: If no reproducible bug or issue is found, the agent must output `NO_CONFIRMED_BUG` and not propose speculative patches.

## Pull Request Guidelines

1. Create a descriptive feature branch (`git checkout -b feature/my-feature`).
2. Include unit or integration tests for new functionality.
3. Commit messages should be concise and follow conventional commits (`feat: ...`, `fix: ...`, `chore: ...`).
4. Ensure CI passes on your branch before requesting review.
