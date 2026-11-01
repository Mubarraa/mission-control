import uuid

from fastapi import APIRouter, Depends, status
from pydantic import Field
from sqlalchemy.orm import Session

from mission_control.api.deps import director_only, get_clock, get_ctx
from mission_control.api.schemas.common import Schema
from mission_control.clock import Clock
from mission_control.db.session import get_db
from mission_control.domain.context import TenantContext
from mission_control.services import skills as svc

router = APIRouter(tags=["skills"])


class SkillOut(Schema):
    id: uuid.UUID
    name: str
    category: str | None
    description: str | None
    active: bool


class SkillIn(Schema):
    name: str = Field(min_length=1, max_length=100)
    category: str | None = Field(None, max_length=100)
    description: str | None = None


class SkillPatch(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    category: str | None = None
    description: str | None = None
    active: bool | None = None


@router.get("/skills", response_model=list[SkillOut])
def list_skills(include_inactive: bool = False, ctx: TenantContext = Depends(get_ctx), db: Session = Depends(get_db)):
    return svc.list_skills(db, ctx, include_inactive)


@router.post("/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
def create_skill(
    body: SkillIn,
    ctx: TenantContext = Depends(director_only),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return svc.create_skill(
        db, ctx, name=body.name, category=body.category, description=body.description, now=clock.now()
    )


@router.patch("/skills/{skill_ref}", response_model=SkillOut)
def update_skill(
    skill_ref: str,
    body: SkillPatch,
    ctx: TenantContext = Depends(director_only),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return svc.update_skill(db, ctx, skill_ref, body.model_dump(), now=clock.now())
