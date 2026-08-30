"""Settlement endpoints. Phase C ships only the participant suggestion (US-203);
the draft/preview/post engine lands in Release 1B and grows this module.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning import clock
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.webapp.deps import get_db, require_admin
from ladelaug_avregning.webapp.schemas import SuggestedParticipantOut

router = APIRouter(
    prefix="/api/settlement", dependencies=[Depends(require_admin)], tags=["settlement"]
)


@router.get("/suggested-participants")
async def suggested_participants(
    on_date: str | None = None, db: Database = Depends(get_db)
) -> dict[str, Any]:
    resolved = on_date or clock.today_oslo().isoformat()
    rows = MemberRepo(db).suggested_participants(resolved)
    return {
        "on_date": resolved,
        "participants": [SuggestedParticipantOut(**r) for r in rows],
    }
