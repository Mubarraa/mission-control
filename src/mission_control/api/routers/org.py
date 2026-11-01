import uuid

from fastapi import APIRouter, Depends, status
from pydantic import Field
from sqlalchemy.orm import Session

from mission_control.api.deps import director_only, get_clock, get_ctx
from mission_control.api.schemas.common import Schema
from mission_control.clock import Clock
from mission_control.db.session import get_db
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import Role
from mission_control.services import org as org_service

router = APIRouter(tags=["organisation"])


class SettingsOut(Schema):
    slug: str
    name: str
    mission_prefix: str
    approvals_required: int
    recovery_buffer_days: int
    stale_offer_days: int


class SettingsIn(Schema):
    approvals_required: int | None = Field(None, ge=1, le=5)
    recovery_buffer_days: int | None = Field(None, ge=0, le=365)
    stale_offer_days: int | None = Field(None, ge=1, le=60)


class MemberOut(Schema):
    id: uuid.UUID
    email: str
    name: str
    role: str
    active: bool

    @classmethod
    def of(cls, member) -> "MemberOut":
        return cls(
            id=member.id,
            email=member.user.email,
            name=member.user.name,
            role=member.role,
            active=member.active,
        )


class MemberIn(Schema):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    role: Role
    password: str = Field(min_length=8, description="Initial password")


class MemberPatch(Schema):
    role: Role | None = None
    active: bool | None = None


@router.get("/org/settings", response_model=SettingsOut)
def get_settings(ctx: TenantContext = Depends(get_ctx), db: Session = Depends(get_db)):
    return org_service.get_org(db, ctx)


@router.patch("/org/settings", response_model=SettingsOut)
def patch_settings(
    body: SettingsIn,
    ctx: TenantContext = Depends(director_only),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    return org_service.update_settings(db, ctx, body.model_dump(exclude_none=True), now=clock.now())


@router.get("/members", response_model=list[MemberOut])
def list_members(ctx: TenantContext = Depends(director_only), db: Session = Depends(get_db)):
    return [MemberOut.of(mb) for mb in org_service.list_members(db, ctx)]


@router.get("/members/{member_id}", response_model=MemberOut)
def get_member(member_id: str, ctx: TenantContext = Depends(director_only), db: Session = Depends(get_db)):
    return MemberOut.of(org_service.get_member(db, ctx, member_id))


@router.post("/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(
    body: MemberIn,
    ctx: TenantContext = Depends(director_only),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    member = org_service.add_member(
        db, ctx, email=body.email, name=body.name, role=body.role, password=body.password, now=clock.now()
    )
    return MemberOut.of(member)


@router.patch("/members/{member_id}", response_model=MemberOut)
def patch_member(
    member_id: str,
    body: MemberPatch,
    ctx: TenantContext = Depends(director_only),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    member = org_service.update_member(db, ctx, member_id, role=body.role, active=body.active, now=clock.now())
    return MemberOut.of(member)
