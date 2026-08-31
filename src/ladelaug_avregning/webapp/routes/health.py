from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    # Unauthenticated liveness probe — no version or build info is disclosed
    # here. Authenticated callers get the version from GET /api/auth/me.
    return {"status": "ok"}
