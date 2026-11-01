import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.db.repositories import TenantRepository
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import SkillStatus, UnavailabilityCategory
from mission_control.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from mission_control.services import audit
from mission_control.services.skills import resolve_skill

PUBLIC_CATEGORIES = {UnavailabilityCategory.LEAVE.value, UnavailabilityCategory.TRAINING.value}


# ---------------------------------------------------------------- lookup & visibility


def resolve_crew(repo: TenantRepository, ref: str) -> m.CrewProfile:
    """Accept 'me', a crew id, a member email, or an unambiguous display name."""
    ctx = repo.ctx
    if str(ref).lower() == "me":
        if ctx.crew_id is None:
            raise NotFound("You do not have a crew profile.", code="crew.no_profile")
        return repo.get(m.CrewProfile, ctx.crew_id, "Crew member")
    try:
        return repo.get(m.CrewProfile, uuid.UUID(str(ref)), "Crew member")
    except ValueError:
        pass
    ref_l = str(ref).strip().lower()
    by_email = repo.db.scalars(
        repo.select(m.CrewProfile)
        .join(m.Membership, m.Membership.id == m.CrewProfile.membership_id)
        .join(m.User, m.User.id == m.Membership.user_id)
        .where(m.User.email == ref_l)
    ).all()
    matches = (
        by_email or repo.db.scalars(repo.select(m.CrewProfile, func.lower(m.CrewProfile.display_name) == ref_l)).all()
    )
    if not matches:
        raise NotFound(f"Crew member '{ref}' not found.", code="crew.not_found")
    if len(matches) > 1:
        raise Conflict(
            f"'{ref}' matches more than one crew member; use their email.",
            code="crew.ambiguous",
            matches=[{"id": str(c.id), "name": c.display_name, "email": c.membership.user.email} for c in matches],
        )
    return matches[0]


def crew_for_read(repo: TenantRepository, ref: str) -> m.CrewProfile:
    crew = resolve_crew(repo, ref)
    if repo.ctx.is_crew and crew.id != repo.ctx.crew_id:
        raise NotFound("Crew member not found.", code="crew.not_found")
    return crew


def _require_self(ctx: TenantContext, crew: m.CrewProfile, action: str) -> None:
    if crew.id != ctx.crew_id:
        if ctx.is_crew:
            raise NotFound("Crew member not found.", code="crew.not_found")
        raise Forbidden(f"Only the crew member can {action} on their own profile.", code="crew.self_only")


def _require_self_or_director(ctx: TenantContext, crew: m.CrewProfile) -> None:
    if crew.id != ctx.crew_id and not ctx.is_director:
        if ctx.is_crew:
            raise NotFound("Crew member not found.", code="crew.not_found")
        raise Forbidden("Only the crew member or a Director can do this.", code="crew.self_or_director")


# ---------------------------------------------------------------- profiles


def list_crew(db: Session, ctx: TenantContext, skill_ref: str | None = None, active_only: bool = True):
    repo = TenantRepository(db, ctx)
    if ctx.is_crew:
        return [repo.get(m.CrewProfile, ctx.crew_id, "Crew member")] if ctx.crew_id else []
    criteria = [m.CrewProfile.active.is_(True)] if active_only else []
    stmt = repo.select(m.CrewProfile, *criteria).order_by(m.CrewProfile.display_name)
    if skill_ref:
        skill = resolve_skill(repo, skill_ref)
        stmt = stmt.where(m.CrewProfile.id.in_(select(m.CrewSkill.crew_id).where(m.CrewSkill.skill_id == skill.id)))
    return list(db.scalars(stmt).unique().all())


