import uuid
from dataclasses import dataclass
from datetime import datetime

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import Role
from mission_control.domain.errors import Unauthenticated
from mission_control.security import decode_token, hash_password, issue_token, verify_password

_BAD_LOGIN = "Invalid email, password or organisation."
_DUMMY_HASH = hash_password("timing-equaliser")


@dataclass
class LoginResult:
    token: str
    expires_at: datetime
    membership: m.Membership
    org: m.Organisation


def login(db: Session, *, email: str, password: str, org_slug: str, now: datetime) -> LoginResult:
    """Every failure returns the same error, so the endpoint never reveals which orgs an email belongs to."""
    row = db.execute(
        select(m.Membership, m.Organisation)
        .join(m.User, m.User.id == m.Membership.user_id)
        .join(m.Organisation, m.Organisation.id == m.Membership.org_id)
        .where(m.User.email == email.strip().lower(), m.Organisation.slug == org_slug.strip().lower())
    ).one_or_none()
    if row is None:
        verify_password(password, _DUMMY_HASH)
        raise Unauthenticated(_BAD_LOGIN, code="auth.invalid_credentials")
    membership, org = row
    if not verify_password(password, membership.user.password_hash) or not membership.active:
        raise Unauthenticated(_BAD_LOGIN, code="auth.invalid_credentials")
    token, expires = issue_token(membership_id=membership.id, org_id=org.id, role=membership.role, now=now)
    return LoginResult(token=token, expires_at=expires, membership=membership, org=org)


def context_from_token(db: Session, token: str, *, now: datetime) -> TenantContext:
    try:
        claims = decode_token(token, now=now)
        membership_id = uuid.UUID(claims["sub"])
        org_id = uuid.UUID(claims["org"])
    except (jwt.InvalidTokenError, ValueError, KeyError) as exc:
        raise Unauthenticated("Your session is invalid or has expired. Log in again.") from exc
    # Re-load the membership on every request: deactivation and role changes take effect immediately.
    membership = db.get(m.Membership, membership_id)
    if membership is None or membership.org_id != org_id or not membership.active:
        raise Unauthenticated("Your session is invalid or has expired. Log in again.")
    crew_id = db.scalar(select(m.CrewProfile.id).where(m.CrewProfile.membership_id == membership.id))
    return TenantContext(
        org_id=org_id,
        membership_id=membership.id,
        user_id=membership.user_id,
        role=Role(membership.role),
        crew_id=crew_id,
    )
