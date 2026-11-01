from fastapi import APIRouter, Depends, status
from pydantic import Field
from sqlalchemy.orm import Session

from mission_control.api.deps import get_clock, get_ctx, planners
from mission_control.api.schemas import missions as s
from mission_control.api.schemas.common import Schema
from mission_control.clock import Clock
from mission_control.db.repositories import TenantRepository
from mission_control.db.session import get_db
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import MissionAction
from mission_control.services import missions as svc

router = APIRouter(tags=["missions"])


@router.get("/missions", response_model=list[s.MissionSummaryOut])
def list_missions(state: str | None = None, ctx: TenantContext = Depends(get_ctx), db: Session = Depends(get_db)):
    return [s.summary(db, mi) for mi in svc.list_missions(db, ctx, state)]


@router.post("/missions", response_model=s.MissionOut, status_code=status.HTTP_201_CREATED)
def create_mission(
    body: s.MissionIn,
    ctx: TenantContext = Depends(planners),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    mission = svc.create_mission(
        db,
        ctx,
        name=body.name,
        description=body.description,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        now=clock.now(),
    )
    return s.detail(db, mission)


@router.get("/missions/{ref}", response_model=s.MissionOut)
def get_mission(ref: str, ctx: TenantContext = Depends(get_ctx), db: Session = Depends(get_db)):
    return s.detail(db, svc.resolve_mission(TenantRepository(db, ctx), ref))


@router.patch("/missions/{ref}", response_model=s.MissionOut)
def patch_mission(
    ref: str,
    body: s.MissionPatch,
    ctx: TenantContext = Depends(planners),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return s.detail(db, svc.update_mission(db, ctx, ref, body.model_dump(exclude_none=True), now=clock.now()))


@router.get("/missions/{ref}/history", response_model=list[s.AuditOut])
def mission_history(ref: str, ctx: TenantContext = Depends(planners), db: Session = Depends(get_db)):
    return [s.audit_out(db, e) for e in svc.history(db, ctx, ref)]


@router.post("/missions/{ref}/slots", response_model=s.MissionOut, status_code=status.HTTP_201_CREATED)
def add_slot(
    ref: str,
    body: s.SlotIn,
    ctx: TenantContext = Depends(planners),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    mission = svc.add_slot(
        db,
        ctx,
        ref,
        role_name=body.role_name,
        headcount=body.headcount,
        requirements=[r.model_dump() for r in body.requirements],
        now=clock.now(),
    )
    return s.detail(db, mission)


@router.patch("/missions/{ref}/slots/{slot}", response_model=s.MissionOut)
def patch_slot(
    ref: str,
    slot: str,
    body: s.SlotPatch,
    ctx: TenantContext = Depends(planners),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    changes = body.model_dump(exclude_none=True)
    if body.requirements is not None:
        changes["requirements"] = [r.model_dump() for r in body.requirements]
    return s.detail(db, svc.update_slot(db, ctx, ref, slot, changes, now=clock.now()))


@router.delete("/missions/{ref}/slots/{slot}", response_model=s.MissionOut)
def delete_slot(
    ref: str,
    slot: str,
    ctx: TenantContext = Depends(planners),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return s.detail(db, svc.remove_slot(db, ctx, ref, slot, now=clock.now()))


class TransitionIn(Schema):
    revision: int | None = Field(None, description="Required for approve/reject: the revision you reviewed")
    reason: str | None = Field(None, max_length=2000, description="Required for reject")


@router.post("/missions/{ref}/{action}", response_model=s.MissionOut)
def transition(
    ref: str,
    action: MissionAction,
    body: TransitionIn | None = None,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    body = body or TransitionIn()
    mission = svc.transition(db, ctx, ref, action, revision=body.revision, reason=body.reason, now=clock.now())
    return s.detail(db, mission)
