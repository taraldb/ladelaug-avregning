"""Password hashing (argon2id) and opaque session-token helpers.

The raw session token is only ever held in the client cookie; the server stores
``hash_token(token)`` (a plain SHA-256, no salt needed for a 256-bit random
token) as the primary key of the ``sessions`` row.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Config defaults (see AuthConfig). Passed explicitly so callers can dial them
# down for a low-power host or up later without touching this module.
DEFAULT_TIME_COST = 3
DEFAULT_MEMORY_COST_KIB = 65536
DEFAULT_PARALLELISM = 2


def _hasher(time_cost: int, memory_cost: int, parallelism: int) -> PasswordHasher:
    return PasswordHasher(
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
    )


def hash_password(
    password: str,
    *,
    time_cost: int = DEFAULT_TIME_COST,
    memory_cost: int = DEFAULT_MEMORY_COST_KIB,
    parallelism: int = DEFAULT_PARALLELISM,
) -> str:
    return _hasher(time_cost, memory_cost, parallelism).hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher(DEFAULT_TIME_COST, DEFAULT_MEMORY_COST_KIB, DEFAULT_PARALLELISM).verify(
            password_hash, password
        )
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(
    password_hash: str,
    *,
    time_cost: int = DEFAULT_TIME_COST,
    memory_cost: int = DEFAULT_MEMORY_COST_KIB,
    parallelism: int = DEFAULT_PARALLELISM,
) -> bool:
    try:
        return _hasher(time_cost, memory_cost, parallelism).check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
