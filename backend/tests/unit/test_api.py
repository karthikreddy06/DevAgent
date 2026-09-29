"""Unit tests for FastAPI endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.unit
async def test_healthz_endpoint() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/healthz")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["app"] == "DevAgent"


@pytest.mark.unit
async def test_public_config_endpoint() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/config")
        assert res.status_code == 200
        data = res.json()
        assert "secret_key" not in data
        assert data["app_name"] == "DevAgent"


@pytest.mark.unit
async def test_root_endpoint() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/")
        assert res.status_code == 200
        data = res.json()
        assert data["app"] == "DevAgent"
        assert "X-Request-ID" in res.headers
