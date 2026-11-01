import uuid
from datetime import UTC, datetime, timedelta

import pytest

from mission_control.domain import lifecycle as lc
from mission_control.domain.enums import MissionAction as A
from mission_control.domain.enums import MissionState as S
from mission_control.domain.enums import Role
from mission_control.domain.errors import Conflict, Forbidden

NOW = datetime(2027, 1, 15, tzinfo=UTC)
OWNER, DIRECTOR, OTHER_DIRECTOR, OTHER_LEAD = (uuid.uuid4() for _ in range(4))


def view(state=S.DRAFT, **kw):
    defaults = dict(code="ART-1", state=state, owner_id=OWNER, starts_at=NOW + timedelta(days=30), revision=1)
    return lc.MissionView(**{**defaults, **kw})


LEGAL = [
    (S.DRAFT, A.SUBMIT, S.PENDING_APPROVAL),
    (S.PENDING_APPROVAL, A.APPROVE, S.APPROVED),
    (S.PENDING_APPROVAL, A.REJECT, S.DRAFT),
    (S.PENDING_APPROVAL, A.WITHDRAW, S.DRAFT),
    (S.APPROVED, A.START, S.ACTIVE),
    (S.ACTIVE, A.COMPLETE, S.COMPLETED),
    (S.ACTIVE, A.ABORT, S.ABORTED),
    (S.DRAFT, A.CANCEL, S.CANCELLED),
    (S.PENDING_APPROVAL, A.CANCEL, S.CANCELLED),
    (S.APPROVED, A.CANCEL, S.CANCELLED),
]


@pytest.mark.parametrize(("state", "action", "target"), LEGAL)
def test_legal_transitions(state, action, target):
    assert lc.next_state(view(state), action) == target


ILLEGAL = [(s, a) for s in S for a in A if (s, a) not in {(x, y) for x, y, _ in LEGAL}]


@pytest.mark.parametrize(("state", "action"), ILLEGAL)
def test_illegal_transitions_conflict_with_allowed_actions(state, action):
    with pytest.raises(Conflict) as exc:
        lc.next_state(view(state), action)
    assert exc.value.extra["allowed_actions"] == lc.allowed_actions(state)


@pytest.mark.parametrize("state", sorted(lc.TERMINAL))
def test_terminal_states_allow_nothing(state):
    assert lc.allowed_actions(state) == []


def test_lead_cannot_approve_own_mission():
    lead = lc.Actor(OWNER, Role.LEAD)
    with pytest.raises(Forbidden):
        lc.check_permission(view(S.PENDING_APPROVAL, submitted_by=OWNER), A.APPROVE, lead)


def test_director_cannot_approve_mission_they_submitted():
    director = lc.Actor(DIRECTOR, Role.DIRECTOR)
    mission = view(S.PENDING_APPROVAL, owner_id=DIRECTOR, submitted_by=DIRECTOR)
    with pytest.raises(Forbidden) as exc:
        lc.check_permission(mission, A.APPROVE, director)
    assert exc.value.code == "approval.self_approval"


def test_director_cannot_approve_mission_they_own_even_if_someone_else_submitted():
    director = lc.Actor(DIRECTOR, Role.DIRECTOR)
    mission = view(S.PENDING_APPROVAL, owner_id=DIRECTOR, submitted_by=OTHER_DIRECTOR)
    with pytest.raises(Forbidden):
        lc.check_permission(mission, A.REJECT, director)


def test_other_director_can_approve():
    mission = view(S.PENDING_APPROVAL, submitted_by=OWNER)
    assert lc.can_approve(mission, lc.Actor(OTHER_DIRECTOR, Role.DIRECTOR))


def test_non_owner_lead_cannot_submit():
    with pytest.raises(Forbidden) as exc:
        lc.check_permission(view(), A.SUBMIT, lc.Actor(OTHER_LEAD, Role.LEAD))
    assert exc.value.code == "mission.not_owner"


def test_director_can_submit_any_mission():
    lc.check_permission(view(), A.SUBMIT, lc.Actor(DIRECTOR, Role.DIRECTOR))


def test_crew_cannot_transition():
    with pytest.raises(Forbidden):
        lc.check_permission(view(), A.CANCEL, lc.Actor(uuid.uuid4(), Role.CREW))


def test_window_started_blocks_submit_and_approve():
    started = view(starts_at=NOW - timedelta(hours=1))
    with pytest.raises(Conflict) as exc:
        lc.check_window_not_started(started, A.SUBMIT, NOW)
    assert exc.value.code == "mission.window_started"
    with pytest.raises(Conflict):
        lc.check_window_not_started(view(S.PENDING_APPROVAL, starts_at=NOW), A.APPROVE, NOW)
    lc.check_window_not_started(started, A.CANCEL, NOW)  # other actions unaffected


def test_approval_quorum():
    mission = view(S.PENDING_APPROVAL, approvals_required=2)
    assert lc.approval_outcome(mission, DIRECTOR) == (1, False)
    second = view(S.PENDING_APPROVAL, approvals_required=2, approvers_this_revision=frozenset({DIRECTOR}))
    assert lc.approval_outcome(second, OTHER_DIRECTOR) == (2, True)
    with pytest.raises(Conflict):
        lc.approval_outcome(second, DIRECTOR)