def create_crew(
    db: Session,
    ctx: TenantContext,
    *,
    member_ref: str,
    display_name: str | None,
    bio: str | None,
    now: datetime,
) -> m.CrewProfile:
    repo = TenantRepository(db, ctx)
    member = None
    try:
        member = repo.first(m.Membership, m.Membership.id == uuid.UUID(member_ref))
    except ValueError:
        member = db.scalar(
            repo.select(m.Membership)
            .join(m.User, m.User.id == m.Membership.user_id)
            .where(m.User.email == member_ref.strip().lower())
        )
    if member is None:
        raise NotFound(f"Member '{member_ref}' not found.", code="member.not_found")
    if repo.first(m.CrewProfile, m.CrewProfile.membership_id == member.id):
        raise Conflict("This member already has a crew profile.", code="crew.exists")
    crew = repo.add(m.CrewProfile(membership_id=member.id, display_name=display_name or member.user.name, bio=bio))
    audit.record(db, ctx, entity_type="crew", entity_id=crew.id, action="crew.created", now=now)
    db.commit()
    db.refresh(crew)
    return crew


def update_crew(db: Session, ctx: TenantContext, ref: str, changes: dict, *, now: datetime) -> m.CrewProfile:
    repo = TenantRepository(db, ctx)
    crew = crew_for_read(repo, ref)
    _require_self_or_director(ctx, crew)
    if "active" in changes and changes["active"] is not None and not ctx.is_director:
        raise Forbidden("Only a Director can activate or deactivate crew profiles.", code="crew.director_only")
    for key in ("display_name", "bio", "active"):
        if changes.get(key) is not None:
            setattr(crew, key, changes[key])
    audit.record(
        db,
        ctx,
        entity_type="crew",
        entity_id=crew.id,
        action="crew.updated",
        now=now,
        changes={k: v for k, v in changes.items() if v is not None},
    )
    db.commit()
    return crew


# ---------------------------------------------------------------- skills on a profile


def set_own_skill(db: Session, ctx: TenantContext, ref: str, skill_ref: str, level: int, *, now: datetime):
    repo = TenantRepository(db, ctx)
    crew = resolve_crew(repo, ref)
    _require_self(ctx, crew, "declare skills")
    skill = resolve_skill(repo, skill_ref, active_only=True)
    cs = repo.first(m.CrewSkill, m.CrewSkill.crew_id == crew.id, m.CrewSkill.skill_id == skill.id)
    if cs is None:
        cs = repo.add(m.CrewSkill(crew_id=crew.id, skill_id=skill.id, claimed_level=level))
        cs.status = SkillStatus.UNVERIFIED.value
        action = "skill.declared"
    else:
        action = "skill.changed"
        if level != cs.claimed_level:
            # Editing sends a verified skill back for verification; the last verified level keeps
            # counting for matching until someone verifies the new claim.
            cs.claimed_level = level
            cs.status = SkillStatus.UNVERIFIED.value
    db.flush()
    audit.record(db, ctx, entity_type="crew", entity_id=crew.id, action=action, now=now, skill=skill.name, level=level)
    db.commit()
    db.refresh(crew)
    return crew


def remove_own_skill(db: Session, ctx: TenantContext, ref: str, skill_ref: str, *, now: datetime):
    repo = TenantRepository(db, ctx)
    crew = resolve_crew(repo, ref)
    _require_self(ctx, crew, "remove skills")
    skill = resolve_skill(repo, skill_ref)
    cs = repo.first(m.CrewSkill, m.CrewSkill.crew_id == crew.id, m.CrewSkill.skill_id == skill.id)
    if cs is None:
        raise NotFound(f"{skill.name} is not on this profile.", code="crew_skill.not_found")
    db.delete(cs)
    audit.record(db, ctx, entity_type="crew", entity_id=crew.id, action="skill.removed", now=now, skill=skill.name)
    db.commit()
    db.refresh(crew)
    return crew


