"""Application configuration.

A plain Pydantic v2 model tree loaded from ``config/config.yaml`` (not
``pydantic-settings``). ``load_config`` fails fast: a single ``ValueError`` with
every problem joined into one message, rather than surfacing them one restart at
a time.
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field, model_validator

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_SECRET_KEY_ENV = "LADELAUG_SECRET_KEY"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    static_dir: str = "frontend/dist"


class DatabaseConfig(BaseModel):
    path: str = "state/ladelaug.db"


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AuthConfig(BaseModel):
    secret_key: str = ""
    session_ttl_hours: int = 720
    cookie_secure: bool = True
    cookie_name: str = "ladelaug_session"
    login_max_attempts: int = 5
    login_window_seconds: int = 900
    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 65536
    argon2_parallelism: int = 2


class BootstrapAdminConfig(BaseModel):
    email: str = ""
    password: str = ""


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    timezone: str = "Europe/Oslo"
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    bootstrap_admin: BootstrapAdminConfig = Field(default_factory=BootstrapAdminConfig)

    @model_validator(mode="after")
    def _validate(self) -> AppConfig:
        problems: list[str] = []

        # An env var overrides / supplies the HMAC secret so it need never be
        # written to the YAML file.
        env_secret = os.environ.get(_SECRET_KEY_ENV, "").strip()
        if env_secret:
            self.auth.secret_key = env_secret
        if not self.auth.secret_key.strip():
            problems.append(
                f"auth.secret_key is empty — set it in config.yaml or the {_SECRET_KEY_ENV} "
                "environment variable"
            )

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            problems.append(f"timezone {self.timezone!r} is not a known IANA time zone")

        if self.logging.level.upper() not in _VALID_LOG_LEVELS:
            problems.append(
                f"logging.level {self.logging.level!r} is not one of {sorted(_VALID_LOG_LEVELS)}"
            )

        a = self.auth
        if a.argon2_time_cost < 1:
            problems.append("auth.argon2_time_cost must be >= 1")
        if a.argon2_memory_cost_kib < 8192:
            problems.append("auth.argon2_memory_cost_kib must be >= 8192")
        if a.argon2_parallelism < 1:
            problems.append("auth.argon2_parallelism must be >= 1")
        if a.session_ttl_hours < 1:
            problems.append("auth.session_ttl_hours must be >= 1")
        if a.login_max_attempts < 1:
            problems.append("auth.login_max_attempts must be >= 1")
        if a.login_window_seconds < 1:
            problems.append("auth.login_window_seconds must be >= 1")

        if problems:
            raise ValueError("Invalid configuration:\n  - " + "\n  - ".join(problems))
        return self


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal ``.env`` reader: ``KEY=value`` lines, ``#`` comments, no export
    keyword, no quoting rules. Uses ``setdefault`` so a real environment variable
    always wins over the file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip())


def load_config(path: Path) -> AppConfig:
    _load_dotenv()
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config/config.example.yaml to {path} and edit it."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(  # noqa: TRY004 - a bad config file is a value problem, not a type contract
            f"Config file {path} must contain a YAML mapping at the top level."
        )
    return AppConfig.model_validate(raw)
