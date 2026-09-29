"""Shared schemas across all DevAgent endpoints."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class MessageResponse(BaseModel):
    message: str
    details: dict[str, Any] | None = None


class StatusResponse(BaseModel):
    status: str = "ok"


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 50


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
    database: str
    redis: str
    env: str
