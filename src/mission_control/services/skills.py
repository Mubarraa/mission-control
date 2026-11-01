import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.db.repositories import TenantRepository
from mission_control.domain.context import TenantContext
from mission_control.domain.errors import Conflict, NotFound
from mission_control.services import audit


def resolve_skill(repo: TenantRepository, ref: str, *, active_only: bool = False) -> m.Skill:
    """Accept a skill id or (case-insensitive) name."""
    skill = None
    try:
        skill = repo.first(m.Skill, m.Skill.id == uuid.UUID(str(ref)))
    except ValueError:
        skill = repo.first(m.Skill, func.lower(m.Skill.name) == str(ref).strip().lower())
    if skill is None or (active_only and not skill.active):
        raise NotFound(f"Skill '{ref}' not found in this organisation.", code="skill.not_found")
    return skill


def list_skills(db: Session, ctx: TenantContext, include_inactive: bool = False) -> list[m.Skill]:
    repo = TenantRepository(db, ctx)
    criteria = [] if include_inactive else [m.Skill.active.is_(True)]
    return list(repo.list(m.Skill, *criteria, order_by=[m.Skill.category, m.Skill.name]))


def create_skill(
    db: Session,
    ctx: TenantContext,
    *,
    name: str,
    category: str | None,
    description: str | None,
    now: datetime,
) -> m.Skill:
    repo = TenantRepository(db, ctx)
    name = name.strip()
    if repo.first(m.Skill, func.lower(m.Skill.name) == name.lower()):
        raise Conflict(f"A skill named '{name}' already exists.", code="skill.exists")
    skill = repo.add(m.Skill(name=name, category=category, description=description))
    audit.record(db, ctx, entity_type="skill", entity_id=skill.id, action="skill.created", now=now, name=name)
    db.commit()
    return skill


def update_skill(db: Session, ctx: TenantContext, ref: str, changes: dict, *, now: datetime) -> m.Skill:
    repo = TenantRepository(db, ctx)
    skill = resolve_skill(repo, ref)
    new_name = changes.get("name")
    if new_name and new_name.strip().lower() != skill.name.lower():
        clash = repo.first(m.Skill, func.lower(m.Skill.name) == new_name.strip().lower(), m.Skill.id != skill.id)
        if clash:
            raise Conflict(f"A skill named '{new_name}' already exists.", code="skill.exists")
    for key in ("name", "category", "description", "active"):
        if changes.get(key) is not None:
            setattr(skill, key, changes[key].strip() if key == "name" else changes[key])
    audit.record(
        db,
        ctx,
        entity_type="skill",
        entity_id=skill.id,
        action="skill.updated",
        now=now,
        changes={k: v for k, v in changes.items() if v is not None},
    )
    db.commit()
    return skill
