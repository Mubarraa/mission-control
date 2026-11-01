"""Password hashing and token encoding."""

import uuid
from datetime import datetime, timedelta

import jwt
from pwdlib import PasswordHash

from mission_control.config import get_settings

_hasher = PasswordHash.recommended()  # argon2
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)


def issue_token(*, membership_id: uuid.UUID, org_id: uuid.UUID, role: str, now: datetime) -> tuple[str, datetime]:
    settings = get_settings()
    expires = now + timedelta(minutes=settings.token_ttl_minutes)
    payload = {
        "sub": str(membership_id),
        "org": str(org_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM), expires


def decode_token(token: str, *, now: datetime) -> dict:
    """Raises jwt.InvalidTokenError on a bad signature, malformed token or expiry."""
    payload = jwt.decode(
        token,
        get_settings().jwt_secret,
        algorithms=[_ALGORITHM],
        options={
            "verify_exp": False,
            "verify_iat": False,
            "verify_nbf": False,
            "require": ["sub", "org", "exp"],
        },
    )
    # Expiry is checked against the injectable clock rather than the wall clock.
    if payload["exp"] <= int(now.timestamp()):
        raise jwt.ExpiredSignatureError("token expired")
    return payload
