from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from mission_control.clock import Clock
from mission_control.db.session import get_db
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import Role
from mission_control.domain.errors import Forbidden, Unauthenticated
from mission_control.services.auth import context_from_token

_bearer = HTTPBearer(auto_error=False)

ROLE_LABEL = {Role.DIRECTOR: "Director", Role.LEAD: "Mission Lead", Role.CREW: "Crew Member"}


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_ctx(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> TenantContext:
    if creds is None:
        raise Unauthenticated("Authentication required. Log in with `mc login`.")
    return context_from_token(db, creds.credentials, now=clock.now())


def require_role(*roles: Role) -> Callable[..., TenantContext]:
    def _dep(ctx: TenantContext = Depends(get_ctx)) -> TenantContext:
        if ctx.role not in roles:
            needed = " or ".join(ROLE_LABEL[r] for r in roles)
            raise Forbidden(f"This action requires the {needed} role.", code="auth.role_required")
        return ctx

    return _dep


director_only = require_role(Role.DIRECTOR)
planners = require_role(Role.DIRECTOR, Role.LEAD)
