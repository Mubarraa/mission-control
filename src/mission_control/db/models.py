"""ORM models (design.md section 4).

Tenant integrity is enforced in the schema itself: every tenant-owned table carries `org_id`, every
parent exposes `UNIQUE(org_id, id)`, and children reference parents through composite foreign keys
`(org_id, parent_id)`. The database therefore refuses a row that links records from two organisations.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, ExcludeConstraint, Range
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _tenant_fk(cols: list[str], parent: str, ondelete: str | None = None) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(cols, [f"{parent}.org_id", f"{parent}.id"], ondelete=ondelete)


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = _uuid()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    mission_prefix: Mapped[str] = mapped_column(String(8))
    mission_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    approvals_required: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    recovery_buffer_days: Mapped[int] = mapped_column(Integer, default=14, server_default="14")
    stale_offer_days: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("approvals_required >= 1", name="approvals_min"),
        CheckConstraint("recovery_buffer_days >= 0", name="buffer_min"),
        CheckConstraint("stale_offer_days >= 1", name="stale_min"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid()
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-cased
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    """The principal: a user acting within one organisation, with one role."""

    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created()

    user: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("org_id", "user_id"),
        UniqueConstraint("org_id", "id"),
        CheckConstraint("role in ('DIRECTOR','LEAD','CREW')", name="role_valid"),
    )


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        Index("uq_skills_org_lower_name", "org_id", func.lower(name), unique=True),
    )


class CrewProfile(Base):
    __tablename__ = "crew_profiles"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    membership_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    bio: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created()

    membership: Mapped[Membership] = relationship(
        lazy="joined", foreign_keys=[membership_id], primaryjoin="CrewProfile.membership_id == Membership.id"
    )
    skills: Mapped[list["CrewSkill"]] = relationship(back_populates="crew", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        _tenant_fk(["org_id", "membership_id"], "memberships"),
    )


class CrewSkill(Base):
    __tablename__ = "crew_skills"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column()
    crew_id: Mapped[uuid.UUID] = mapped_column()
    skill_id: Mapped[uuid.UUID] = mapped_column()
    claimed_level: Mapped[int] = mapped_column(Integer)
    verified_level: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="UNVERIFIED")
    cert_expires_on: Mapped[date | None] = mapped_column(Date)
    verified_by: Mapped[uuid.UUID | None] = mapped_column()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    crew: Mapped[CrewProfile] = relationship(
        back_populates="skills", foreign_keys=[crew_id], primaryjoin="CrewSkill.crew_id == CrewProfile.id"
    )
    skill: Mapped[Skill] = relationship(
        lazy="joined", foreign_keys=[skill_id], primaryjoin="CrewSkill.skill_id == Skill.id"
    )

    __table_args__ = (
        UniqueConstraint("crew_id", "skill_id"),
        _tenant_fk(["org_id", "crew_id"], "crew_profiles", ondelete="CASCADE"),
        _tenant_fk(["org_id", "skill_id"], "skills"),
        _tenant_fk(["org_id", "verified_by"], "memberships"),
        CheckConstraint("claimed_level between 1 and 5", name="claimed_range"),
        CheckConstraint("verified_level is null or verified_level between 1 and 5", name="verified_range"),
        CheckConstraint("status in ('UNVERIFIED','VERIFIED')", name="status_valid"),
    )


class Unavailability(Base):
    __tablename__ = "unavailability"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column()
    crew_id: Mapped[uuid.UUID] = mapped_column()
    period: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    category: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        _tenant_fk(["org_id", "crew_id"], "crew_profiles", ondelete="CASCADE"),
        CheckConstraint("category in ('LEAVE','TRAINING','MEDICAL','OTHER')", name="category_valid"),
        Index("ix_unavailability_crew_period", "crew_id", "period", postgresql_using="gist"),
    )


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(24), default="DRAFT")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[uuid.UUID] = mapped_column()
    submitted_by: Mapped[uuid.UUID | None] = mapped_column()
    submitted_revision: Mapped[int | None] = mapped_column(Integer)
    approvals_required_snapshot: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    slots: Mapped[list["MissionSlot"]] = relationship(
        back_populates="mission", lazy="selectin", order_by="MissionSlot.ordinal"
    )

    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "code"),
        _tenant_fk(["org_id", "owner_id"], "memberships"),
        _tenant_fk(["org_id", "submitted_by"], "memberships"),
        CheckConstraint("ends_at > starts_at", name="window_valid"),
    )


class MissionSlot(Base):
    __tablename__ = "mission_slots"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column()
    mission_id: Mapped[uuid.UUID] = mapped_column()
    role_name: Mapped[str] = mapped_column(String(100))
    headcount: Mapped[int] = mapped_column(Integer, default=1)
    ordinal: Mapped[int] = mapped_column(Integer)

    mission: Mapped[Mission] = relationship(
        back_populates="slots", foreign_keys=[mission_id], primaryjoin="MissionSlot.mission_id == Mission.id"
    )
    requirements: Mapped[list["SlotRequirement"]] = relationship(
        back_populates="slot", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        _tenant_fk(["org_id", "mission_id"], "missions"),
        CheckConstraint("headcount >= 1", name="headcount_min"),
    )


class SlotRequirement(Base):
    __tablename__ = "slot_requirements"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column()
    slot_id: Mapped[uuid.UUID] = mapped_column()
    skill_id: Mapped[uuid.UUID] = mapped_column()
    min_level: Mapped[int] = mapped_column(Integer)
    cert_required: Mapped[bool] = mapped_column(Boolean, default=False)

    slot: Mapped[MissionSlot] = relationship(
        back_populates="requirements",
        foreign_keys=[slot_id],
        primaryjoin="SlotRequirement.slot_id == MissionSlot.id",
    )
    skill: Mapped[Skill] = relationship(
        lazy="joined", foreign_keys=[skill_id], primaryjoin="SlotRequirement.skill_id == Skill.id"
    )

    __table_args__ = (
        UniqueConstraint("slot_id", "skill_id"),
        _tenant_fk(["org_id", "slot_id"], "mission_slots", ondelete="CASCADE"),
        _tenant_fk(["org_id", "skill_id"], "skills"),
        CheckConstraint("min_level between 1 and 5", name="min_level_range"),
    )


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column()
    mission_id: Mapped[uuid.UUID] = mapped_column()
    slot_id: Mapped[uuid.UUID] = mapped_column()
    crew_id: Mapped[uuid.UUID] = mapped_column()
    state: Mapped[str] = mapped_column(String(16), default="PROPOSED")
    source: Mapped[str] = mapped_column(String(16), default="MANUAL")
    blocked_period: Mapped[Range[datetime] | None] = mapped_column(TSTZRANGE)
    offered_by: Mapped[uuid.UUID] = mapped_column()
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_reason: Mapped[str | None] = mapped_column(Text)

    crew: Mapped[CrewProfile] = relationship(
        lazy="joined", foreign_keys=[crew_id], primaryjoin="Assignment.crew_id == CrewProfile.id"
    )
    slot: Mapped[MissionSlot] = relationship(
        lazy="joined", foreign_keys=[slot_id], primaryjoin="Assignment.slot_id == MissionSlot.id"
    )
    mission: Mapped[Mission] = relationship(
        lazy="joined", foreign_keys=[mission_id], primaryjoin="Assignment.mission_id == Mission.id"
    )

    __table_args__ = (
        _tenant_fk(["org_id", "mission_id"], "missions"),
        _tenant_fk(["org_id", "slot_id"], "mission_slots"),
        _tenant_fk(["org_id", "crew_id"], "crew_profiles"),
        _tenant_fk(["org_id", "offered_by"], "memberships"),
        CheckConstraint("state in ('PROPOSED','ACCEPTED','DECLINED','WITHDRAWN','RELEASED')", name="state_valid"),
        CheckConstraint("state not in ('DECLINED','WITHDRAWN') or length(trim(exit_reason)) > 0", name="exit_reason"),
        CheckConstraint("state <> 'ACCEPTED' or blocked_period is not null", name="accepted_blocks"),
        Index(
            "uq_assignments_active_crew_per_mission",
            "mission_id",
            "crew_id",
            unique=True,
            postgresql_where=text("state in ('PROPOSED','ACCEPTED')"),
        ),
        # DO NOT REMOVE. Makes double-booking impossible at the storage layer (design.md section 8).
        # Requires the btree_gist extension, created by hand in migration 0001.
        ExcludeConstraint(
            ("crew_id", "="),
            ("blocked_period", "&&"),
            name="no_double_booking",
            using="gist",
            where=text("state = 'ACCEPTED'"),
        ),
    )


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column()
    mission_id: Mapped[uuid.UUID] = mapped_column()
    revision: Mapped[int] = mapped_column(Integer)
    approver_id: Mapped[uuid.UUID] = mapped_column()
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        UniqueConstraint("mission_id", "revision", "approver_id"),
        _tenant_fk(["org_id", "mission_id"], "missions"),
        _tenant_fk(["org_id", "approver_id"], "memberships"),
        CheckConstraint("decision in ('APPROVE','REJECT')", name="decision_valid"),
    )


class AuditEvent(Base):
    """Append-only. There is intentionally no update or delete path anywhere in the code."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid()
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)  # insertion order
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID] = mapped_column()
    action: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        _tenant_fk(["org_id", "actor_id"], "memberships"),
        Index("ix_audit_entity", "org_id", "entity_type", "entity_id", "created_at"),
    )


class Notification(Base):
    """Per-recipient messages. Separate from the audit log (D19)."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = _uuid()
    org_id: Mapped[uuid.UUID] = mapped_column()
    recipient_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(64))
    mission_id: Mapped[uuid.UUID | None] = mapped_column()
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        _tenant_fk(["org_id", "recipient_id"], "memberships"),
        _tenant_fk(["org_id", "mission_id"], "missions"),
        Index("ix_notifications_unread", "recipient_id", postgresql_where=text("read_at is null")),
    )
