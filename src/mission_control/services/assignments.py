"""Assignment offers and responses (design.md section 6.1)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.db.repositories import TenantRepository
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import AssignmentSource, AssignmentState, MissionState
from mission_control.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from mission_control.services import audit, notifications
from mission_control.services.crew import resolve_crew
from mission_control.services.missions import (
    ACTIVE_ASSIGNMENT,
    _require_editor,
    _slot_of,
    assignments_of,
    blocked_period,
    material_change,
    resolve_mission,
)

WITHDRAWABLE = {MissionState.DRAFT.value, MissionState.PENDING_APPROVAL.value, MissionState.APPROVED.value}
EXITED = (AssignmentState.DECLINED.value, AssignmentState.WITHDRAWN.value)


def _org(db: Session, ctx: TenantContext) -> m.Organisation:
    return db.get(m.Organisation, ctx.org_id)


def _load(repo: TenantRepository, assignment_id: str) -> tuple[m.Assignment, m.Mission]:
    a = repo.get(m.Assignment, assignment_id, "Assignment")
    if repo.ctx.is_crew and a.crew_id != repo.ctx.crew_id:
        raise NotFound("Assignment not found.")
    mission = repo.get(m.Mission, a.mission_id, "Mission", lock=True)  # serialise per mission
    repo.db.refresh(a)
    return a, mission


def _reason(reason: str | None, what: str) -> str:
    if reason is None or not reason.strip():
        raise ValidationFailed(f"A reason is required to {what}.", code="assignment.reason_required")
    return reason.strip()


# ---------------------------------------------------------------- offers


def check_offer(db: Session, mission: m.Mission, slot: m.MissionSlot, crew: m.CrewProfile) -> None:
    """Structural rules for an offer. (Skill/availability eligibility is checked by the matcher rules.)"""
    if mission.state != MissionState.DRAFT.value:
        raise Conflict(f"Offers can only be made while {mission.code} is DRAFT.", code="assignment.mission_not_draft")
    if not crew.active:
        raise Conflict(f"{crew.display_name}'s profile is inactive.", code="assignment.crew_inactive")
    history = db.scalars(
        select(m.Assignment).where(m.Assignment.mission_id == mission.id, m.Assignment.crew_id == crew.id)
    ).all()
    if any(a.state in ACTIVE_ASSIGNMENT for a in history):
        raise Conflict(f"{crew.display_name} is already on {mission.code}.", code="assignment.duplicate_crew")
    exited = next((a for a in history if a.state in EXITED), None)
    if exited:
        verb = "declined" if exited.state == AssignmentState.DECLINED.value else "withdrew from"
        raise Conflict(f"{crew.display_name} {verb} {mission.code}.", code="assignment.crew_exited")
    taken = len([a for a in assignments_of(db, mission) if a.slot_id == slot.id])
    if taken >= slot.headcount:
        raise Conflict(f"{slot.role_name} is full ({taken}/{slot.headcount}).", code="assignment.slot_full")


def create_offer(
    db: Session,
    ctx: TenantContext,
    mission: m.Mission,
    slot: m.MissionSlot,
    crew: m.CrewProfile,
    *,
    source: AssignmentSource,
    now: datetime,
) -> m.Assignment:
    check_offer(db, mission, slot, crew)
    a = TenantRepository(db, ctx).add(
        m.Assignment(
            mission_id=mission.id,
            slot_id=slot.id,
            crew_id=crew.id,
            state=AssignmentState.PROPOSED.value,
            source=source.value,
            offered_by=ctx.membership_id,
            offered_at=now,
        )
    )
    audit.record(
        db,
        ctx,
        entity_type="assignment",
        entity_id=a.id,
        action="assignment.offered",
        now=now,
        mission=mission.code,
        slot=slot.role_name,
        crew=crew.display_name,
        source=source.value,
    )
    material_change(db, ctx, mission, f"{crew.display_name} offered {slot.role_name}", now)
    return a


def offer(
    db: Session,
    ctx: TenantContext,
    ref: str,
    slot_ref: str,
    crew_ref: str,
    *,
    now: datetime,
    eligibility=None,
) -> m.Assignment:
    repo = TenantRepository(db, ctx)
    mission = resolve_mission(repo, ref, lock=True)
    _require_editor(ctx, mission)
    slot = _slot_of(repo, mission, slot_ref)
    crew = resolve_crew(repo, crew_ref)
    check_offer(db, mission, slot, crew)  # structural rules first: clearer errors for duplicates/full slots
    if eligibility is not None:
        eligibility(db, ctx, mission, slot, crew)
    a = create_offer(db, ctx, mission, slot, crew, source=AssignmentSource.MANUAL, now=now)
    db.commit()
    return a


# ---------------------------------------------------------------- responses


def accept(db: Session, ctx: TenantContext, assignment_id: str, *, now: datetime) -> m.Assignment:
    repo = TenantRepository(db, ctx)
    a, mission = _load(repo, assignment_id)
    if a.crew_id != ctx.crew_id:
        raise NotFound("Assignment not found.")
    if a.state != AssignmentState.PROPOSED.value:
        raise Conflict(f"This offer is {a.state}, not PROPOSED.", code="assignment.not_proposed")
    if mission.state != MissionState.DRAFT.value:
        raise Conflict(
            f"{mission.code} is {mission.state}; this offer can no longer be accepted.",
            code="assignment.mission_not_draft",
        )
    period = blocked_period(mission, _org(db, ctx).recovery_buffer_days)
    window = db.scalar(
        repo.select(m.Unavailability).where(
            m.Unavailability.crew_id == a.crew_id,
            m.Unavailability.period.overlaps(period),
        )
    )
    if window is not None:
        raise Conflict(
            f"You are marked unavailable {window.period.lower:%Y-%m-%d} to {window.period.upper:%Y-%m-%d}, "
            f"which overlaps {mission.code}. Remove that window first or decline.",
            code="assignment.unavailable",
        )
    clash = _conflicting(db, ctx, a.crew_id, period)
    if clash is not None:
        raise _double_booked(clash)
    a.state = AssignmentState.ACCEPTED.value
    a.blocked_period = period
    a.responded_at = now
    try:
        db.flush()
    except IntegrityError as exc:
        # A concurrent acceptance won the race; the exclusion constraint is the final arbiter.
        if getattr(exc.orig, "sqlstate", None) != "23P01":
            raise
        db.rollback()
        raise _double_booked(_conflicting(db, ctx, a.crew_id, period)) from exc
    audit.record(
        db,
        ctx,
        entity_type="assignment",
        entity_id=a.id,
        action="assignment.accepted",
        now=now,
        mission=mission.code,
    )
    material_change(db, ctx, mission, f"{a.crew.display_name} accepted {a.slot.role_name}", now)
    db.commit()
    return a


def _double_booked(clash: m.Assignment | None) -> Conflict:
    if clash is None:
        return Conflict("You are already committed to an overlapping mission.", code="assignment.double_booked")
    return Conflict(
        f"You are already committed to {clash.mission.code} until {clash.blocked_period.upper:%Y-%m-%d} "
        "(incl. recovery).",
        code="assignment.double_booked",
        conflict={"mission_code": clash.mission.code, "until": str(clash.blocked_period.upper)},
    )


def _conflicting(db: Session, ctx: TenantContext, crew_id, period: Range) -> m.Assignment | None:
    return db.scalar(
        TenantRepository(db, ctx)
        .select(m.Assignment)
        .where(
            m.Assignment.crew_id == crew_id,
            m.Assignment.state == AssignmentState.ACCEPTED.value,
            m.Assignment.blocked_period.overlaps(period),
        )
    )


def decline(db: Session, ctx: TenantContext, assignment_id: str, reason: str | None, *, now: datetime):
    repo = TenantRepository(db, ctx)
    a, mission = _load(repo, assignment_id)
    if a.crew_id != ctx.crew_id:
        raise NotFound("Assignment not found.")
    text = _reason(reason, "decline an offer")
    if a.state != AssignmentState.PROPOSED.value:
        raise Conflict(f"This offer is {a.state}, not PROPOSED.", code="assignment.not_proposed")
    a.state, a.exit_reason, a.responded_at = AssignmentState.DECLINED.value, text, now
    audit.record(
        db,
        ctx,
        entity_type="assignment",
        entity_id=a.id,
        action="assignment.declined",
        now=now,
        mission=mission.code,
        reason=text,
    )
    if mission.state == MissionState.DRAFT.value:
        material_change(db, ctx, mission, f"{a.crew.display_name} declined {a.slot.role_name}", now)
    db.commit()
    return a


def withdraw(db: Session, ctx: TenantContext, assignment_id: str, reason: str | None, *, now: datetime):
    """Crew self-withdrawal from an ACCEPTED assignment (D18)."""
    repo = TenantRepository(db, ctx)
    a, mission = _load(repo, assignment_id)
    if a.crew_id != ctx.crew_id:
        raise NotFound("Assignment not found.")
    text = _reason(reason, "withdraw")
    if a.state != AssignmentState.ACCEPTED.value:
        raise Conflict(
            f"Only accepted assignments can be withdrawn from (this one is {a.state}).",
            code="assignment.not_accepted",
        )
    if mission.state not in WITHDRAWABLE:
        raise Conflict(
            f"{mission.code} is {mission.state}: the mission is under way or finished. "
            "Contact the mission lead, who can release you.",
            code="assignment.mission_under_way",
        )
    previous_state = mission.state
    a.state, a.exit_reason, a.responded_at = AssignmentState.WITHDRAWN.value, text, now
    audit.record(
        db,
        ctx,
        entity_type="assignment",
        entity_id=a.id,
        action="assignment.withdrawn",
        now=now,
        mission=mission.code,
        slot=a.slot.role_name,
        reason=text,
    )
    material_change(db, ctx, mission, f"{a.crew.display_name} withdrew from {a.slot.role_name}", now)
    notifications.notify(
        db,
        org_id=ctx.org_id,
        recipient_id=mission.owner_id,
        kind="crew.withdrew",
        mission_id=mission.id,
        now=now,
        mission_code=mission.code,
        crew=a.crew.display_name,
        slot=a.slot.role_name,
        reason=text,
        previous_state=previous_state,
        mission_state=mission.state,
        returned_to_draft=previous_state != mission.state,
    )
    db.commit()
    return a


def release(db: Session, ctx: TenantContext, assignment_id: str, *, now: datetime) -> m.Assignment:
    repo = TenantRepository(db, ctx)
    a, mission = _load(repo, assignment_id)
    if ctx.is_crew:
        raise Forbidden(
            "Crew members withdraw rather than release (`mc assignment withdraw`).", code="auth.role_required"
        )
    _require_editor(ctx, mission)
    if a.state not in ACTIVE_ASSIGNMENT:
        raise Conflict(f"This assignment is {a.state} and cannot be released.", code="assignment.not_active")
    a.state, a.responded_at = AssignmentState.RELEASED.value, now
    audit.record(
        db,
        ctx,
        entity_type="assignment",
        entity_id=a.id,
        action="assignment.released",
        now=now,
        mission=mission.code,
        crew=a.crew.display_name,
        slot=a.slot.role_name,
    )
    # Emergency release during an ACTIVE mission changes neither revision nor state, but is audited.
    if mission.state != MissionState.ACTIVE.value:
        material_change(db, ctx, mission, f"{a.crew.display_name} released from {a.slot.role_name}", now)
    db.commit()
    return a


def list_assignments(
    db: Session,
    ctx: TenantContext,
    *,
    crew_ref: str | None = None,
    mission_ref: str | None = None,
    state: str | None = None,
) -> list[m.Assignment]:
    repo = TenantRepository(db, ctx)
    stmt = repo.select(m.Assignment)
    if ctx.is_crew:
        stmt = stmt.where(m.Assignment.crew_id == ctx.crew_id)
    elif crew_ref:
        stmt = stmt.where(m.Assignment.crew_id == resolve_crew(repo, crew_ref).id)
    if mission_ref:
        stmt = stmt.where(m.Assignment.mission_id == resolve_mission(repo, mission_ref).id)
    if state:
        stmt = stmt.where(m.Assignment.state == state.upper())
    return list(db.scalars(stmt.order_by(m.Assignment.offered_at.desc())).unique().all())
