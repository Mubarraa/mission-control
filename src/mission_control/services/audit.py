"""Append-only audit trail. There is deliberately no update or delete function."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.domain.context import TenantContext


def record(
    db: Session,
    ctx: TenantContext,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    now: datetime,
    **data: Any,
) -> m.AuditEvent:
    event = m.AuditEvent(
        org_id=ctx.org_id,
        actor_id=ctx.membership_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        data=_jsonable(data),
        created_at=now,
    )
    db.add(event)
    db.flush()
    return event


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID | datetime):
        return str(value)
    return value
