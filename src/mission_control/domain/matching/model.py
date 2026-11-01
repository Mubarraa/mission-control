"""Input and output types for the matcher (design.md section 7). Plain data: no DB, no HTTP."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class Requirement:
    skill_id: uuid.UUID
    skill_name: str
    min_level: int
    cert_required: bool = False


@dataclass(frozen=True)
class Position:
    """One open headcount unit of a slot."""

    slot_id: uuid.UUID
    role_name: str
    slot_ordinal: int
    index: int
    headcount: int
    requirements: tuple[Requirement, ...]

    @property
    def label(self) -> str:
        return f"{self.role_name} #{self.index}" if self.headcount > 1 else self.role_name


@dataclass(frozen=True)
class SkillRecord:
    verified_level: int | None
    claimed_level: int
    verified: bool
    cert_expires_on: date | None = None


@dataclass(frozen=True)
class Commitment:
    """An accepted assignment (blocked period incl. recovery) or a pending offer (window incl. recovery)."""

    mission_code: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class UnavailableWindow:
    start: datetime
    end: datetime
    public_label: str  # "leave", "training" or "unavailable" - never medical detail


@dataclass(frozen=True)
class Candidate:
    crew_id: uuid.UUID
    name: str
    active: bool = True
    skills: Mapping[uuid.UUID, SkillRecord] = field(default_factory=dict)
    commitments: tuple[Commitment, ...] = ()
    unavailability: tuple[UnavailableWindow, ...] = ()
    pending_offers: tuple[Commitment, ...] = ()
    workload_days: float = 0.0
    experience: Mapping[uuid.UUID, int] = field(default_factory=dict)  # completed missions using each skill


@dataclass(frozen=True)
class MissionWindow:
    start: datetime
    end: datetime
    buffer_days: int = 0

    @property
    def blocked_end(self) -> datetime:
        return self.end + timedelta(days=self.buffer_days)


@dataclass(frozen=True)
class MatchInput:
    mission_code: str
    window: MissionWindow
    positions: tuple[Position, ...]
    candidates: tuple[Candidate, ...]
    # crew who may not be suggested for this mission at all: crew_id -> ALREADY_ON_MISSION|DECLINED|WITHDRAWN
    barred: Mapping[uuid.UUID, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleResult:
    rule: str
    detail: str
    blocking: bool = True  # False for advisory flags such as UNVERIFIED_WOULD_QUALIFY


@dataclass(frozen=True)
class Exclusion:
    crew_id: uuid.UUID
    name: str
    tier: int
    rules: tuple[RuleResult, ...]


@dataclass(frozen=True)
class Suggestion:
    crew_id: uuid.UUID
    name: str
    score: float
    breakdown: Mapping[str, float]
    reason: str


@dataclass(frozen=True)
class PositionResult:
    position: Position
    suggestion: Suggestion | None
    alternatives: tuple[Suggestion, ...]
    unfilled_reasons: tuple[Exclusion, ...]
    excluded_total: int


@dataclass(frozen=True)
class MatchResult:
    mission_code: str
    positions: tuple[PositionResult, ...]

    @property
    def filled(self) -> int:
        return sum(1 for p in self.positions if p.suggestion is not None)

    @property
    def unfilled(self) -> int:
        return len(self.positions) - self.filled
