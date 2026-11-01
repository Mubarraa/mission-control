import uuid

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from mission_control.api.deps import get_clock, planners
from mission_control.api.routers.assignments import AssignmentOut
from mission_control.api.schemas.common import Schema
from mission_control.clock import Clock
from mission_control.db.session import get_db
from mission_control.domain.context import TenantContext
from mission_control.domain.matching.model import Exclusion, Suggestion
from mission_control.services import matching as svc

router = APIRouter(tags=["matching"])


class SuggestionOut(Schema):
    crew_id: uuid.UUID
    name: str
    score: float
    breakdown: dict[str, float]
    reason: str

    @classmethod
    def of(cls, s: Suggestion) -> "SuggestionOut":
        return cls(crew_id=s.crew_id, name=s.name, score=s.score, breakdown=dict(s.breakdown), reason=s.reason)


class RuleOut(Schema):
    rule: str
    detail: str
    blocking: bool


class ExclusionOut(Schema):
    crew_id: uuid.UUID
    name: str
    tier: int
    rules: list[RuleOut]

    @classmethod
    def of(cls, e: Exclusion) -> "ExclusionOut":
        return cls(
            crew_id=e.crew_id,
            name=e.name,
            tier=e.tier,
            rules=[RuleOut(rule=r.rule, detail=r.detail, blocking=r.blocking) for r in e.rules],
        )


class PositionOut(Schema):
    slot_id: uuid.UUID
    role_name: str
    index: int
    label: str
    suggestion: SuggestionOut | None
    alternatives: list[SuggestionOut]
    unfilled_reasons: list[ExclusionOut]
    excluded_total: int


class MatchSummary(Schema):
    open: int
    filled: int
    unfilled: int


class MatchOut(Schema):
    mission_code: str
    mission_name: str
    revision: int
    starts_at: str
    ends_at: str
    positions: list[PositionOut]
    summary: MatchSummary


class PairIn(Schema):
    slot_id: uuid.UUID
    crew_id: uuid.UUID


class ApplyIn(Schema):
    pairs: list[PairIn] = Field(min_length=1)


class RejectedOut(Schema):
    slot_id: str
    crew_id: str
    crew_name: str | None
    reason: str


class ApplyOut(Schema):
    applied: list[AssignmentOut]
    rejected: list[RejectedOut]


@router.get("/missions/{ref}/match", response_model=MatchOut)
def match(ref: str, all: bool = False, ctx: TenantContext = Depends(planners), db: Session = Depends(get_db)):
    run = svc.run_match(db, ctx, ref, all_reasons=all)
    r = run.result
    return MatchOut(
        mission_code=run.mission.code,
        mission_name=run.mission.name,
        revision=run.mission.revision,
        starts_at=run.mission.starts_at.isoformat(),
        ends_at=run.mission.ends_at.isoformat(),
        positions=[
            PositionOut(
                slot_id=p.position.slot_id,
                role_name=p.position.role_name,
                index=p.position.index,
                label=p.position.label,
                suggestion=SuggestionOut.of(p.suggestion) if p.suggestion else None,
                alternatives=[SuggestionOut.of(a) for a in p.alternatives],
                unfilled_reasons=[ExclusionOut.of(e) for e in p.unfilled_reasons],
                excluded_total=p.excluded_total,
            )
            for p in r.positions
        ],
        summary=MatchSummary(open=len(r.positions), filled=r.filled, unfilled=r.unfilled),
    )


@router.post("/missions/{ref}/match/apply", response_model=ApplyOut)
def apply(
    ref: str,
    body: ApplyIn,
    ctx: TenantContext = Depends(planners),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    outcome = svc.apply(db, ctx, ref, [(p.slot_id, p.crew_id) for p in body.pairs], now=clock.now())
    return ApplyOut(
        applied=[AssignmentOut.of(a) for a in outcome.applied],
        rejected=[RejectedOut(**r) for r in outcome.rejected],
    )
