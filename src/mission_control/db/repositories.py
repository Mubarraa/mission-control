"""Tenant-scoped data access.

Every query built here is constrained to the caller's organisation. A record from another
organisation is indistinguishable from one that does not exist (404), so existence never leaks.
Unscoped queries are allowed only in `services/auth.py` (login) and `seed.py`.
"""

import uuid
from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from mission_control.domain.context import TenantContext
from mission_control.domain.errors import NotFound

T = TypeVar("T")


class TenantRepository:
    def __init__(self, db: Session, ctx: TenantContext) -> None:
        self.db = db
        self.ctx = ctx

    def select(self, model: type[T], *criteria: Any) -> Select[tuple[T]]:
        return select(model).where(model.org_id == self.ctx.org_id, *criteria)  # type: ignore[attr-defined]

    def get(self, model: type[T], obj_id: uuid.UUID | str, what: str = "Resource", *, lock: bool = False) -> T:
        try:
            key = obj_id if isinstance(obj_id, uuid.UUID) else uuid.UUID(str(obj_id))
        except ValueError as exc:
            raise NotFound(f"{what} not found.") from exc
        stmt = self.select(model, model.id == key)  # type: ignore[attr-defined]
        if lock:
            stmt = stmt.with_for_update()
        obj = self.db.scalar(stmt)
        if obj is None:
            raise NotFound(f"{what} not found.")
        return obj

    def first(self, model: type[T], *criteria: Any) -> T | None:
        return self.db.scalar(self.select(model, *criteria).limit(1))

    def list(self, model: type[T], *criteria: Any, order_by: Any = None) -> Sequence[T]:
        stmt = self.select(model, *criteria)
        if order_by is not None:
            stmt = stmt.order_by(*order_by) if isinstance(order_by, list | tuple) else stmt.order_by(order_by)
        return self.db.scalars(stmt).unique().all()

    def add(self, obj: T) -> T:
        current = getattr(obj, "org_id", None)
        if current is not None and current != self.ctx.org_id:
            raise ValueError("Refusing to write a row for another organisation")
        obj.org_id = self.ctx.org_id  # type: ignore[attr-defined]
        self.db.add(obj)
        self.db.flush()
        return obj
