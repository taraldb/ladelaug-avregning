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
_ZAPTEC_PASSWORD_ENV = "ZAPTEC_PASSWORD"
_ZAPTEC_CAPTURE_DIR_ENV = "ZAPTEC_CAPTURE_DIR"
_GMAIL_CLIENT_ID_ENV = "GMAIL_CLIENT_ID"
_GMAIL_CLIENT_SECRET_ENV = "GMAIL_CLIENT_SECRET"
_GMAIL_REFRESH_TOKEN_ENV = "GMAIL_REFRESH_TOKEN"

_EMAIL_BACKENDS = ("console", "file", "smtp", "gmail")


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


class SchedulerConfig(BaseModel):
    """In-process job scheduler. ``enabled`` is the master switch — the FastAPI
    lifespan only starts the loop when it is true (so the test suite, which runs
    the lifespan via ``TestClient``, never spins up a real scheduler). Per-job
    on/off and cron live in the ``job_schedules`` table, editable at runtime."""

    enabled: bool = False
    tick_seconds: int = 60


class ZaptecConfig(BaseModel):
    """Zaptec Public API (https://api.zaptec.com). ``enabled`` gates every sync
    endpoint. The password is normally left blank here and supplied via the
    ``ZAPTEC_PASSWORD`` environment variable (mirrors ``LADELAUG_SECRET_KEY``)."""

    enabled: bool = False
    base_url: str = "https://api.zaptec.com"
    token_url: str = "https://api.zaptec.com/oauth/token"
    username: str = ""
    password: str = ""
    installation_id: str = ""
    request_timeout_seconds: float = 30.0
    page_size: int = 500
    max_retries: int = 3
    # Shown to a member whose charging access has been warned/disabled — 1D
    # records the status and notifies; it does not call Zaptec to enforce it
    # (that is a Release 2 item). The portal is where an admin acts.
    portal_url: str = "https://portal.zaptec.com"
    # Debug: empty = off. A path (cwd-relative) makes the client write one
    # pretty-printed JSON file per Zaptec HTTP call there (token / chargers /
    # each chargehistory page); the bearer token and password are redacted.
    # Also settable via the ZAPTEC_CAPTURE_DIR environment variable.
    capture_dir: str = ""


class EmailConfig(BaseModel):
    """Outgoing mail. ``backend`` is ``console`` (log only), ``file`` (write
    ``.eml`` under ``state/mail/``), ``smtp``, or ``gmail`` (Gmail REST API with
    an OAuth2 refresh token — see ``scripts/gmail_oauth_bootstrap.py``).
    ``base_url`` is the public origin used to build links in emails (magic-link,
    reports).

    The ``gmail_*`` secrets are normally left blank here and supplied via the
    ``GMAIL_CLIENT_SECRET`` / ``GMAIL_REFRESH_TOKEN`` environment variables (or
    ``.env``), mirroring ``ZAPTEC_PASSWORD``. ``gmail_sender`` is the address the
    message is sent as; blank falls back to ``from_address`` (it must be the
    authenticated Gmail account or one of its verified "Send mail as" aliases)."""

    backend: str = "console"
    from_address: str = "ladelaug@example.com"
    base_url: str = "http://localhost:8080"
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_sender: str = ""
    magic_link_ttl_minutes: int = 30
    password_reset_ttl_minutes: int = 60


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    timezone: str = "Europe/Oslo"
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    bootstrap_admin: BootstrapAdminConfig = Field(default_factory=BootstrapAdminConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    zaptec: ZaptecConfig = Field(default_factory=ZaptecConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)

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

        env_zaptec_pw = os.environ.get(_ZAPTEC_PASSWORD_ENV, "").strip()
        if env_zaptec_pw:
            self.zaptec.password = env_zaptec_pw
        env_capture_dir = os.environ.get(_ZAPTEC_CAPTURE_DIR_ENV, "").strip()
        if env_capture_dir:
            self.zaptec.capture_dir = env_capture_dir
        if self.zaptec.enabled and not (self.zaptec.username and self.zaptec.password):
            problems.append(
                "zaptec.enabled is true but zaptec.username / zaptec.password are not both set "
                f"(password via config.yaml or the {_ZAPTEC_PASSWORD_ENV} environment variable)"
            )
        for env_name, attr in (
            (_GMAIL_CLIENT_ID_ENV, "gmail_client_id"),
            (_GMAIL_CLIENT_SECRET_ENV, "gmail_client_secret"),
            (_GMAIL_REFRESH_TOKEN_ENV, "gmail_refresh_token"),
        ):
            env_val = os.environ.get(env_name, "").strip()
            if env_val:
                setattr(self.email, attr, env_val)
        if self.email.backend not in _EMAIL_BACKENDS:
            problems.append(
                f"email.backend {self.email.backend!r} is not one of "
                + ", ".join(repr(b) for b in _EMAIL_BACKENDS)
            )
        if self.email.backend == "gmail" and not (
            self.email.gmail_client_id.strip()
            and self.email.gmail_client_secret.strip()
            and self.email.gmail_refresh_token.strip()
        ):
            problems.append(
                "email.backend is 'gmail' but gmail_client_id / gmail_client_secret / "
                f"gmail_refresh_token are not all set (secrets via {_GMAIL_CLIENT_SECRET_ENV} / "
                f"{_GMAIL_REFRESH_TOKEN_ENV} or .env; run scripts/gmail_oauth_bootstrap.py)"
            )

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            problems.append(f"timezone {self.timezone!r} is not a known IANA time zone")

        if self.logging.level.upper() not in _VALID_LOG_LEVELS:
            problems.append(
                f"logging.level {self.logging.level!r} is not one of {sorted(_VALID_LOG_LEVELS)}"
            )

        if self.scheduler.tick_seconds < 5:
            problems.append("scheduler.tick_seconds must be >= 5")

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
