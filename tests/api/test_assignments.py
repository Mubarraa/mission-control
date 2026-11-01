import threading
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mission_control.db import models as m
from mission_control.domain.context import TenantContext
from mission_control.domain.enums import Role
from mission_control.domain.errors import Conflict
from mission_control.services import assignments as svc
from tests.conftest import NOW
from tests.factories import (
    make_assignment,
    make_crew,
    make_member,
    make_mission,
    make_org,
    make_skill,
    make_slot,
)

START = NOW + timedelta(days=45)


def _world(db, **org_settings):
    org = make_org(db, prefix="ART", **org_settings)
    lead = make_member(db, org, "LEAD")
    geo = make_skill(db, org, "Geology")
    bob = make_crew(db, org, name="Bob", skills={geo: 4})
    mission = make_mission(db, org, lead, START, days=10)
    slot = make_slot(db, mission, "Geologist", {geo: 3})
    return org, lead, geo, bob, mission, slot


def test_offer_then_accept_blocks_time_with_buffer(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db, recovery_buffer_days=14)
    resp = client.post(
        f"/v1/missions/{mission.code}/assignments",
        json={"slot": "Geologist", "crew": "Bob"},
        headers=auth_headers(lead, org),
    )
    assert resp.status_code == 201 and resp.json()["state"] == "PROPOSED"
    aid = resp.json()["id"]
    accepted = client.post(f"/v1/assignments/{aid}/accept", headers=auth_headers(bob.membership, org))
    assert accepted.status_code == 200 and accepted.json()["state"] == "ACCEPTED"
    a = db.get(m.Assignment, accepted.json()["id"])
    assert a.blocked_period.upper == mission.ends_at + timedelta(days=14)


