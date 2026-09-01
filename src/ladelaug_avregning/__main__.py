"""Command-line entry point.

python -m ladelaug_avregning serve            # run the HTTP server (default)
python -m ladelaug_avregning migrate          # apply migrations and exit
python -m ladelaug_avregning create-admin     # create an administrator account
python -m ladelaug_avregning low-balance-scan # enqueue low-balance warning emails
python -m ladelaug_avregning drain-mail       # send queued emails (cron)
python -m ladelaug_avregning run-job <name>   # run one scheduler job once
python -m ladelaug_avregning regenerate-reports [--settlement ID]  # rewrite state/reports/*
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ladelaug_avregning.config import AppConfig, load_config
from ladelaug_avregning.logging_setup import configure_logging
from ladelaug_avregning.security import MIN_PASSWORD_LENGTH as _MIN_PASSWORD_LEN
from ladelaug_avregning.security import WEAK_PASSWORDS as _WEAK_PASSWORDS

_DEFAULT_CONFIG = Path("config/config.yaml")


def _load_config_or_exit(path: Path) -> AppConfig:
    try:
        return load_config(path)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


def _argon2_params(config: AppConfig) -> tuple[int, int, int]:
    a = config.auth
    return (a.argon2_time_cost, a.argon2_memory_cost_kib, a.argon2_parallelism)


def _bootstrap_admin(config: AppConfig) -> None:
    """Create the configured admin on first run — only when ``users`` is empty."""
    ba = config.bootstrap_admin
    if not (ba.email and ba.password):
        return

    import asyncio
    import logging

    from ladelaug_avregning.audit import AuditContext
    from ladelaug_avregning.db import Database
    from ladelaug_avregning.domain.users import UserRepo
    from ladelaug_avregning.errors import DomainError

    log = logging.getLogger(__name__)

    if len(ba.password) < _MIN_PASSWORD_LEN or ba.password.lower() in _WEAK_PASSWORDS:
        log.warning(
            "bootstrap_admin: password for %s is too short or a known-weak value — "
            "not creating the account. Set a strong bootstrap_admin.password (>= %d chars) "
            "or run: python -m ladelaug_avregning create-admin",
            ba.email,
            _MIN_PASSWORD_LEN,
        )
        return

    db = Database(config.database.path)
    try:
        if db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        try:
            asyncio.run(
                UserRepo(db).create(
                    email=ba.email,
                    password=ba.password,
                    role="admin",
                    actor=AuditContext.system(),
                    argon2=_argon2_params(config),
                )
            )
        except DomainError:
            log.warning("bootstrap_admin: an account for %s already exists, skipping", ba.email)
            return
        log.info("bootstrap_admin: created administrator %s", ba.email)
    finally:
        db.close()


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from ladelaug_avregning.db import Database
    from ladelaug_avregning.webapp.app import create_app

    config = _load_config_or_exit(args.config)
    configure_logging(config.logging.level)
    _bootstrap_admin(config)
    db = Database(config.database.path)
    app = create_app(config, db)
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        proxy_headers=True,
        # Only trust X-Forwarded-* from the configured reverse proxy — a wildcard
        # would let any client spoof its IP and defeat the login rate limiter.
        forwarded_allow_ips=config.server.trusted_proxies,
    )
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    from ladelaug_avregning.db import Database

    config = _load_config_or_exit(args.config)
    configure_logging(config.logging.level)
    # Constructing Database runs the migrations.
    db = Database(config.database.path)
    db.close()
    print(f"Migrations applied. Database: {config.database.path}")
    return 0


def _prompt_password() -> str:
    import getpass

    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        print("Passwords do not match.", file=sys.stderr)
        raise SystemExit(1)
    return first


def _cmd_create_admin(args: argparse.Namespace) -> int:
    import asyncio

    from ladelaug_avregning.audit import AuditContext
    from ladelaug_avregning.db import Database
    from ladelaug_avregning.domain.users import UserRepo
    from ladelaug_avregning.errors import DomainError

    config = _load_config_or_exit(args.config)
    configure_logging(config.logging.level)

    password = args.password or _prompt_password()
    if len(password) < _MIN_PASSWORD_LEN:
        print(f"Password must be at least {_MIN_PASSWORD_LEN} characters.", file=sys.stderr)
        raise SystemExit(1)

    db = Database(config.database.path)
    try:
        user_id = asyncio.run(
            UserRepo(db).create(
                email=args.email,
                password=password,
                role="admin",
                actor=AuditContext.system(),
                argon2=_argon2_params(config),
            )
        )
    except DomainError as exc:
        if exc.code == "email_taken":
            print(f"An account with email {args.email!r} already exists.", file=sys.stderr)
            raise SystemExit(1) from exc
        raise
    finally:
        db.close()
    print(f"Created admin {args.email} (id={user_id})")
    return 0


def _cmd_low_balance_scan(args: argparse.Namespace) -> int:
    import asyncio

    from ladelaug_avregning.audit import AuditContext
    from ladelaug_avregning.db import Database
    from ladelaug_avregning.domain.notifications import NotificationRepo

    config = _load_config_or_exit(args.config)
    configure_logging(config.logging.level)
    db = Database(config.database.path)
    try:
        counts = asyncio.run(NotificationRepo(db).scan_low_balances(actor=AuditContext.system()))
    finally:
        db.close()
    print(
        "Low-balance scan: "
        f"scanned={counts['scanned']} below={counts['below']} "
        f"queued={counts['queued']} suppressed={counts['suppressed']}"
    )
    return 0


def _cmd_drain_mail(args: argparse.Namespace) -> int:
    import asyncio

    from ladelaug_avregning.audit import AuditContext
    from ladelaug_avregning.db import Database
    from ladelaug_avregning.domain.notifications import NotificationRepo
    from ladelaug_avregning.email.sender import build_sender

    config = _load_config_or_exit(args.config)
    configure_logging(config.logging.level)
    db = Database(config.database.path)
    try:
        sender = build_sender(config.email, state_dir=config.state_dir)
        result = asyncio.run(
            NotificationRepo(db).process_queue(sender, actor=AuditContext.system())
        )
    finally:
        db.close()
    print(
        "Mail drain: "
        f"due={result['due']} sent={result['sent']} "
        f"retried={result['retried']} failed={result['failed']}"
    )
    return 0


def _cmd_regenerate_reports(args: argparse.Namespace) -> int:
    from ladelaug_avregning.db import Database
    from ladelaug_avregning.domain.settlement import SettlementRepo

    config = _load_config_or_exit(args.config)
    configure_logging(config.logging.level)
    db = Database(config.database.path)
    try:
        repo = SettlementRepo(db, tz=config.timezone, state_dir=config.state_dir)
        if args.settlement is not None:
            targets = [args.settlement]
        else:
            targets = [s["id"] for s in repo.list() if s["status"] == "posted"]
        if not targets:
            print("No posted settlements to regenerate.")
            return 0
        for sid in targets:
            out = repo.regenerate_reports(sid)
            print(
                f"Settlement {out['settlement_id']} ({out['period_month']}): "
                f"wrote {len(out['files'])} files -> "
                f"{config.state_dir}/reports/{out['period_month']}/"
            )
    finally:
        db.close()
    return 0


def _cmd_run_job(args: argparse.Namespace) -> int:
    import asyncio

    from ladelaug_avregning.db import Database
    from ladelaug_avregning.scheduler.jobs import JOBS

    if args.name not in JOBS:
        print(f"Unknown job {args.name!r}. Choose from: {', '.join(sorted(JOBS))}", file=sys.stderr)
        raise SystemExit(1)

    config = _load_config_or_exit(args.config)
    configure_logging(config.logging.level)
    db = Database(config.database.path)
    try:
        result = asyncio.run(JOBS[args.name](db, config))
    finally:
        db.close()
    print(f"Job {args.name}: {result}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ladelaug_avregning")
    parser.add_argument("--config", type=Path, default=_DEFAULT_CONFIG, help="path to config.yaml")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="run the HTTP server (default)")
    sub.add_parser("migrate", help="apply database migrations and exit")

    ca = sub.add_parser("create-admin", help="create an administrator account")
    ca.add_argument("--email", required=True)
    ca.add_argument("--password", help="prompted for if omitted")

    sub.add_parser("low-balance-scan", help="enqueue low-balance warning emails")
    sub.add_parser("drain-mail", help="send queued emails (wire to cron)")

    rj = sub.add_parser("run-job", help="run one in-process scheduler job once")
    rj.add_argument("name", help="drain_mail | low_balance_scan | zaptec_sync_sessions")

    rr = sub.add_parser(
        "regenerate-reports",
        help="re-render state/reports/<period>/ for posted settlements (after a template change)",
    )
    rr.add_argument(
        "--settlement",
        type=int,
        default=None,
        help="only this settlement id (default: every posted settlement)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "serve"
    handler = {
        "serve": _cmd_serve,
        "migrate": _cmd_migrate,
        "create-admin": _cmd_create_admin,
        "low-balance-scan": _cmd_low_balance_scan,
        "drain-mail": _cmd_drain_mail,
        "run-job": _cmd_run_job,
        "regenerate-reports": _cmd_regenerate_reports,
    }[command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
