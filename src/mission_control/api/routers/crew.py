import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Response, status
from pydantic import AwareDatetime, Field
from sqlalchemy.orm import Session

from mission_control.api.deps import director_only, get_clock, get_ctx, planners
from mission_control.api.schemas.common import Schema
from mission_control.clock import Clock
from mission_control.db import models as m
from mission_control.db.repositories import TenantRepository
from mission_control.db.session import get_db
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import UnavailabilityCategory
from mission_control.services import crew as svc

router = APIRouter(tags=["crew"])


class CrewSkillOut(Schema):
    skill_id: uuid.UUID
    skill: str
    category: str | None
    claimed_level: int
    verified_level: int | None
    status: str
    cert_expires_on: date | None
    verified_at: datetime | None


class CrewOut(Schema):
    id: uuid.UUID
    member_id: uuid.UUID
    email: str
    display_name: str
    bio: str | None
    active: bool
    skills: list[CrewSkillOut]

    @classmethod
    def of(cls, crew: m.CrewProfile) -> "CrewOut":
        return cls(
            id=crew.id,
            member_id=crew.membership_id,
            email=crew.membership.user.email,
            display_name=crew.display_name,
            bio=crew.bio,
            active=crew.active,
            skills=sorted(
                (
                    CrewSkillOut(
                        skill_id=cs.skill_id,
                        skill=cs.skill.name,
                        category=cs.skill.category,
                        claimed_level=cs.claimed_level,
                        verified_level=cs.verified_level,
                        status=cs.status,
                        cert_expires_on=cs.cert_expires_on,
                        verified_at=cs.verified_at,
                    )
                    for cs in crew.skills
                ),
                key=lambda s: s.skill.lower(),
            ),
        )


class CrewIn(Schema):
    member: str = Field(description="Member id or email")
    display_name: str | None = None
    bio: str | None = None


class CrewPatch(Schema):
    display_name: str | None = Field(None, min_length=1, max_length=200)
    bio: str | None = None
    active: bool | None = None


class SkillLevelIn(Schema):
    level: int = Field(ge=1, le=5)


class VerifyIn(Schema):
    level: int | None = Field(None, ge=1, le=5, description="Adjusted level; defaults to the claimed level")
    cert_expires_on: date | None = None


class WindowIn(Schema):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    category: UnavailabilityCategory
    note: str | None = None


class WindowOut(Schema):
    id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    label: str
    category: str | None
    note: str | None


@router.get("/crew", response_model=list[CrewOut])
def list_crew(
    skill: str | None = None,
    include_inactive: bool = False,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
):
    return [CrewOut.of(c) for c in svc.list_crew(db, ctx, skill, active_only=not include_inactive)]


@router.post("/crew", response_model=CrewOut, status_code=status.HTTP_201_CREATED)
def create_crew(
    body: CrewIn,
    ctx: TenantContext = Depends(director_only),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    crew = svc.create_crew(
        db, ctx, member_ref=body.member, display_name=body.display_name, bio=body.bio, now=clock.now()
    )
    return CrewOut.of(crew)


@router.get("/crew/{ref}", response_model=CrewOut)
def get_crew(ref: str, ctx: TenantContext = Depends(get_ctx), db: Session = Depends(get_db)):
    return CrewOut.of(svc.crew_for_read(TenantRepository(db, ctx), ref))


@router.patch("/crew/{ref}", response_model=CrewOut)
def patch_crew(
    ref: str,
    body: CrewPatch,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return CrewOut.of(svc.update_crew(db, ctx, ref, body.model_dump(), now=clock.now()))


@router.put("/crew/{ref}/skills/{skill_ref}", response_model=CrewOut)
def set_skill(
    ref: str,
    skill_ref: str,
    body: SkillLevelIn,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return CrewOut.of(svc.set_own_skill(db, ctx, ref, skill_ref, body.level, now=clock.now()))


@router.delete("/crew/{ref}/skills/{skill_ref}", response_model=CrewOut)
def remove_skill(
    ref: str,
    skill_ref: str,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return CrewOut.of(svc.remove_own_skill(db, ctx, ref, skill_ref, now=clock.now()))


@router.post("/crew/{ref}/skills/{skill_ref}/verify", response_model=CrewOut)
def verify_skill(
    ref: str,
    skill_ref: str,
    body: VerifyIn,
    ctx: TenantContext = Depends(planners),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    crew = svc.verify_skill(
        db, ctx, ref, skill_ref, level=body.level, cert_expires_on=body.cert_expires_on, now=clock.now()
    )
    return CrewOut.of(crew)


@router.get("/crew/{ref}/unavailability", response_model=list[WindowOut])
def list_unavailability(ref: str, ctx: TenantContext = Depends(get_ctx), db: Session = Depends(get_db)):
    return svc.list_unavailability(db, ctx, ref)[1]


@router.post("/crew/{ref}/unavailability", response_model=WindowOut, status_code=status.HTTP_201_CREATED)
def add_unavailability(
    ref: str,
    body: WindowIn,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return svc.add_unavailability(
        db,
        ctx,
        ref,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        category=body.category,
        note=body.note,
        now=clock.now(),
    )


@router.delete("/crew/{ref}/unavailability/{window_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_unavailability(
    ref: str,
    window_id: str,
    ctx: TenantContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    svc.remove_unavailability(db, ctx, ref, window_id, now=clock.now())
    return Response(status_code=status.HTTP_204_NO_CONTENT)
