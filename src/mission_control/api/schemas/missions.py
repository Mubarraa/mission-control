import uuid
from datetime import datetime

from pydantic import AwareDatetime, Field
from sqlalchemy.orm import Session

from mission_control.api.schemas.common import Schema
from mission_control.db import models as m
from mission_control.domain import lifecycle as lc
from mission_control.domain.enums import MissionState
from mission_control.services import missions as svc


class RequirementIn(Schema):
    skill: str = Field(description="Skill id or name")
    min_level: int = Field(ge=1, le=5)
    cert_required: bool = False


class SlotIn(Schema):
    role_name: str = Field(min_length=1, max_length=100)
    headcount: int = Field(1, ge=1, le=50)
    requirements: list[RequirementIn] = Field(min_length=1)


class SlotPatch(Schema):
    role_name: str | None = Field(None, min_length=1, max_length=100)
    headcount: int | None = Field(None, ge=1, le=50)
    requirements: list[RequirementIn] | None = None


class MissionIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class MissionPatch(Schema):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None


class RequirementOut(Schema):
    skill_id: uuid.UUID
    skill: str
    min_level: int
    cert_required: bool


class SlotAssignmentOut(Schema):
    id: uuid.UUID
    crew_id: uuid.UUID
    crew_name: str
    state: str
    offered_at: datetime


class SlotOut(Schema):
    id: uuid.UUID
    role_name: str
    headcount: int
    ordinal: int
    requirements: list[RequirementOut]
    assignments: list[SlotAssignmentOut]
    accepted: int
    open_positions: int


class PersonOut(Schema):
    id: uuid.UUID
    name: str


class ApprovalsOut(Schema):
    required: int | None
    received: int
    approvers: list[PersonOut]


class MissionSummaryOut(Schema):
    id: uuid.UUID
    code: str
    name: str
    state: str
    starts_at: datetime
    ends_at: datetime
    revision: int
    owner: PersonOut


class MissionOut(MissionSummaryOut):
    description: str | None
    submitted_by: PersonOut | None
    approvals: ApprovalsOut
    slots: list[SlotOut]
    allowed_actions: list[str]


def _person(db: Session, membership_id: uuid.UUID | None) -> PersonOut | None:
    if membership_id is None:
        return None
    member = db.get(m.Membership, membership_id)
    return PersonOut(id=member.id, name=member.user.name)


def summary(db: Session, mission: m.Mission) -> MissionSummaryOut:
    return MissionSummaryOut(
        id=mission.id,
        code=mission.code,
        name=mission.name,
        state=mission.state,
        starts_at=mission.starts_at,
        ends_at=mission.ends_at,
        revision=mission.revision,
        owner=_person(db, mission.owner_id),
    )


def detail(db: Session, mission: m.Mission) -> MissionOut:
    active = svc.assignments_of(db, mission)
    view = svc.view_of(db, mission)
    slots = []
    for slot in mission.slots:
        mine = [a for a in active if a.slot_id == slot.id]
        accepted = sum(1 for a in mine if a.state == "ACCEPTED")
        slots.append(
            SlotOut(
                id=slot.id,
                role_name=slot.role_name,
                headcount=slot.headcount,
                ordinal=slot.ordinal,
                requirements=[
                    RequirementOut(
                        skill_id=r.skill_id,
                        skill=r.skill.name,
                        min_level=r.min_level,
                        cert_required=r.cert_required,
                    )
                    for r in slot.requirements
                ],
                assignments=[
                    SlotAssignmentOut(
                        id=a.id,
                        crew_id=a.crew_id,
                        crew_name=a.crew.display_name,
                        state=a.state,
                        offered_at=a.offered_at,
                    )
                    for a in mine
                ],
                accepted=accepted,
                open_positions=slot.headcount - len(mine),
            )
        )
    pending = mission.state == MissionState.PENDING_APPROVAL.value
    return MissionOut(
        **summary(db, mission).model_dump(),
        description=mission.description,
        submitted_by=_person(db, mission.submitted_by),
        approvals=ApprovalsOut(
            required=mission.approvals_required_snapshot if pending else None,
            received=len(view.approvers_this_revision),
            approvers=[_person(db, a) for a in sorted(view.approvers_this_revision)],
        ),
        slots=slots,
        allowed_actions=lc.allowed_actions(MissionState(mission.state)),
    )


class AuditOut(Schema):
    at: datetime
    actor: PersonOut | None
    action: str
    entity_type: str
    data: dict


def audit_out(db: Session, event: m.AuditEvent) -> AuditOut:
    return AuditOut(
        at=event.created_at,
        actor=_person(db, event.actor_id),
        action=event.action,
        entity_type=event.entity_type,
        data=event.data,
    )
