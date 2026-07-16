"""Liveness and readiness endpoints."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from myagent import __version__

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "myagent-python"
    version: str = __version__


class ReadinessResponse(BaseModel):
    status: Literal["ready"] = "ready"
    checks: dict[str, Literal["ok"]] = {"application": "ok"}


@router.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    """Report whether the HTTP process is alive."""

    return LivenessResponse()


@router.get("/ready", response_model=ReadinessResponse)
async def ready() -> ReadinessResponse:
    """Report whether the currently implemented application layer is ready."""

    return ReadinessResponse()

