from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.db.repositories import TenantRepository
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import Role
from mission_control.domain.errors import Conflict, Forbidden, ValidationFailed
from mission_control.security import hash_password
from mission_control.services import audit

SETTINGS_FIELDS = ("approvals_required", "recovery_buffer_days", "stale_offer_days")


def get_org(db: Session, ctx: TenantContext) -> m.Organisation:
    return db.get(m.Organisation, ctx.org_id)


def update_settings(db: Session, ctx: TenantContext, changes: dict, *, now: datetime) -> m.Organisation:
    org = db.get(m.Organisation, ctx.org_id)
    before = {k: getattr(org, k) for k in SETTINGS_FIELDS}
    for key, value in changes.items():
        if key in SETTINGS_FIELDS and value is not None:
            setattr(org, key, value)
    db.flush()
    after = {k: getattr(org, k) for k in SETTINGS_FIELDS}
    if before != after:
        audit.record(
            db,
            ctx,
            entity_type="organisation",
            entity_id=org.id,
            action="settings.updated",
            now=now,
            before=before,
            after=after,
        )
    db.commit()
    return org


def list_members(db: Session, ctx: TenantContext) -> list[m.Membership]:
    repo = TenantRepository(db, ctx)
    return list(repo.list(m.Membership, order_by=m.Membership.created_at))


def get_member(db: Session, ctx: TenantContext, member_id) -> m.Membership:
    return TenantRepository(db, ctx).get(m.Membership, member_id, "Member")


def add_member(
    db: Session, ctx: TenantContext, *, email: str, name: str, role: Role, password: str, now: datetime
) -> m.Membership:
    email = email.strip().lower()
    if "@" not in email:
        raise ValidationFailed("Email address is not valid.", code="member.invalid_email")
    user = db.scalar(select(m.User).where(m.User.email == email))
    if user is None:
        user = m.User(email=email, name=name, password_hash=hash_password(password))
        db.add(user)
        db.flush()
    repo = TenantRepository(db, ctx)
    if repo.first(m.Membership, m.Membership.user_id == user.id):
        raise Conflict(f"{email} is already a member of this organisation.", code="member.exists")
    member = repo.add(m.Membership(user_id=user.id, role=role.value))
    audit.record(
        db,
        ctx,
        entity_type="membership",
        entity_id=member.id,
        action="member.added",
        now=now,
        email=email,
        role=role.value,
    )
    db.commit()
    return member


def update_member(
    db: Session, ctx: TenantContext, member_id, *, role: Role | None, active: bool | None, now: datetime
) -> m.Membership:
    member = TenantRepository(db, ctx).get(m.Membership, member_id, "Member")
    if member.id == ctx.membership_id and (active is False or (role and role != Role.DIRECTOR)):
        raise Forbidden("You cannot deactivate or demote yourself.", code="member.self_change")
    changes = {}
    if role is not None and role.value != member.role:
        changes["role"] = [member.role, role.value]
        member.role = role.value
    if active is not None and active != member.active:
        changes["active"] = [member.active, active]
        member.active = active
    if changes:
        audit.record(
            db,
            ctx,
            entity_type="membership",
            entity_id=member.id,
            action="member.updated",
            now=now,
            **changes,
        )
    db.commit()
    return member