def test_duplicate_crew_and_full_slot(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    h = auth_headers(lead, org)
    client.post(f"/v1/missions/{mission.code}/assignments", json={"slot": "Geologist", "crew": "Bob"}, headers=h)
    make_slot(db, mission, "Backup", {geo: 1})
    dup = client.post(f"/v1/missions/{mission.code}/assignments", json={"slot": "Backup", "crew": "Bob"}, headers=h)
    assert dup.status_code == 409 and dup.json()["code"] == "assignment.duplicate_crew"
    make_crew(db, org, name="Carol", skills={geo: 4})
    full = client.post(
        f"/v1/missions/{mission.code}/assignments", json={"slot": "Geologist", "crew": "Carol"}, headers=h
    )
    assert full.status_code == 409 and full.json()["code"] == "assignment.slot_full"


def test_crew_cannot_accept_someone_elses_offer(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    a = make_assignment(db, mission, slot, bob)
    alice = make_crew(db, org, name="Alice")
    assert client.post(f"/v1/assignments/{a.id}/accept", headers=auth_headers(alice.membership, org)).status_code == 404


def test_overlapping_acceptance_names_the_conflicting_mission(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db, recovery_buffer_days=14)
    make_assignment(db, mission, slot, bob, "ACCEPTED", buffer_days=14)
    later = make_mission(db, org, lead, mission.ends_at + timedelta(days=5))  # inside the recovery buffer
    offer = make_assignment(db, later, make_slot(db, later, "Geologist", {geo: 3}), bob)
    resp = client.post(f"/v1/assignments/{offer.id}/accept", headers=auth_headers(bob.membership, org))
    assert resp.status_code == 409
    assert resp.json()["code"] == "assignment.double_booked" and mission.code in resp.json()["detail"]


def test_unavailability_blocks_acceptance(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    a = make_assignment(db, mission, slot, bob)
    hb = auth_headers(bob.membership, org)
    client.post(
        "/v1/crew/me/unavailability",
        headers=hb,
        json={
            "starts_at": (START + timedelta(days=2)).isoformat(),
            "ends_at": (START + timedelta(days=4)).isoformat(),
            "category": "MEDICAL",
        },
    )
    resp = client.post(f"/v1/assignments/{a.id}/accept", headers=hb)
    assert resp.status_code == 409 and resp.json()["code"] == "assignment.unavailable"


def test_new_unavailability_over_accepted_assignment_rejected(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    make_assignment(db, mission, slot, bob, "ACCEPTED")
    resp = client.post(
        "/v1/crew/me/unavailability",
        headers=auth_headers(bob.membership, org),
        json={
            "starts_at": (START + timedelta(days=1)).isoformat(),
            "ends_at": (START + timedelta(days=2)).isoformat(),
            "category": "LEAVE",
        },
    )
    assert resp.status_code == 409 and resp.json()["code"] == "unavailability.overlaps_assignment"


def test_decline_requires_reason_and_reopens_position(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    a = make_assignment(db, mission, slot, bob)
    hb = auth_headers(bob.membership, org)
    assert client.post(f"/v1/assignments/{a.id}/decline", json={"reason": ""}, headers=hb).status_code == 422
    resp = client.post(f"/v1/assignments/{a.id}/decline", json={"reason": "family commitment"}, headers=hb)
    assert resp.json()["state"] == "DECLINED"
    detail = client.get(f"/v1/missions/{mission.code}", headers=auth_headers(lead, org)).json()
    assert detail["slots"][0]["open_positions"] == 1
    again = client.post(
        f"/v1/missions/{mission.code}/assignments",
        json={"slot": "Geologist", "crew": "Bob"},
        headers=auth_headers(lead, org),
    )
    assert again.status_code == 409 and again.json()["code"] == "assignment.crew_exited"


def test_withdraw_from_approved_mission_returns_to_draft_and_notifies_owner(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    a = make_assignment(db, mission, slot, bob, "ACCEPTED")
    director = make_member(db, org, "DIRECTOR")
    mission.state, mission.submitted_by, mission.approvals_required_snapshot = "APPROVED", lead.id, 1
    db.add(
        m.Approval(
            org_id=org.id,
            mission_id=mission.id,
            revision=mission.revision,
            approver_id=director.id,
            decision="APPROVE",
        )
    )
    db.flush()
    resp = client.post(
        f"/v1/assignments/{a.id}/withdraw",
        json={"reason": "knee injury"},
        headers=auth_headers(bob.membership, org),
    )
    assert resp.status_code == 200 and resp.json()["state"] == "WITHDRAWN"
    db.refresh(mission)
    assert mission.state == "DRAFT" and mission.revision == 2
    detail = client.get(f"/v1/missions/{mission.code}", headers=auth_headers(lead, org)).json()
    assert detail["approvals"]["received"] == 0  # approval was for revision 1
    note = db.scalar(select(m.Notification).where(m.Notification.recipient_id == lead.id))
    assert note.kind == "crew.withdrew" and note.data["reason"] == "knee injury"
    assert note.data["returned_to_draft"] is True and note.data["slot"] == "Geologist"


def test_withdraw_requires_reason(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    a = make_assignment(db, mission, slot, bob, "ACCEPTED")
    resp = client.post(
        f"/v1/assignments/{a.id}/withdraw", json={"reason": "  "}, headers=auth_headers(bob.membership, org)
    )
    assert resp.status_code == 422
    db.refresh(a)
    assert a.state == "ACCEPTED"


def test_no_withdrawal_once_active_but_lead_can_release(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    a = make_assignment(db, mission, slot, bob, "ACCEPTED")
    mission.state = "ACTIVE"
    db.flush()
    resp = client.post(
        f"/v1/assignments/{a.id}/withdraw",
        json={"reason": "emergency"},
        headers=auth_headers(bob.membership, org),
    )
    assert resp.status_code == 409 and "lead" in resp.json()["detail"]
    released = client.post(f"/v1/assignments/{a.id}/release", headers=auth_headers(lead, org))
    assert released.status_code == 200 and released.json()["state"] == "RELEASED"
    db.refresh(mission)
    assert mission.state == "ACTIVE"


def test_withdrawn_crew_frees_their_blocked_period(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    a = make_assignment(db, mission, slot, bob, "ACCEPTED")
    client.post(
        f"/v1/assignments/{a.id}/withdraw",
        json={"reason": "reassigned"},
        headers=auth_headers(bob.membership, org),
    )
    other = make_mission(db, org, lead, START)
    offer = make_assignment(db, other, make_slot(db, other, "Geologist", {geo: 3}), bob)
    assert (
        client.post(f"/v1/assignments/{offer.id}/accept", headers=auth_headers(bob.membership, org)).status_code == 200
    )


def test_crew_history(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    make_assignment(db, mission, slot, bob)
    rows = client.get("/v1/crew/me/assignments", headers=auth_headers(bob.membership, org)).json()
    assert [(r["mission_code"], r["slot"], r["state"]) for r in rows] == [(mission.code, "Geologist", "PROPOSED")]


def test_isolation_assignments(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    a = make_assignment(db, mission, slot, bob)
    other = make_org(db)
    intruder = make_member(db, other, "DIRECTOR")
    h = auth_headers(intruder, other)
    assert client.post(f"/v1/assignments/{a.id}/release", headers=h).status_code == 404
    assert client.get("/v1/assignments", headers=h).json() == []
    assert (
        client.post(
            f"/v1/missions/{mission.code}/assignments", json={"slot": "Geologist", "crew": "Bob"}, headers=h
        ).status_code
        == 404
    )


# ------------------------------------------------------------------ concurrency (real commits)


def test_concurrent_double_accept_only_one_wins(engine):
    """Two overlapping offers accepted at the same moment on two connections: exactly one succeeds."""
    with Session(engine) as s:
        org, lead, geo, bob, m1, slot1 = _world(s)
        m2 = make_mission(s, org, lead, START + timedelta(days=3))
        a1 = make_assignment(s, m1, slot1, bob)
        a2 = make_assignment(s, m2, make_slot(s, m2, "Geologist", {geo: 3}), bob)
        ctx = TenantContext(
            org_id=org.id,
            membership_id=bob.membership_id,
            user_id=bob.membership.user_id,
            role=Role.CREW,
            crew_id=bob.id,
        )
        ids, org_id, user_ids = (a1.id, a2.id), org.id, [lead.user_id, bob.membership.user_id]
        s.commit()

    barrier, results = threading.Barrier(2), []

    def attempt(assignment_id):
        with Session(engine) as s:
            barrier.wait()
            try:
                svc.accept(s, ctx, str(assignment_id), now=NOW)
                results.append("ok")
            except Conflict as exc:
                results.append(exc.code)

    try:
        threads = [threading.Thread(target=attempt, args=(i,)) for i in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        assert sorted(results) == ["assignment.double_booked", "ok"]
    finally:
        _purge(engine, org_id, user_ids)


def _purge(engine, org_id, user_ids):
    with Session(engine) as s:
        for model in (
            m.Notification,
            m.AuditEvent,
            m.Approval,
            m.Assignment,
            m.SlotRequirement,
            m.MissionSlot,
            m.Mission,
            m.Unavailability,
            m.CrewSkill,
            m.CrewProfile,
            m.Skill,
            m.Membership,
        ):
            s.execute(delete(model).where(model.org_id == org_id))
        s.execute(delete(m.Organisation).where(m.Organisation.id == org_id))
        s.execute(delete(m.User).where(m.User.id.in_(user_ids)))
        s.commit()
