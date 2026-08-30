from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.errors import register_exception_handlers
from ladelaug_avregning.webapp.routes import (
    audit,
    auth,
    chargers,
    charging,
    health,
    ledger,
    me,
    members,
    settlement,
    zaptec,
)


class SPAStaticFiles(StaticFiles):
    """Static files with a single-page-app fallback: any GET that would 404
    (a client-side route like ``/members/3`` on a hard refresh) returns
    ``index.html`` instead, so React Router can take over. ``/api/*`` is
    unaffected — those routes are registered before this mount."""

    async def get_response(self, path: str, scope: Any) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api/"):
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and not path.startswith("api/"):
            return await super().get_response("index.html", scope)
        return response


def create_app(config: AppConfig, db: Database) -> FastAPI:
    app = FastAPI(title="ladelaug-avregning")
    app.state.config = config
    app.state.db = db

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(audit.router)
    app.include_router(members.router)
    app.include_router(chargers.router)
    app.include_router(zaptec.router)
    app.include_router(charging.router)
    app.include_router(settlement.router)
    app.include_router(ledger.router)
    app.include_router(me.router)

    # Mounted last so it only serves paths no /api route claimed.
    static_dir = Path(config.server.static_dir)
    if static_dir.is_dir():
        app.mount("/", SPAStaticFiles(directory=str(static_dir), html=True), name="frontend")

    return app
