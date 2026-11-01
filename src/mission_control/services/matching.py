"""Matching service: bulk-loads the data the pure matcher needs, runs it, and applies suggestions.

Loading is a fixed number of queries regardless of roster size (no N+1).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.db.repositories import TenantRepository
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import AssignmentSource, AssignmentState, MissionState
from mission_control.domain.errors import Conflict, DomainError
from mission_control.domain.matching import eligibility, engine
from mission_control.domain.matching.model import (
    Candidate,
    Commitment,
    MatchInput,
    MatchResult,
    MissionWindow,
    Position,
    Requirement,
    SkillRecord,
    UnavailableWindow,
)
from mission_control.services.assignments import create_offer
from mission_control.services.crew import PUBLIC_CATEGORIES
from mission_control.services.missions import (
    ACTIVE_ASSIGNMENT,
    _require_editor,
    assignments_of,
    resolve_mission,
)

WORKLOAD_LOOKBACK = timedelta(days=90)


def _window(db: Session, mission: m.Mission) -> MissionWindow:
    buffer_days = db.scalar(select(m.Organisation.recovery_buffer_days).where(m.Organisation.id == mission.org_id))
    return MissionWindow(mission.starts_at, mission.ends_at, buffer_days)


def _requirements(slot: m.MissionSlot) -> tuple[Requirement, ...]:
    return tuple(Requirement(r.skill_id, r.skill.name, r.min_level, r.cert_required) for r in slot.requirements)


def open_positions(db: Session, mission: m.Mission) -> list[Position]:
    taken = defaultdict(int)
    for a in assignments_of(db, mission):
        taken[a.slot_id] += 1
    positions = []
    for slot in mission.slots:
        reqs = _requirements(slot)
        for index in range(taken[slot.id] + 1, slot.headcount + 1):
            positions.append(Position(slot.id, slot.role_name, slot.ordinal, index, slot.headcount, reqs))
    return positions


def load_candidates(
    db: Session,
    ctx: TenantContext,
    mission: m.Mission,
    window: MissionWindow,
    crew_ids: list[uuid.UUID] | None = None,
) -> list[Candidate]:
    repo = TenantRepository(db, ctx)
    stmt = repo.select(m.CrewProfile)
    stmt = (
        stmt.where(m.CrewProfile.id.in_(crew_ids))
        if crew_ids is not None
        else stmt.where(m.CrewProfile.active.is_(True))
    )
    profiles = db.scalars(stmt).unique().all()
    ids = [p.id for p in profiles]
    if not ids:
        return []

    commitments, pending = defaultdict(list), defaultdict(list)
    workload = defaultdict(float)
    lookback_start = window.start - WORKLOAD_LOOKBACK
    other = db.execute(
        select(
            m.Assignment.crew_id,
            m.Assignment.state,
            m.Assignment.blocked_period,
            m.Mission.code,
            m.Mission.starts_at,
            m.Mission.ends_at,
        )
        .join(m.Mission, m.Mission.id == m.Assignment.mission_id)
        .where(
            m.Assignment.org_id == ctx.org_id,
            m.Assignment.crew_id.in_(ids),
            m.Assignment.mission_id != mission.id,
            m.Assignment.state.in_(ACTIVE_ASSIGNMENT),
        )
    ).all()
    for crew_id, state, period, code, starts, ends in other:
        if state == AssignmentState.ACCEPTED.value:
            commitments[crew_id].append(Commitment(code, period.lower, period.upper))
            overlap = (min(ends, window.start) - max(starts, lookback_start)).total_seconds() / 86400
            workload[crew_id] += max(0.0, overlap)
        else:
            pending[crew_id].append(Commitment(code, starts, ends + timedelta(days=window.buffer_days)))

    unavailable = defaultdict(list)
    for w in db.scalars(repo.select(m.Unavailability, m.Unavailability.crew_id.in_(ids))).all():
        label = w.category.lower() if w.category in PUBLIC_CATEGORIES else "unavailable"
        unavailable[w.crew_id].append(UnavailableWindow(w.period.lower, w.period.upper, label))

    experience = defaultdict(lambda: defaultdict(int))
    for crew_id, skill_id in db.execute(
        select(m.Assignment.crew_id, m.SlotRequirement.skill_id)
        .join(m.Mission, m.Mission.id == m.Assignment.mission_id)
        .join(m.SlotRequirement, m.SlotRequirement.slot_id == m.Assignment.slot_id)
        .where(
            m.Assignment.org_id == ctx.org_id,
            m.Assignment.crew_id.in_(ids),
            m.Assignment.state == AssignmentState.ACCEPTED.value,
            m.Mission.state == MissionState.COMPLETED.value,
        )
    ).all():
        experience[crew_id][skill_id] += 1

    return [
        Candidate(
            crew_id=p.id,
            name=p.display_name,
            active=p.active,
            skills={
                cs.skill_id: SkillRecord(
                    cs.verified_level, cs.claimed_level, cs.status == "VERIFIED", cs.cert_expires_on
                )
                for cs in p.skills
            },
            commitments=tuple(commitments[p.id]),
            unavailability=tuple(unavailable[p.id]),
            pending_offers=tuple(pending[p.id]),
            workload_days=round(workload[p.id], 1),
            experience=dict(experience[p.id]),
        )
        for p in profiles
    ]


def _barred(db: Session, mission: m.Mission) -> dict[uuid.UUID, str]:
    barred = {}
    for a in assignments_of(db, mission, states=None):
        if a.state in ACTIVE_ASSIGNMENT:
            barred[a.crew_id] = "ALREADY_ON_MISSION"
        elif a.state in (AssignmentState.DECLINED.value, AssignmentState.WITHDRAWN.value):
            barred.setdefault(a.crew_id, a.state)
    return barred


@dataclass
class MatchRun:
    mission: m.Mission
    result: MatchResult


def run_match(db: Session, ctx: TenantContext, ref: str, *, all_reasons: bool = False) -> MatchRun:
    repo = TenantRepository(db, ctx)
    mission = resolve_mission(repo, ref)
    _require_editor(ctx, mission)
    if mission.state != MissionState.DRAFT.value:
        raise Conflict(
            f"{mission.code} is {mission.state}; the matcher only runs on DRAFT missions.",
            code="match.mission_not_draft",
        )
    window = _window(db, mission)
    data = MatchInput(
        mission_code=mission.code,
        window=window,
        positions=tuple(open_positions(db, mission)),
        candidates=tuple(load_candidates(db, ctx, mission, window)),
        barred=_barred(db, mission),
    )
    return MatchRun(mission, engine.run(data, all_reasons=all_reasons))


def check_eligible(
    db: Session, ctx: TenantContext, mission: m.Mission, slot: m.MissionSlot, crew: m.CrewProfile
) -> None:
    """Hard rules for one (crew, slot) pair; used by manual offers and when applying suggestions."""
    window = _window(db, mission)
    barred = _barred(db, mission).get(crew.id)
    if barred:
        raise Conflict(f"{crew.display_name} {eligibility.BARRED_DETAIL[barred]}.", code="assignment.not_eligible")
    candidate = load_candidates(db, ctx, mission, window, crew_ids=[crew.id])[0]
    position = Position(slot.id, slot.role_name, slot.ordinal, 1, slot.headcount, _requirements(slot))
    failures = eligibility.blocking(eligibility.evaluate(candidate, position, window))
    if failures:
        raise Conflict(
            f"{crew.display_name} is not eligible for {slot.role_name}: " + "; ".join(f.detail for f in failures),
            code="assignment.not_eligible",
            rules=[{"rule": f.rule, "detail": f.detail} for f in failures],
        )


@dataclass
class ApplyOutcome:
    applied: list[m.Assignment]
    rejected: list[dict]


def apply(db: Session, ctx: TenantContext, ref: str, pairs: list[tuple[str, str]], *, now: datetime) -> ApplyOutcome:
    """Turn chosen suggestions into PROPOSED offers. Each pair is re-validated and succeeds or fails alone."""
    repo = TenantRepository(db, ctx)
    mission = resolve_mission(repo, ref, lock=True)
    _require_editor(ctx, mission)
    if mission.state != MissionState.DRAFT.value:
        raise Conflict(
            f"{mission.code} is {mission.state}; suggestions can only be applied to DRAFT missions.",
            code="match.mission_not_draft",
        )
    applied, rejected = [], []
    slots = {str(s.id): s for s in mission.slots}
    for slot_id, crew_id in pairs:
        slot = slots.get(str(slot_id))
        crew = repo.first(m.CrewProfile, m.CrewProfile.id == _uuid(crew_id))
        if slot is None or crew is None:
            rejected.append(
                {
                    "slot_id": str(slot_id),
                    "crew_id": str(crew_id),
                    "crew_name": None,
                    "reason": "slot or crew member not found",
                }
            )
            continue
        try:
            check_eligible(db, ctx, mission, slot, crew)
            applied.append(create_offer(db, ctx, mission, slot, crew, source=AssignmentSource.MATCHER, now=now))
        except DomainError as exc:
            rejected.append(
                {
                    "slot_id": str(slot.id),
                    "crew_id": str(crew.id),
                    "crew_name": crew.display_name,
                    "reason": exc.detail,
                }
            )
    db.commit()
    return ApplyOutcome(applied, rejected)


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
