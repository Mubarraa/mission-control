"""Per-recipient notifications (D19): separate from the audit log, dismissed one at a time."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.db.repositories import TenantRepository
from mission_control.domain.context import TenantContext
from mission_control.domain.errors import NotFound
from mission_control.services.audit import _jsonable


def notify(
    db: Session,
    *,
    org_id: uuid.UUID,
    recipient_id: uuid.UUID,
    kind: str,
    mission_id: uuid.UUID | None,
    now: datetime,
    **data: Any,
) -> m.Notification:
    note = m.Notification(
        org_id=org_id,
        recipient_id=recipient_id,
        kind=kind,
        mission_id=mission_id,
        data=_jsonable(data),
        created_at=now,
    )
    db.add(note)
    db.flush()
    return note


def unread_for(db: Session, ctx: TenantContext) -> list[m.Notification]:
    repo = TenantRepository(db, ctx)
    return list(
        repo.list(
            m.Notification,
            m.Notification.recipient_id == ctx.membership_id,
            m.Notification.read_at.is_(None),
            order_by=m.Notification.created_at.desc(),
        )
    )


def dismiss(db: Session, ctx: TenantContext, notification_id: str, *, now: datetime) -> m.Notification:
    note = TenantRepository(db, ctx).get(m.Notification, notification_id, "Notification")
    if note.recipient_id != ctx.membership_id:  # only the recipient may see or dismiss it
        raise NotFound("Notification not found.")
    if note.read_at is None:
        note.read_at = now
    db.commit()
    return note
