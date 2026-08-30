from __future__ import annotations

from fastapi import APIRouter

import ladelaug_avregning

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": ladelaug_avregning.__version__}