def verify_skill(
    db: Session,
    ctx: TenantContext,
    ref: str,
    skill_ref: str,
    *,
    level: int | None,
    cert_expires_on: date | None,
    now: datetime,
):
    repo = TenantRepository(db, ctx)
    crew = resolve_crew(repo, ref)
    if crew.id == ctx.crew_id:
        raise Forbidden(
            "You cannot verify skills on your own profile; another Director or Lead must do it.",
            code="crew_skill.self_verification",
        )
    skill = resolve_skill(repo, skill_ref)
    cs = repo.first(m.CrewSkill, m.CrewSkill.crew_id == crew.id, m.CrewSkill.skill_id == skill.id)
    if cs is None:
        raise NotFound(f"{crew.display_name} has not declared {skill.name}.", code="crew_skill.not_found")
    verified = level or cs.claimed_level
    before = {"claimed": cs.claimed_level, "verified": cs.verified_level}
    cs.verified_level = verified
    cs.claimed_level = verified
    cs.status = SkillStatus.VERIFIED.value
    cs.verified_by = ctx.membership_id
    cs.verified_at = now
    if cert_expires_on is not None:
        cs.cert_expires_on = cert_expires_on
    audit.record(
        db,
        ctx,
        entity_type="crew",
        entity_id=crew.id,
        action="skill.verified",
        now=now,
        skill=skill.name,
        before=before,
        level=verified,
        cert_expires_on=str(cert_expires_on or ""),
    )
    db.commit()
    db.refresh(crew)
    return crew


# ---------------------------------------------------------------- unavailability


def list_unavailability(db: Session, ctx: TenantContext, ref: str) -> tuple[m.CrewProfile, list[dict]]:
    repo = TenantRepository(db, ctx)
    crew = crew_for_read(repo, ref)
    rows = repo.list(m.Unavailability, m.Unavailability.crew_id == crew.id, order_by=m.Unavailability.period)
    full = ctx.is_director or crew.id == ctx.crew_id
    return crew, [present_window(w, full=full) for w in rows]


def present_window(w: m.Unavailability, *, full: bool) -> dict:
    out = {"id": w.id, "starts_at": w.period.lower, "ends_at": w.period.upper}
    if full:
        out.update(category=w.category, label=w.category, note=w.note)
    else:
        # Leads see that someone is unavailable, but MEDICAL/OTHER detail and notes stay private.
        label = w.category if w.category in PUBLIC_CATEGORIES else "Unavailable"
        out.update(category=None, label=label, note=None)
    return out


def add_unavailability(
    db: Session,
    ctx: TenantContext,
    ref: str,
    *,
    starts_at: datetime,
    ends_at: datetime,
    category: UnavailabilityCategory,
    note: str | None,
    now: datetime,
) -> dict:
    if ends_at <= starts_at:
        raise ValidationFailed("The end must be after the start.", code="unavailability.invalid_window")
    repo = TenantRepository(db, ctx)
    crew = crew_for_read(repo, ref)
    _require_self_or_director(ctx, crew)
    period = Range(starts_at, ends_at, bounds="[)")
    clash = db.scalar(
        repo.select(m.Assignment).where(
            m.Assignment.crew_id == crew.id,
            m.Assignment.state == "ACCEPTED",
            m.Assignment.blocked_period.overlaps(period),
        )
    )
    if clash is not None:
        raise Conflict(
            f"This overlaps your accepted assignment on {clash.mission.code}. Withdraw from it first "
            f"(`mc assignment withdraw {clash.id} --reason ...`) or ask the lead to release you.",
            code="unavailability.overlaps_assignment",
            mission_code=clash.mission.code,
            assignment_id=str(clash.id),
        )
    window = repo.add(m.Unavailability(crew_id=crew.id, period=period, category=category.value, note=note))
    audit.record(
        db,
        ctx,
        entity_type="crew",
        entity_id=crew.id,
        action="unavailability.added",
        now=now,
        starts_at=starts_at,
        ends_at=ends_at,
        category=category.value,
    )
    db.commit()
    return present_window(window, full=True)


def remove_unavailability(db: Session, ctx: TenantContext, ref: str, window_id: str, *, now: datetime) -> None:
    repo = TenantRepository(db, ctx)
    crew = crew_for_read(repo, ref)
    _require_self_or_director(ctx, crew)
    window = repo.get(m.Unavailability, window_id, "Unavailability window")
    if window.crew_id != crew.id:
        raise NotFound("Unavailability window not found.")
    db.delete(window)
    audit.record(db, ctx, entity_type="crew", entity_id=crew.id, action="unavailability.removed", now=now)
    db.commit()
