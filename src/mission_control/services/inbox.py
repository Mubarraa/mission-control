"""Role-aware inbox: everything that needs the current member's attention, notifications first."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.db.repositories import TenantRepository
from mission_control.domain import lifecycle as lc
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import ApprovalDecision, AssignmentState, MissionState
from mission_control.services import notifications
from mission_control.services.missions import actor_of, assignments_of, view_of


def build(db: Session, ctx: TenantContext, *, now: datetime) -> dict:
    repo = TenantRepository(db, ctx)
    org = db.get(m.Organisation, ctx.org_id)
    inbox: dict = {
        "role": ctx.role.value,
        "notifications": [
            {
                "id": n.id,
                "kind": n.kind,
                "mission_id": n.mission_id,
                "data": n.data,
                "created_at": n.created_at,
            }
            for n in notifications.unread_for(db, ctx)
        ],
        "approvals": [],
        "missions": [],
        "stale_offer_days": org.stale_offer_days,
        "offers": [],
        "skills_awaiting_verification": [],
    }

    if ctx.is_director:
        pending = repo.list(
            m.Mission, m.Mission.state == MissionState.PENDING_APPROVAL.value, order_by=m.Mission.starts_at
        )
        actor = actor_of(ctx)
        for mission in pending:
            view = view_of(db, mission)
            submitter = db.get(m.Membership, mission.submitted_by) if mission.submitted_by else None
            inbox["approvals"].append(
                {
                    "code": mission.code,
                    "name": mission.name,
                    "starts_at": mission.starts_at,
                    "revision": mission.revision,
                    "submitted_by": submitter.user.name if submitter else None,
                    "received": len(view.approvers_this_revision),
                    "required": view.approvals_required,
                    "can_approve": lc.can_approve(view, actor),
                    "needs_other_approver": ctx.membership_id in (mission.submitted_by, mission.owner_id),
                    "already_approved": ctx.membership_id in view.approvers_this_revision,
                }
            )

    if ctx.is_planner:
        owned = repo.list(
            m.Mission,
            m.Mission.owner_id == ctx.membership_id,
            m.Mission.state.in_(
                [MissionState.DRAFT.value, MissionState.PENDING_APPROVAL.value, MissionState.APPROVED.value]
            ),
            order_by=m.Mission.starts_at,
        )
        for mission in owned:
            item = _mission_attention(db, mission, org.stale_offer_days, now)
            if item:
                inbox["missions"].append(item)

    if ctx.crew_id:
        for a in (
            db.scalars(
                repo.select(m.Assignment)
                .where(
                    m.Assignment.crew_id == ctx.crew_id,
                    m.Assignment.state == AssignmentState.PROPOSED.value,
                )
                .order_by(m.Assignment.offered_at)
            )
            .unique()
            .all()
        ):
            inbox["offers"].append(
                {
                    "assignment_id": a.id,
                    "mission_code": a.mission.code,
                    "mission_name": a.mission.name,
                    "slot": a.slot.role_name,
                    "starts_at": a.mission.starts_at,
                    "ends_at": a.mission.ends_at,
                    "offered_at": a.offered_at,
                }
            )
        for cs in repo.list(m.CrewSkill, m.CrewSkill.crew_id == ctx.crew_id, m.CrewSkill.status == "UNVERIFIED"):
            inbox["skills_awaiting_verification"].append(
                {
                    "skill": cs.skill.name,
                    "claimed_level": cs.claimed_level,
                    "verified_level": cs.verified_level,
                }
            )
    return inbox


def _mission_attention(db: Session, mission: m.Mission, stale_days: int, now: datetime) -> dict | None:
    active = assignments_of(db, mission)
    draft = mission.state == MissionState.DRAFT.value
    slots, unfilled, offers = [], [], []
    for slot in mission.slots:  # slot order
        mine = [a for a in active if a.slot_id == slot.id]
        accepted = [a for a in mine if a.state == AssignmentState.ACCEPTED.value]
        pending = []
        for a in mine:
            if a.state != AssignmentState.PROPOSED.value:
                continue
            age = (now - a.offered_at).total_seconds() / 86400
            offer = {
                "assignment_id": a.id,
                "crew": a.crew.display_name,
                "slot": slot.role_name,
                "age_days": round(age, 1),
                "stale": age > stale_days,
            }
            pending.append(offer)
            offers.append(offer)
        slots.append(
            {
                "slot": slot.role_name,
                "headcount": slot.headcount,
                "accepted": [a.crew.display_name for a in accepted],
                "offered": pending,
                "open": slot.headcount - len(mine),
            }
        )
        if len(accepted) < slot.headcount:
            unfilled.append(
                {
                    "slot": slot.role_name,
                    "accepted": len(accepted),
                    "offered": len(pending),
                    "headcount": slot.headcount,
                }
            )
    exits = (
        [
            {"crew": a.crew.display_name, "slot": a.slot.role_name, "state": a.state, "reason": a.exit_reason}
            for a in assignments_of(db, mission, (AssignmentState.DECLINED.value, AssignmentState.WITHDRAWN.value))
        ]
        if draft
        else []
    )
    rejection = None
    if draft:
        last = db.scalar(
            select(m.Approval)
            .where(m.Approval.mission_id == mission.id)
            .order_by(m.Approval.created_at.desc())
            .limit(1)
        )
        if last is not None and last.decision == ApprovalDecision.REJECT.value:
            rejection = {"reason": last.reason, "by": db.get(m.Membership, last.approver_id).user.name}
    if not (draft or offers):
        return None
    return {
        "code": mission.code,
        "name": mission.name,
        "state": mission.state,
        "starts_at": mission.starts_at,
        "slots": slots if draft else [],
        "accepted_total": sum(len(sl["accepted"]) for sl in slots),
        "positions_total": sum(sl["headcount"] for sl in slots),
        "unfilled": unfilled if draft else [],
        "offers": offers,
        "exits": exits,
        "rejection": rejection,
        "ready_to_submit": draft and bool(mission.slots) and not unfilled,
    }
