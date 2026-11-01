from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mission_control.api.deps import get_clock, get_ctx
from mission_control.clock import Clock
from mission_control.db.session import get_db
from mission_control.domain.context import TenantContext
from mission_control.services import inbox

router = APIRouter(tags=["inbox"])


@router.get("/inbox")
def get_inbox(ctx: TenantContext = Depends(get_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    """Role-shaped: notifications, approvals (Directors), owned missions needing attention (Leads/Directors),
    assignment offers and skills awaiting verification (anyone with a crew profile)."""
    return inbox.build(db, ctx, now=clock.now())
