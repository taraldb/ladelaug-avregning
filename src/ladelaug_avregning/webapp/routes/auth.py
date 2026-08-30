"""Authentication endpoints: password sign-in, sign-out, and the session probe.

``POST /api/auth/login`` checks the login rate limit *before* hashing, verifies
the password with argon2id, mints a server-side session, and sets an HttpOnly
cookie. Failure returns an indistinguishable ``401`` whether the email is
unknown, the password is wrong, or the account is disabled.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from ladelaug_avregning import __version__, security
from ladelaug_avregning.audit import AuditContext, record_audit
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.auth_tokens import AuthTokenRepo
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.domain.rate_limit import LoginRateLimiter
from ladelaug_avregning.domain.sessions import SessionRepo
from ladelaug_avregning.domain.users import UserRepo
from ladelaug_avregning.errors import AuthError
from ladelaug_avregning.webapp.deps import get_config, get_current_user, get_db, require_fetch
from ladelaug_avregning.webapp.schemas import (
    EmailRequest,
    LoginRequest,
    PasswordResetRequest,
    TokenConsumeRequest,
    UserOut,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _start_session(
    db: Database, config: AppConfig, request: Request, response: Response, user_id: int
) -> None:
    auth = config.auth
    token = await SessionRepo(db).create(
        user_id=user_id,
        ttl_hours=auth.session_ttl_hours,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        auth.cookie_name,
        token,
        max_age=auth.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=auth.cookie_secure,
        path="/",
    )


@router.post("/login", dependencies=[Depends(require_fetch)])
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    auth = config.auth
    argon2 = (auth.argon2_time_cost, auth.argon2_memory_cost_kib, auth.argon2_parallelism)
    email_normalized = body.email.strip().lower()
    ip = _client_ip(request)

    limiter = LoginRateLimiter(
        db, max_attempts=auth.login_max_attempts, window_seconds=auth.login_window_seconds
    )
    limiter.check(email_normalized, ip)  # -> 429 (before any argon2 work)

    users = UserRepo(db)
    user = users.get_by_email(email_normalized)
    ctx = AuditContext(actor_user_id=user["id"] if user else None, actor_label=body.email, ip=ip)

    password_ok = (
        user is not None
        and user["password_hash"] is not None
        and not user["disabled"]
        and security.verify_password(user["password_hash"], body.password)
    )
    if not password_ok:
        reason = "disabled" if user is not None and user["disabled"] else "bad_credentials"
        await limiter.record(email_normalized, ip, succeeded=False)
        await record_audit(
            db,
            ctx,
            event_type="user.sign_in_failed",
            entity_type="user",
            entity_id=user["id"] if user else None,
            summary=f"Failed sign-in for {body.email}",
            detail={"reason": reason},
        )
        raise AuthError("Invalid email or password", status=401)

    await limiter.record(email_normalized, ip, succeeded=True)

    if security.needs_rehash(
        user["password_hash"],
        time_cost=argon2[0],
        memory_cost=argon2[1],
        parallelism=argon2[2],
    ):
        await users.set_password(
            int(user["id"]), body.password, actor=AuditContext.system(), argon2=argon2
        )

    token = await SessionRepo(db).create(
        user_id=int(user["id"]),
        ttl_hours=auth.session_ttl_hours,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        auth.cookie_name,
        token,
        max_age=auth.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=auth.cookie_secure,
        path="/",
    )
    await record_audit(
        db,
        ctx,
        event_type="user.signed_in",
        entity_type="user",
        entity_id=int(user["id"]),
        summary=f"{body.email} signed in",
    )
    return {"user": UserOut.from_row(user).model_dump()}


@router.post("/logout", dependencies=[Depends(require_fetch)])
async def logout(
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    token = request.cookies.get(config.auth.cookie_name)
    if token:
        await SessionRepo(db).revoke(token)
    response.delete_cookie(config.auth.cookie_name, path="/")
    await record_audit(
        db,
        AuditContext(
            actor_user_id=int(user["id"]), actor_label=user["email"], ip=_client_ip(request)
        ),
        event_type="user.signed_out",
        entity_type="user",
        entity_id=int(user["id"]),
        summary=f"{user['email']} signed out",
    )
    return {"ok": True}


@router.get("/me")
async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    out = UserOut.from_row(user).model_dump()
    out["version"] = __version__
    return out


# --- passwordless sign-in (US-102) & password reset (US-103) ----------


@router.post("/magic-link", dependencies=[Depends(require_fetch)])
async def request_magic_link(
    body: EmailRequest,
    request: Request,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    user = UserRepo(db).get_by_email(body.email)
    if user and not user["disabled"] and user["email"]:
        token = await AuthTokenRepo(db).issue(
            user_id=int(user["id"]),
            kind="magic_link",
            ttl_minutes=config.email.magic_link_ttl_minutes,
            ip=_client_ip(request),
        )
        link = f"{config.email.base_url.rstrip('/')}/auth/magic-link?token={token}"
        await NotificationRepo(db).enqueue(
            to_address=user["email"],
            subject="Innloggingslenke – ladelaug",
            body_text=(
                "Klikk lenken for å logge inn (gyldig i "
                f"{config.email.magic_link_ttl_minutes} minutter):\n\n{link}\n\n"
                "Ba du ikke om dette, kan du se bort fra e-posten."
            ),
            template="magic_link",
            related_entity_type="user",
            related_entity_id=int(user["id"]),
        )
        await record_audit(
            db,
            AuditContext(
                actor_user_id=int(user["id"]), actor_label=user["email"], ip=_client_ip(request)
            ),
            event_type="auth.magic_link_requested",
            entity_type="user",
            entity_id=int(user["id"]),
            summary=f"Magic-link requested for {user['email']}",
        )
    return {"ok": True}


@router.post("/magic-link/consume", dependencies=[Depends(require_fetch)])
async def consume_magic_link(
    body: TokenConsumeRequest,
    request: Request,
    response: Response,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    user_id = await AuthTokenRepo(db).consume(token=body.token, kind="magic_link")
    user = UserRepo(db).get(user_id)
    if user is None or user["disabled"]:
        raise AuthError("This link is no longer valid", status=401)
    await _start_session(db, config, request, response, user_id)
    ctx = AuditContext(actor_user_id=user_id, actor_label=user["email"], ip=_client_ip(request))
    await record_audit(
        db,
        ctx,
        event_type="auth.magic_link_used",
        entity_type="user",
        entity_id=user_id,
        summary=f"{user['email']} signed in via magic link",
    )
    await record_audit(
        db,
        ctx,
        event_type="user.signed_in",
        entity_type="user",
        entity_id=user_id,
        summary=f"{user['email']} signed in",
    )
    return {"user": UserOut.from_row(user).model_dump()}


@router.post("/password-reset/request", dependencies=[Depends(require_fetch)])
async def request_password_reset(
    body: EmailRequest,
    request: Request,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    user = UserRepo(db).get_by_email(body.email)
    if user and not user["disabled"] and user["email"]:
        token = await AuthTokenRepo(db).issue(
            user_id=int(user["id"]),
            kind="password_reset",
            ttl_minutes=config.email.password_reset_ttl_minutes,
            ip=_client_ip(request),
        )
        link = f"{config.email.base_url.rstrip('/')}/auth/reset?token={token}"
        await NotificationRepo(db).enqueue(
            to_address=user["email"],
            subject="Tilbakestill passord – ladelaug",
            body_text=(
                "Klikk lenken for å velge nytt passord (gyldig i "
                f"{config.email.password_reset_ttl_minutes} minutter):\n\n{link}\n\n"
                "Ba du ikke om dette, kan du se bort fra e-posten."
            ),
            template="password_reset",
            related_entity_type="user",
            related_entity_id=int(user["id"]),
        )
        await record_audit(
            db,
            AuditContext(
                actor_user_id=int(user["id"]), actor_label=user["email"], ip=_client_ip(request)
            ),
            event_type="auth.password_reset_requested",
            entity_type="user",
            entity_id=int(user["id"]),
            summary=f"Password reset requested for {user['email']}",
        )
    return {"ok": True}


@router.post("/password-reset/consume", dependencies=[Depends(require_fetch)])
async def consume_password_reset(
    body: PasswordResetRequest,
    request: Request,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    auth = config.auth
    argon2 = (auth.argon2_time_cost, auth.argon2_memory_cost_kib, auth.argon2_parallelism)
    user_id = await AuthTokenRepo(db).consume(token=body.token, kind="password_reset")
    user = UserRepo(db).get(user_id)
    if user is None or user["disabled"]:
        raise AuthError("This link is no longer valid", status=401)
    ctx = AuditContext(actor_user_id=user_id, actor_label=user["email"], ip=_client_ip(request))
    await UserRepo(db).set_password(user_id, body.password, actor=ctx, argon2=argon2)
    await SessionRepo(db).revoke_all_for_user(user_id)
    await record_audit(
        db,
        ctx,
        event_type="auth.password_reset",
        entity_type="user",
        entity_id=user_id,
        summary=f"Password reset for {user['email']}; all sessions revoked",
    )
    if user["email"]:
        await NotificationRepo(db).enqueue(
            to_address=user["email"],
            subject="Passordet ditt ble endret",
            body_text="Passordet til ladelaug-kontoen din ble nettopp endret. "
            "Var det ikke deg, kontakt styret straks.",
            template="password_changed",
            related_entity_type="user",
            related_entity_id=user_id,
        )
    return {"ok": True}
