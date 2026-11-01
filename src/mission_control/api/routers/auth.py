import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from mission_control.api.deps import get_clock, get_ctx
from mission_control.api.schemas.common import Schema
from mission_control.clock import Clock
from mission_control.db import models as m
from mission_control.db.session import get_db
from mission_control.domain.context import TenantContext
from mission_control.services import auth

router = APIRouter(tags=["auth"])


class LoginIn(Schema):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)
    org: str = Field(min_length=1, description="Organisation slug")


class OrgOut(Schema):
    id: uuid.UUID
    slug: str
    name: str


class UserOut(Schema):
    id: uuid.UUID
    email: str
    name: str


class MeOut(Schema):
    user: UserOut
    org: OrgOut
    role: str
    membership_id: uuid.UUID
    crew_id: uuid.UUID | None


class LoginOut(MeOut):
    token: str
    expires_at: datetime


@router.post("/auth/login", response_model=LoginOut)
def login(body: LoginIn, db: Session = Depends(get_db), clock: Clock = Depends(get_clock)) -> LoginOut:
    result = auth.login(db, email=body.email, password=body.password, org_slug=body.org, now=clock.now())
    ctx = auth.context_from_token(db, result.token, now=clock.now())
    return LoginOut(token=result.token, expires_at=result.expires_at, **_me(db, ctx).model_dump())


@router.get("/me", response_model=MeOut)
def me(ctx: TenantContext = Depends(get_ctx), db: Session = Depends(get_db)) -> MeOut:
    return _me(db, ctx)


def _me(db: Session, ctx: TenantContext) -> MeOut:
    membership = db.get(m.Membership, ctx.membership_id)
    org = db.get(m.Organisation, ctx.org_id)
    return MeOut(
        user=UserOut.model_validate(membership.user),
        org=OrgOut.model_validate(org),
        role=ctx.role.value,
        membership_id=ctx.membership_id,
        crew_id=ctx.crew_id,
    )
