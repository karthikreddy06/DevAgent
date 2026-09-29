# DevAgent - common tasks.
# Windows users: use scripts/*.ps1 instead (make is not installed by default).

.PHONY: help env up down logs ps build backend-install backend-dev worker-dev frontend-install frontend-dev \
        migrate revision test test-backend test-frontend test-integration test-docker lint fmt typecheck \
        sandbox-images fixture clean

help:
	@echo "env              create .env from .env.example if missing"
	@echo "up | down        start/stop the full docker stack"
	@echo "logs             tail backend+worker logs"
	@echo "backend-install  create backend venv and install deps (editable)"
	@echo "backend-dev      run FastAPI with reload on :8000"
	@echo "worker-dev       run the arq worker"
	@echo "frontend-dev     run Vite dev server on :5173"
	@echo "migrate          alembic upgrade head"
	@echo "revision         alembic autogenerate revision (m='message')"
	@echo "test             backend unit tests + frontend tests"
	@echo "test-docker      backend tests that require the docker daemon"
	@echo "sandbox-images   build the sandbox runner images"
	@echo "fixture          build the buggy fixture git repository"

env:
	@test -f .env || cp .env.example .env

up: env
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f backend worker

ps:
	docker compose ps

sandbox-images:
	docker build -f infra/sandbox/runner-python.Dockerfile -t devagent/runner-python:3.12 infra/sandbox

backend-install:
	cd backend && python -m pip install -e ".[dev]"

backend-dev:
	cd backend && uvicorn app.main:app --reload --port 8000

worker-dev:
	cd backend && arq app.workers.settings.WorkerSettings

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

migrate:
	cd backend && alembic upgrade head

revision:
	cd backend && alembic revision --autogenerate -m "$(m)"

test: test-backend test-frontend

test-backend:
	cd backend && python -m pytest -m "not docker and not db" -q

test-integration:
	cd backend && python -m pytest -m "db" -q

test-docker:
	cd backend && python -m pytest -m docker -q

test-frontend:
	cd frontend && npm run test -- --run

lint:
	cd backend && ruff check app tests && ruff format --check app tests

fmt:
	cd backend && ruff check --fix app tests && ruff format app tests

typecheck:
	cd backend && mypy app
	cd frontend && npx tsc --noEmit

fixture:
	python fixtures/build_fixture_repo.py

clean:
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache data
