import uuid
from dataclasses import dataclass

from mission_control.domain.enums import Role


@dataclass(frozen=True)
class TenantContext:
    """Who is acting, and in which organisation. Every service call and repository requires one."""

    org_id: uuid.UUID
    membership_id: uuid.UUID
    user_id: uuid.UUID
    role: Role
    crew_id: uuid.UUID | None = None

    @property
    def is_director(self) -> bool:
        return self.role == Role.DIRECTOR

    @property
    def is_lead(self) -> bool:
        return self.role == Role.LEAD

    @property
    def is_crew(self) -> bool:
        return self.role == Role.CREW

    @property
    def is_planner(self) -> bool:
        """Directors and Mission Leads plan missions and see the whole roster."""
        return self.role in (Role.DIRECTOR, Role.LEAD)
