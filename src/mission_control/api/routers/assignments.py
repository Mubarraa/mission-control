import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import Field
from sqlalchemy.orm import Session

from mission_control.api.deps import get_clock, get_ctx, planners
from mission_control.api.schemas.common import Schema
from mission_control.clock import Clock
from mission_control.db import models as m
from mission_control.db.repositories import TenantRepository
from mission_control.db.session import get_db
from mission_control.domain.context import TenantContext
from mission_control.services import assignments as svc
from mission_control.services import notifications
from mission_control.services.crew import crew_for_read
from mission_control.services.matching import check_eligible

router = APIRouter(tags=["assignments"])


class AssignmentOut(Schema):
    id: uuid.UUID
    mission_code: str
    mission_name: str
    mission_state: str
    starts_at: datetime
    ends_at: datetime
    slot: str
    crew_id: uuid.UUID
    crew_name: str
    state: str
    source: str
    offered_at: datetime
    responded_at: datetime | None
    exit_reason: str | None

    @classmethod
    def of(cls, a: m.Assignment) -> "AssignmentOut":
        return cls(
            id=a.id,
            mission_code=a.mission.code,
            mission_name=a.mission.name,
            mission_state=a.mission.state,
            starts_at=a.mission.starts_at,
            ends_at=a.mission.ends_at,
            slot=a.slot.role_name,
            crew_id=a.crew_id,
            crew_name=a.crew.display_name,
            state=a.state,
            source=a.source,
            offered_at=a.offered_at,
            responded_at=a.responded_at,
            exit_reason=a.exit_reason,
        )


class OfferIn(Schema):
    slot: str = Field(description="Slot id or role name")
    crew: str = Field(description="Crew id, email or name")


class ReasonIn(Schema):
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(
    mission: str | None = None,
    crew: str | None = None,
    state: str | None = None,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
):
    return [AssignmentOut.of(a) for a in svc.list_assignments(db, ctx, crew_ref=crew, mission_ref=mission, state=state)]


@router.get("/crew/{ref}/assignments", response_model=list[AssignmentOut])
def crew_assignments(ref: str, ctx: TenantContext = Depends(get_ctx), db: Session = Depends(get_db)):
    crew = crew_for_read(TenantRepository(db, ctx), ref)
    return [AssignmentOut.of(a) for a in svc.list_assignments(db, ctx, crew_ref=str(crew.id))]


@router.post("/missions/{ref}/assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
def offer(
    ref: str,
    body: OfferIn,
    ctx: TenantContext = Depends(planners),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return AssignmentOut.of(svc.offer(db, ctx, ref, body.slot, body.crew, now=clock.now(), eligibility=check_eligible))


@router.post("/assignments/{assignment_id}/accept", response_model=AssignmentOut)
def accept(
    assignment_id: str,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return AssignmentOut.of(svc.accept(db, ctx, assignment_id, now=clock.now()))


@router.post("/assignments/{assignment_id}/decline", response_model=AssignmentOut)
def decline(
    assignment_id: str,
    body: ReasonIn,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return AssignmentOut.of(svc.decline(db, ctx, assignment_id, body.reason, now=clock.now()))


@router.post("/assignments/{assignment_id}/withdraw", response_model=AssignmentOut)
def withdraw(
    assignment_id: str,
    body: ReasonIn,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return AssignmentOut.of(svc.withdraw(db, ctx, assignment_id, body.reason, now=clock.now()))


@router.post("/assignments/{assignment_id}/release", response_model=AssignmentOut)
def release(
    assignment_id: str,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return AssignmentOut.of(svc.release(db, ctx, assignment_id, now=clock.now()))


class NotificationOut(Schema):
    id: uuid.UUID
    kind: str
    mission_id: uuid.UUID | None
    data: dict
    created_at: datetime
    read_at: datetime | None


@router.post("/notifications/{notification_id}/dismiss", response_model=NotificationOut)
def dismiss(
    notification_id: str,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return notifications.dismiss(db, ctx, notification_id, now=clock.now())
