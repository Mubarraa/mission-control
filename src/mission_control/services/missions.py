"""Missions, slots, material changes and lifecycle transitions."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.db.repositories import TenantRepository
from mission_control.domain import lifecycle as lc
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import ApprovalDecision, AssignmentState, MissionAction, MissionState
from mission_control.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from mission_control.services import audit
from mission_control.services.skills import resolve_skill

ACTIVE_ASSIGNMENT = (AssignmentState.PROPOSED.value, AssignmentState.ACCEPTED.value)


# ---------------------------------------------------------------- lookup


def resolve_mission(repo: TenantRepository, ref: str, *, lock: bool = False) -> m.Mission:
    """Accept a mission code (e.g. ART-12, case-insensitive) or id. Crew only see missions they are on."""
    try:
        mission = repo.get(m.Mission, uuid.UUID(str(ref)), "Mission", lock=lock)
    except ValueError:
        stmt = repo.select(m.Mission, func.upper(m.Mission.code) == str(ref).strip().upper())
        if lock:
            stmt = stmt.with_for_update()
        mission = repo.db.scalar(stmt)
        if mission is None:
            raise NotFound(f"Mission {ref} not found.", code="mission.not_found") from None
    if repo.ctx.is_crew and not _crew_is_on(repo, mission):
        raise NotFound(f"Mission {ref} not found.", code="mission.not_found")
    return mission


def _crew_is_on(repo: TenantRepository, mission: m.Mission) -> bool:
    if repo.ctx.crew_id is None:
        return False
    return (
        repo.first(m.Assignment, m.Assignment.mission_id == mission.id, m.Assignment.crew_id == repo.ctx.crew_id)
        is not None
    )


def view_of(db: Session, mission: m.Mission) -> lc.MissionView:
    approvers = db.scalars(
        select(m.Approval.approver_id).where(
            m.Approval.mission_id == mission.id,
            m.Approval.revision == mission.revision,
            m.Approval.decision == ApprovalDecision.APPROVE.value,
        )
    ).all()
    return lc.MissionView(
        code=mission.code,
        state=MissionState(mission.state),
        owner_id=mission.owner_id,
        starts_at=mission.starts_at,
        revision=mission.revision,
        submitted_by=mission.submitted_by,
        approvals_required=mission.approvals_required_snapshot or 1,
        approvers_this_revision=frozenset(approvers),
    )


def actor_of(ctx: TenantContext) -> lc.Actor:
    return lc.Actor(membership_id=ctx.membership_id, role=ctx.role)


def assignments_of(db: Session, mission: m.Mission, states=ACTIVE_ASSIGNMENT) -> list[m.Assignment]:
    stmt = select(m.Assignment).where(m.Assignment.mission_id == mission.id)
    if states:
        stmt = stmt.where(m.Assignment.state.in_(states))
    return list(db.scalars(stmt.order_by(m.Assignment.offered_at)).unique().all())


# ---------------------------------------------------------------- create / read / update


def create_mission(
    db: Session,
    ctx: TenantContext,
    *,
    name: str,
    description: str | None,
    starts_at: datetime,
    ends_at: datetime,
    now: datetime,
) -> m.Mission:
    _validate_window(starts_at, ends_at, now)
    prefix, seq = db.execute(
        update(m.Organisation)
        .where(m.Organisation.id == ctx.org_id)
        .values(mission_seq=m.Organisation.mission_seq + 1)
        .returning(m.Organisation.mission_prefix, m.Organisation.mission_seq)
    ).one()
    mission = TenantRepository(db, ctx).add(
        m.Mission(
            code=f"{prefix}-{seq}",
            name=name.strip(),
            description=description,
            starts_at=starts_at,
            ends_at=ends_at,
            state=MissionState.DRAFT.value,
            revision=1,
            owner_id=ctx.membership_id,
        )
    )
    audit.record(
        db,
        ctx,
        entity_type="mission",
        entity_id=mission.id,
        action="mission.created",
        now=now,
        code=mission.code,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.commit()
    return mission


def list_missions(db: Session, ctx: TenantContext, state: str | None = None) -> list[m.Mission]:
    repo = TenantRepository(db, ctx)
    stmt = repo.select(m.Mission)
    if state:
        stmt = stmt.where(m.Mission.state == state.upper())
    if ctx.is_crew:
        stmt = stmt.where(m.Mission.id.in_(select(m.Assignment.mission_id).where(m.Assignment.crew_id == ctx.crew_id)))
    return list(db.scalars(stmt.order_by(m.Mission.starts_at, m.Mission.code)).unique().all())


def update_mission(db: Session, ctx: TenantContext, ref: str, changes: dict, *, now: datetime) -> m.Mission:
    repo = TenantRepository(db, ctx)
    mission = resolve_mission(repo, ref, lock=True)
    _require_editor(ctx, mission)
    if changes.get("name"):
        mission.name = changes["name"].strip()
    if "description" in changes and changes["description"] is not None:
        mission.description = changes["description"]
    starts = changes.get("starts_at") or mission.starts_at
    ends = changes.get("ends_at") or mission.ends_at
    if (starts, ends) != (mission.starts_at, mission.ends_at):
        _validate_window(starts, ends, now)
        _require_editable(mission)
        old = (mission.starts_at, mission.ends_at)
        mission.starts_at, mission.ends_at = starts, ends
        _rebook_accepted(db, mission)
        material_change(db, ctx, mission, "window changed", now, before=old, after=(starts, ends))
    db.commit()
    return mission


def _rebook_accepted(db: Session, mission: m.Mission) -> None:
    """Window edits move the blocked period of accepted crew; the exclusion constraint guards overlaps."""
    buffer_days = db.scalar(select(m.Organisation.recovery_buffer_days).where(m.Organisation.id == mission.org_id))
    for a in assignments_of(db, mission, (AssignmentState.ACCEPTED.value,)):
        a.blocked_period = blocked_period(mission, buffer_days)
        name = a.crew.display_name
        try:
            db.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) != "23P01":
                raise
            db.rollback()
            raise Conflict(
                f"The new dates would double-book {name}, who is committed elsewhere. "
                "Release them first or choose other dates.",
                code="assignment.double_booked",
            ) from exc


def blocked_period(mission: m.Mission, buffer_days: int) -> Range:
    return Range(mission.starts_at, mission.ends_at + timedelta(days=buffer_days), bounds="[)")


def _validate_window(starts_at: datetime, ends_at: datetime, now: datetime) -> None:
    if starts_at.tzinfo is None or ends_at.tzinfo is None:
        raise ValidationFailed("Dates must include a timezone (UTC recommended).", code="mission.naive_datetime")
    if ends_at <= starts_at:
        raise ValidationFailed("The mission must end after it starts.", code="mission.invalid_window")
    if starts_at <= now:
        raise ValidationFailed("The mission cannot start in the past.", code="mission.start_in_past")


def _require_editor(ctx: TenantContext, mission: m.Mission) -> None:
    if ctx.is_crew:
        raise Forbidden("Crew members cannot edit missions.", code="auth.role_required")
    if not ctx.is_director and mission.owner_id != ctx.membership_id:
        raise Forbidden(f"Only the owner of {mission.code} or a Director can change it.", code="mission.not_owner")


def _require_editable(mission: m.Mission) -> None:
    if MissionState(mission.state) not in lc.EDITABLE:
        raise Conflict(f"{mission.code} is {mission.state} and can no longer be changed.", code="mission.locked")


def material_change(db: Session, ctx: TenantContext, mission: m.Mission, reason: str, now: datetime, **data) -> None:
    """Window, slots, requirements or assignments changed: bump the revision; pending/approved -> DRAFT."""
    _require_editable(mission)
    mission.revision += 1
    previous = mission.state
    if previous in (MissionState.PENDING_APPROVAL.value, MissionState.APPROVED.value):
        mission.state = MissionState.DRAFT.value
        audit.record(
            db,
            ctx,
            entity_type="mission",
            entity_id=mission.id,
            action="mission.auto_withdrawn",
            now=now,
            reason=reason,
            from_state=previous,
            revision=mission.revision,
        )
    audit.record(
        db,
        ctx,
        entity_type="mission",
        entity_id=mission.id,
        action="mission.changed",
        now=now,
        reason=reason,
        revision=mission.revision,
        **data,
    )
    db.flush()


# ---------------------------------------------------------------- slots


def add_slot(
    db: Session,
    ctx: TenantContext,
    ref: str,
    *,
    role_name: str,
    headcount: int,
    requirements: list[dict],
    now: datetime,
) -> m.Mission:
    repo = TenantRepository(db, ctx)
    mission = resolve_mission(repo, ref, lock=True)
    _require_editor(ctx, mission)
    _require_editable(mission)
    if not requirements:
        raise ValidationFailed("A slot needs at least one skill requirement.", code="slot.no_requirements")
    ordinal = (max((s.ordinal for s in mission.slots), default=0)) + 1
    slot = repo.add(
        m.MissionSlot(mission_id=mission.id, role_name=role_name.strip(), headcount=headcount, ordinal=ordinal)
    )
    _set_requirements(repo, slot, requirements)
    material_change(db, ctx, mission, f"slot {role_name} added", now, slot=role_name, headcount=headcount)
    db.commit()
    db.refresh(mission)
    return mission


def update_slot(db: Session, ctx: TenantContext, ref: str, slot_id: str, changes: dict, *, now: datetime):
    repo = TenantRepository(db, ctx)
    mission = resolve_mission(repo, ref, lock=True)
    _require_editor(ctx, mission)
    slot = _slot_of(repo, mission, slot_id)
    if changes.get("headcount") is not None:
        active = len([a for a in assignments_of(db, mission) if a.slot_id == slot.id])
        if changes["headcount"] < active:
            raise Conflict(
                f"{slot.role_name} has {active} active assignments; release some first.",
                code="slot.headcount_below_assigned",
            )
        slot.headcount = changes["headcount"]
    if changes.get("role_name"):
        slot.role_name = changes["role_name"].strip()
    if changes.get("requirements") is not None:
        for req in list(slot.requirements):
            db.delete(req)
        db.flush()
        _set_requirements(repo, slot, changes["requirements"])
    material_change(db, ctx, mission, f"slot {slot.role_name} changed", now)
    db.commit()
    db.refresh(mission)
    return mission


def remove_slot(db: Session, ctx: TenantContext, ref: str, slot_id: str, *, now: datetime) -> m.Mission:
    repo = TenantRepository(db, ctx)
    mission = resolve_mission(repo, ref, lock=True)
    _require_editor(ctx, mission)
    slot = _slot_of(repo, mission, slot_id)
    if db.scalar(select(func.count()).select_from(m.Assignment).where(m.Assignment.slot_id == slot.id)):
        raise Conflict(
            f"{slot.role_name} has assignment history; release crew and edit it instead.",
            code="slot.has_assignments",
        )
    db.delete(slot)
    material_change(db, ctx, mission, f"slot {slot.role_name} removed", now)
    db.commit()
    db.refresh(mission)
    return mission


def _slot_of(repo: TenantRepository, mission: m.Mission, slot_ref: str) -> m.MissionSlot:
    """Accept a slot id or role name (case-insensitive) within the mission."""
    for slot in mission.slots:
        if str(slot.id) == str(slot_ref) or slot.role_name.lower() == str(slot_ref).strip().lower():
            return slot
    raise NotFound(f"Slot '{slot_ref}' not found on {mission.code}.", code="slot.not_found")


def _set_requirements(repo: TenantRepository, slot: m.MissionSlot, requirements: list[dict]) -> None:
    seen = set()
    for req in requirements:
        skill = resolve_skill(repo, str(req["skill"]), active_only=True)
        if skill.id in seen:
            raise ValidationFailed(f"{skill.name} is listed twice for {slot.role_name}.", code="slot.duplicate_skill")
        seen.add(skill.id)
        repo.add(
            m.SlotRequirement(
                slot_id=slot.id,
                skill_id=skill.id,
                min_level=int(req["min_level"]),
                cert_required=bool(req.get("cert_required", False)),
            )
        )
    repo.db.refresh(slot)


def history(db: Session, ctx: TenantContext, ref: str) -> list[m.AuditEvent]:
    repo = TenantRepository(db, ctx)
    mission = resolve_mission(repo, ref)
    if not ctx.is_director and mission.owner_id != ctx.membership_id:
        raise Forbidden("Only Directors and the mission's lead can view its history.", code="mission.not_owner")
    slot_ids = [s.id for s in mission.slots]
    assignment_ids = db.scalars(select(m.Assignment.id).where(m.Assignment.mission_id == mission.id)).all()
    return list(
        repo.list(
            m.AuditEvent,
            m.AuditEvent.entity_id.in_([mission.id, *slot_ids, *assignment_ids]),
            order_by=m.AuditEvent.seq,
        )
    )


# ---------------------------------------------------------------- lifecycle transitions


def transition(
    db: Session,
    ctx: TenantContext,
    ref: str,
    action: MissionAction,
    *,
    revision: int | None = None,
    reason: str | None = None,
    now: datetime,
) -> m.Mission:
    repo = TenantRepository(db, ctx)
    mission = resolve_mission(repo, ref, lock=True)
    view = view_of(db, mission)
    target = lc.decide(view, action, actor_of(ctx), now)
    previous = mission.state

    if action in (MissionAction.APPROVE, MissionAction.REJECT):
        if revision is None:
            raise ValidationFailed("Include the revision you reviewed.", code="approval.revision_required")
        if revision != mission.revision:
            raise Conflict(
                f"{mission.code} has changed since you reviewed it (you saw revision {revision}, it is now "
                f"{mission.revision}). Review it again before deciding.",
                code="approval.stale",
                current_revision=mission.revision,
            )

    if action == MissionAction.SUBMIT:
        _check_submission_gate(db, mission)
        org = db.get(m.Organisation, ctx.org_id)
        mission.submitted_by = ctx.membership_id
        mission.submitted_revision = mission.revision
        mission.approvals_required_snapshot = org.approvals_required
        mission.state = target.value
    elif action == MissionAction.APPROVE:
        count, reached = lc.approval_outcome(view, ctx.membership_id)
        repo.add(
            m.Approval(
                mission_id=mission.id,
                revision=mission.revision,
                approver_id=ctx.membership_id,
                decision=ApprovalDecision.APPROVE.value,
                reason=reason,
            )
        )
        if reached:
            mission.state = target.value
        audit.record(
            db,
            ctx,
            entity_type="mission",
            entity_id=mission.id,
            action="mission.approval_recorded",
            now=now,
            revision=mission.revision,
            approvals=count,
            required=view.approvals_required,
        )
    elif action == MissionAction.REJECT:
        text = (reason or "").strip()
        if not text:
            raise ValidationFailed("A reason is required to reject a mission.", code="approval.reason_required")
        repo.add(
            m.Approval(
                mission_id=mission.id,
                revision=mission.revision,
                approver_id=ctx.membership_id,
                decision=ApprovalDecision.REJECT.value,
                reason=text,
            )
        )
        mission.state = target.value
        mission.revision += 1  # voids approvals recorded against the rejected revision
    elif action == MissionAction.WITHDRAW:
        mission.state = target.value
        mission.revision += 1
    elif action == MissionAction.CANCEL:
        for a in assignments_of(db, mission):
            a.state, a.responded_at = AssignmentState.RELEASED.value, now
        mission.state = target.value
    else:  # START, COMPLETE, ABORT
        mission.state = target.value

    if mission.state != previous:
        audit.record(
            db,
            ctx,
            entity_type="mission",
            entity_id=mission.id,
            action=f"mission.{action.value}",
            now=now,
            from_state=previous,
            to_state=mission.state,
            revision=mission.revision,
            **({"reason": reason.strip()} if reason and reason.strip() else {}),
        )
    db.commit()
    return mission


def _check_submission_gate(db: Session, mission: m.Mission) -> None:
    if not mission.slots:
        raise Conflict(f"{mission.code} has no crew slots yet.", code="mission.no_slots", unfilled=[])
    accepted = [a for a in assignments_of(db, mission, (AssignmentState.ACCEPTED.value,))]
    unfilled = []
    for slot in mission.slots:
        have = sum(1 for a in accepted if a.slot_id == slot.id)
        if have < slot.headcount:
            unfilled.append({"slot": slot.role_name, "accepted": have, "headcount": slot.headcount})
    if unfilled:
        listing = ", ".join(f"{u['slot']} ({u['accepted']}/{u['headcount']} accepted)" for u in unfilled)
        raise Conflict(
            f"Every position needs an accepted crew member before submitting. Unfilled: {listing}.",
            code="mission.unfilled_slots",
            unfilled=unfilled,
        )
