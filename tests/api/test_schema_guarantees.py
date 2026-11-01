"""Storage-level guarantees (design.md sections 4.1 and 8)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError

from mission_control.db import models as m
from tests.factories import (
    make_assignment,
    make_crew,
    make_member,
    make_mission,
    make_org,
    make_skill,
    make_slot,
)

T0 = datetime(2027, 3, 1, tzinfo=UTC)


def _setup(db):
    org = make_org(db)
    lead = make_member(db, org, "LEAD")
    geo = make_skill(db, org, "Geology")
    crew = make_crew(db, org, skills={geo: 4})
    return org, lead, geo, crew


def test_overlapping_accepted_assignments_are_rejected(db):
    org, lead, geo, crew = _setup(db)
    m1 = make_mission(db, org, lead, T0, days=10)
    m2 = make_mission(db, org, lead, T0 + timedelta(days=5), days=10)
    make_assignment(db, m1, make_slot(db, m1, "Geologist", {geo: 3}), crew, "ACCEPTED", buffer_days=0)
    with pytest.raises(IntegrityError) as exc, db.begin_nested():
        make_assignment(db, m2, make_slot(db, m2, "Geologist", {geo: 3}), crew, "ACCEPTED", buffer_days=0)
    assert exc.value.orig.sqlstate == "23P01"  # exclusion_violation


def test_touching_half_open_periods_do_not_conflict(db):
    org, lead, geo, crew = _setup(db)
    m1 = make_mission(db, org, lead, T0, days=10)
    m2 = make_mission(db, org, lead, T0 + timedelta(days=10), days=10)  # starts exactly when m1 ends
    make_assignment(db, m1, make_slot(db, m1, "Geologist", {geo: 3}), crew, "ACCEPTED", buffer_days=0)
    make_assignment(db, m2, make_slot(db, m2, "Geologist", {geo: 3}), crew, "ACCEPTED", buffer_days=0)


def test_proposed_assignments_do_not_block_time(db):
    org, lead, geo, crew = _setup(db)
    m1 = make_mission(db, org, lead, T0, days=10)
    m2 = make_mission(db, org, lead, T0, days=10)
    make_assignment(db, m1, make_slot(db, m1, "Geologist", {geo: 3}), crew, "ACCEPTED")
    make_assignment(db, m2, make_slot(db, m2, "Geologist", {geo: 3}), crew, "PROPOSED")


def test_cross_tenant_reference_fails_foreign_key(db):
    org_a, lead_a, geo_a, _ = _setup(db)
    org_b = make_org(db)
    crew_b = make_crew(db, org_b, skills={make_skill(db, org_b, "Geology"): 4})
    mission = make_mission(db, org_a, lead_a, T0)
    slot = make_slot(db, mission, "Geologist", {geo_a: 3})
    with pytest.raises(IntegrityError) as exc, db.begin_nested():
        db.add(
            m.Assignment(
                org_id=org_a.id,
                mission_id=mission.id,
                slot_id=slot.id,
                crew_id=crew_b.id,  # belongs to org B
                offered_by=lead_a.id,
                offered_at=T0,
            )
        )
        db.flush()
    assert exc.value.orig.sqlstate == "23503"  # foreign_key_violation


def test_declined_requires_reason(db):
    org, lead, geo, crew = _setup(db)
    mission = make_mission(db, org, lead, T0)
    a = make_assignment(db, mission, make_slot(db, mission, "Geologist", {geo: 3}), crew)
    with pytest.raises(IntegrityError), db.begin_nested():
        a.state = "DECLINED"
        a.exit_reason = "  "
        db.flush()


def test_unavailability_uses_tstzrange(db):
    org, _, _, crew = _setup(db)
    db.add(
        m.Unavailability(
            org_id=org.id,
            crew_id=crew.id,
            period=Range(T0, T0 + timedelta(days=3), bounds="[)"),
            category="LEAVE",
        )
    )
    db.flush()
