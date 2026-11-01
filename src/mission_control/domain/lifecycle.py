"""Mission lifecycle rules (design.md section 6). Pure: no database, no HTTP.

Services pass in a `MissionView` snapshot and an `Actor`; this module answers
"is this allowed, and what state comes next?" and explains refusals in plain language.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from mission_control.domain.enums import MissionAction as A
from mission_control.domain.enums import MissionState as S
from mission_control.domain.enums import Role
from mission_control.domain.errors import Conflict, Forbidden

TRANSITIONS: dict[tuple[S, A], S] = {
    (S.DRAFT, A.SUBMIT): S.PENDING_APPROVAL,
    (S.PENDING_APPROVAL, A.APPROVE): S.APPROVED,  # only once enough approvals are in
    (S.PENDING_APPROVAL, A.REJECT): S.DRAFT,
    (S.PENDING_APPROVAL, A.WITHDRAW): S.DRAFT,
    (S.APPROVED, A.START): S.ACTIVE,
    (S.ACTIVE, A.COMPLETE): S.COMPLETED,
    (S.ACTIVE, A.ABORT): S.ABORTED,
    (S.DRAFT, A.CANCEL): S.CANCELLED,
    (S.PENDING_APPROVAL, A.CANCEL): S.CANCELLED,
    (S.APPROVED, A.CANCEL): S.CANCELLED,
}

TERMINAL = {S.COMPLETED, S.CANCELLED, S.ABORTED}
EDITABLE = {S.DRAFT, S.PENDING_APPROVAL, S.APPROVED}  # material edits allowed (pending/approved -> DRAFT)
APPROVER_ACTIONS = {A.APPROVE, A.REJECT}


@dataclass(frozen=True)
class Actor:
    membership_id: uuid.UUID
    role: Role


@dataclass(frozen=True)
class MissionView:
    code: str
    state: S
    owner_id: uuid.UUID
    starts_at: datetime
    revision: int
    submitted_by: uuid.UUID | None = None
    approvals_required: int = 1
    approvers_this_revision: frozenset[uuid.UUID] = field(default_factory=frozenset)


def allowed_actions(state: S) -> list[str]:
    return sorted(a.value for (s, a) in TRANSITIONS if s == state)


def next_state(mission: MissionView, action: A) -> S:
    target = TRANSITIONS.get((mission.state, action))
    if target is None:
        allowed = allowed_actions(mission.state)
        hint = f" Allowed from {mission.state.value}: {', '.join(allowed)}." if allowed else ""
        raise Conflict(
            f"Cannot {action.value} {mission.code}: it is {mission.state.value}.{hint}",
            code="mission.illegal_transition",
            state=mission.state.value,
            allowed_actions=allowed,
        )
    return target


def check_permission(mission: MissionView, action: A, actor: Actor) -> None:
    """Who may perform an action (ownership, role, separation of duties)."""
    if actor.role == Role.CREW:
        raise Forbidden("Crew members cannot change a mission's state.", code="auth.role_required")
    if action in APPROVER_ACTIONS:
        if actor.role != Role.DIRECTOR:
            raise Forbidden("Approving or rejecting missions requires the Director role.", code="auth.role_required")
        if actor.membership_id in (mission.submitted_by, mission.owner_id):
            relation = "submitted" if actor.membership_id == mission.submitted_by else "own"
            raise Forbidden(
                f"You {relation} {mission.code}; a different Director must approve or reject it.",
                code="approval.self_approval",
            )
        return
    if actor.role != Role.DIRECTOR and actor.membership_id != mission.owner_id:
        raise Forbidden(f"Only the owner of {mission.code} or a Director can do this.", code="mission.not_owner")


def can_approve(mission: MissionView, actor: Actor) -> bool:
    try:
        check_permission(mission, A.APPROVE, actor)
    except Forbidden:
        return False
    return actor.membership_id not in mission.approvers_this_revision


def check_window_not_started(mission: MissionView, action: A, now: datetime) -> None:
    if action in (A.SUBMIT, A.APPROVE) and mission.starts_at <= now:
        raise Conflict(
            f"{mission.code}'s window has already started; edit the dates before you {action.value} it.",
            code="mission.window_started",
        )


def approval_outcome(mission: MissionView, approver: uuid.UUID) -> tuple[int, bool]:
    """Returns (approvals after this one, whether the mission becomes APPROVED)."""
    if approver in mission.approvers_this_revision:
        raise Conflict(
            f"You have already approved revision {mission.revision} of {mission.code}.",
            code="approval.duplicate",
        )
    count = len(mission.approvers_this_revision) + 1
    return count, count >= mission.approvals_required


def decide(mission: MissionView, action: A, actor: Actor, now: datetime) -> S:
    """Full check for an action; returns the target state (for APPROVE, the state if quorum is reached)."""
    target = next_state(mission, action)
    check_permission(mission, action, actor)
    check_window_not_started(mission, action, now)
    return target
