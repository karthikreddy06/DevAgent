# Sandbox runner image for Python projects.
#
# This image is the ONLY place untrusted repository code is executed. It is
# deliberately minimal: no git credentials, no DevAgent code, no secrets, and it
# is always started with --network=none, a read-only rootfs, dropped
# capabilities and a non-root user (see app/tools/docker/runner.py).
#
# Test tooling is baked in so that repositories which only need their declared
# test runner can execute with networking disabled entirely.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/runner \
    PATH="/home/runner/.local/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        build-essential \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Pinned test tooling for the MVP (pytest is the supported runner).
RUN python -m pip install --upgrade pip \
    && python -m pip install "pytest==8.3.4" "pytest-cov==6.0.0" "pytest-json-report==1.5.0" "fastapi>=0.109.0" "pydantic>=2.5.0" "httpx" "joblib" "scikit-learn" "numpy" "pandas"

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin runner \
    && mkdir -p /workspace \
    && chown -R runner:runner /workspace /home/runner

USER runner
WORKDIR /workspace

# No CMD: every execution is an explicit `docker exec` from the DevAgent worker.
CMD ["sleep", "infinity"]
