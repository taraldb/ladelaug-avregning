from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.errors import register_exception_handlers
from ladelaug_avregning.webapp.routes import audit, auth, health


def create_app(config: AppConfig, db: Database) -> FastAPI:
    app = FastAPI(title="ladelaug-avregning")
    app.state.config = config
    app.state.db = db

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(audit.router)

    # Mounted last so it only serves paths no /api route claimed.
    static_dir = Path(config.server.static_dir)
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")

    return app
