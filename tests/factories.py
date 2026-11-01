"""Small builders so that each test (especially cross-tenant ones) stays a few lines long."""

import itertools
from datetime import date, datetime, timedelta

from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.security import hash_password

_seq = itertools.count(1)
PASSWORD = "pw-test-123"
_HASH = hash_password(PASSWORD)


def make_org(db: Session, slug: str | None = None, prefix: str = "TST", **settings) -> m.Organisation:
    n = next(_seq)
    org = m.Organisation(slug=slug or f"org-{n}", name=f"Org {n}", mission_prefix=prefix, **settings)
    db.add(org)
    db.flush()
    return org


def make_member(
    db: Session, org: m.Organisation, role: str = "CREW", email: str | None = None, name: str | None = None
) -> m.Membership:
    n = next(_seq)
    email = (email or f"user{n}@example.test").lower()
    user = db.query(m.User).filter_by(email=email).one_or_none()
    if user is None:
        user = m.User(email=email, name=name or f"User {n}", password_hash=_HASH)
        db.add(user)
        db.flush()
    member = m.Membership(org_id=org.id, user_id=user.id, role=role)
    db.add(member)
    db.flush()
    return member


def make_skill(db: Session, org: m.Organisation, name: str, category: str | None = None) -> m.Skill:
    skill = m.Skill(org_id=org.id, name=name, category=category)
    db.add(skill)
    db.flush()
    return skill


def make_crew(
    db: Session,
    org: m.Organisation,
    member: m.Membership | None = None,
    name: str | None = None,
    skills: dict[m.Skill, int] | None = None,
    certs: dict[m.Skill, date] | None = None,
) -> m.CrewProfile:
    member = member or make_member(db, org, "CREW", name=name)
    crew = m.CrewProfile(org_id=org.id, membership_id=member.id, display_name=name or member.user.name)
    db.add(crew)
    db.flush()
    for skill, level in (skills or {}).items():
        db.add(
            m.CrewSkill(
                org_id=org.id,
                crew_id=crew.id,
                skill_id=skill.id,
                claimed_level=level,
                verified_level=level,
                status="VERIFIED",
                cert_expires_on=(certs or {}).get(skill),
            )
        )
    db.flush()
    db.refresh(crew)
    return crew


def make_mission(
    db: Session,
    org: m.Organisation,
    owner: m.Membership,
    starts: datetime,
    days: int = 10,
    state: str = "DRAFT",
    name: str = "Test Mission",
) -> m.Mission:
    org.mission_seq += 1
    mission = m.Mission(
        org_id=org.id,
        code=f"{org.mission_prefix}-{org.mission_seq}",
        name=name,
        starts_at=starts,
        ends_at=starts + timedelta(days=days),
        state=state,
        owner_id=owner.id,
    )
    db.add(mission)
    db.flush()
    return mission


def make_slot(
    db: Session,
    mission: m.Mission,
    role: str,
    reqs: dict[m.Skill, int],
    headcount: int = 1,
    cert: set[m.Skill] | None = None,
) -> m.MissionSlot:
    slot = m.MissionSlot(
        org_id=mission.org_id,
        mission_id=mission.id,
        role_name=role,
        headcount=headcount,
        ordinal=len(mission.slots) + 1,
    )
    db.add(slot)
    db.flush()
    for skill, level in reqs.items():
        db.add(
            m.SlotRequirement(
                org_id=mission.org_id,
                slot_id=slot.id,
                skill_id=skill.id,
                min_level=level,
                cert_required=skill in (cert or set()),
            )
        )
    db.flush()
    db.refresh(mission)
    return slot


def make_assignment(
    db: Session,
    mission: m.Mission,
    slot: m.MissionSlot,
    crew: m.CrewProfile,
    state: str = "PROPOSED",
    buffer_days: int = 14,
    offered_at: datetime | None = None,
) -> m.Assignment:
    blocked = None
    if state == "ACCEPTED":
        blocked = Range(mission.starts_at, mission.ends_at + timedelta(days=buffer_days), bounds="[)")
    a = m.Assignment(
        org_id=mission.org_id,
        mission_id=mission.id,
        slot_id=slot.id,
        crew_id=crew.id,
        state=state,
        blocked_period=blocked,
        offered_by=mission.owner_id,
        offered_at=offered_at or mission.starts_at - timedelta(days=30),
    )
    db.add(a)
    db.flush()
    return a
