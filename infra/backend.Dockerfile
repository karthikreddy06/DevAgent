# DevAgent backend + worker image.
# Build context is the repository root (see docker-compose.yml).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git is required for repository ingestion; curl for container healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# ---------------------------------------------------------------------------
FROM base AS builder
COPY backend/pyproject.toml backend/README.md /srv/
COPY backend/app /srv/app
RUN python -m pip install --upgrade pip build \
    && python -m pip install .

# ---------------------------------------------------------------------------
FROM base AS runtime
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY backend/app /srv/app
COPY backend/alembic /srv/alembic
COPY backend/alembic.ini /srv/alembic.ini
COPY backend/README.md /srv/README.md

# Non-root runtime user. The docker socket is only mounted into the worker
# container, and sandbox containers never share this filesystem.
RUN useradd --create-home --uid 10001 devagent \
    && mkdir -p /data/workspaces /data/artifacts \
    && chown -R devagent:devagent /data /srv
USER devagent

ENV WORKSPACES_DIR=/data/workspaces \
    ARTIFACTS_DIR=/data/artifacts \
    PYTHONPATH=/srv

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
