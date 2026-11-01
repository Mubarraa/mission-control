from datetime import timedelta

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


def _world(db, **settings):
    org = make_org(db, prefix="ART", **settings)
    lead = make_member(db, org, "LEAD")
    geo = make_skill(db, org, "Geology")
    bob = make_crew(db, org, name="Bob", skills={geo: 4})
    mission = make_mission(db, org, lead, START)
    slot = make_slot(db, mission, "Geologist", {geo: 3})
    return org, lead, geo, bob, mission, slot


def test_director_inbox_marks_own_submission(client, db, auth_headers):
    org = make_org(db)
    d1, d2 = make_member(db, org, "DIRECTOR"), make_member(db, org, "LEAD")
    make_mission(db, org, d1, START, state="PENDING_APPROVAL", name="Mine").submitted_by = d1.id
    make_mission(db, org, d2, START, state="PENDING_APPROVAL", name="Theirs").submitted_by = d2.id
    db.flush()
    rows = client.get("/v1/inbox", headers=auth_headers(d1, org)).json()["approvals"]
    flags = {r["name"]: r["needs_other_approver"] for r in rows}
    assert flags == {"Mine": True, "Theirs": False}


def test_crew_inbox_lists_offers_and_unverified_skills(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    make_assignment(db, mission, slot, bob)
    h = auth_headers(bob.membership, org)
    client.put("/v1/crew/me/skills/geology", json={"level": 5}, headers=h)
    body = client.get("/v1/inbox", headers=h).json()
    assert [(o["mission_code"], o["slot"]) for o in body["offers"]] == [(mission.code, "Geologist")]
    assert body["skills_awaiting_verification"][0]["skill"] == "Geology"


def test_lead_sees_offer_age_and_stale_flag(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db, stale_offer_days=3)
    make_slot(db, mission, "Backup", {geo: 1})
    carol = make_crew(db, org, name="Carol", skills={geo: 2})
    make_assignment(db, mission, slot, bob, offered_at=NOW - timedelta(days=4))
    make_assignment(db, mission, mission.slots[1], carol, offered_at=NOW - timedelta(days=2))
    item = client.get("/v1/inbox", headers=auth_headers(lead, org)).json()["missions"][0]
    flags = {o["crew"]: (o["age_days"], o["stale"]) for o in item["offers"]}
    assert flags == {"Bob": (4.0, True), "Carol": (2.0, False)}


def test_withdrawal_notification_visible_only_to_owner_and_dismissable(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    a = make_assignment(db, mission, slot, bob, "ACCEPTED")
    client.post(
        f"/v1/assignments/{a.id}/withdraw",
        json={"reason": "knee injury"},
        headers=auth_headers(bob.membership, org),
    )
    hl = auth_headers(lead, org)
    notes = client.get("/v1/inbox", headers=hl).json()["notifications"]
    assert len(notes) == 1 and notes[0]["data"]["reason"] == "knee injury"
    nid = notes[0]["id"]
    other_lead = auth_headers(make_member(db, org, "LEAD"), org)
    assert client.get("/v1/inbox", headers=other_lead).json()["notifications"] == []
    assert client.post(f"/v1/notifications/{nid}/dismiss", headers=other_lead).status_code == 404
    other_org = make_org(db)
    outsider = auth_headers(make_member(db, other_org, "DIRECTOR"), other_org)
    assert client.post(f"/v1/notifications/{nid}/dismiss", headers=outsider).status_code == 404
    assert client.post(f"/v1/notifications/{nid}/dismiss", headers=hl).status_code == 200
    assert client.get("/v1/inbox", headers=hl).json()["notifications"] == []
    history = [e["action"] for e in client.get(f"/v1/missions/{mission.code}/history", headers=hl).json()]
    assert "assignment.withdrawn" in history  # dismissing never touches the audit trail


def test_lead_sees_rejection_and_exits(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    a = make_assignment(db, mission, slot, bob)
    client.post(
        f"/v1/assignments/{a.id}/decline",
        json={"reason": "family"},
        headers=auth_headers(bob.membership, org),
    )
    item = client.get("/v1/inbox", headers=auth_headers(lead, org)).json()["missions"][0]
    assert item["exits"] == [{"crew": "Bob", "slot": "Geologist", "state": "DECLINED", "reason": "family"}]
    assert item["unfilled"][0]["slot"] == "Geologist"


def test_inbox_shows_every_slot_with_accepted_and_offered(client, db, auth_headers):
    org, lead, geo, bob, mission, slot = _world(db)
    make_slot(db, mission, "Backup", {geo: 1}, headcount=2)
    carol = make_crew(db, org, name="Carol", skills={geo: 2})
    make_assignment(db, mission, slot, bob, "ACCEPTED")
    make_assignment(db, mission, mission.slots[1], carol)
    item = client.get("/v1/inbox", headers=auth_headers(lead, org)).json()["missions"][0]
    assert (item["accepted_total"], item["positions_total"]) == (1, 3)
    assert [(s["slot"], s["accepted"], [o["crew"] for o in s["offered"]], s["open"]) for s in item["slots"]] == [
        ("Geologist", ["Bob"], [], 0),
        ("Backup", [], ["Carol"], 1),
    ]


def test_fully_crewed_notification_only_on_last_acceptance(client, db, auth_headers):
    from sqlalchemy import select

    from mission_control.db import models as m

    org, lead, geo, bob, mission, slot = _world(db)
    backup = make_slot(db, mission, "Backup", {geo: 1})
    carol = make_crew(db, org, name="Carol", skills={geo: 2})
    a1, a2 = make_assignment(db, mission, slot, bob), make_assignment(db, mission, backup, carol)

    def notes():
        return db.scalars(select(m.Notification).where(m.Notification.kind == "mission.fully_crewed")).all()

    client.post(f"/v1/assignments/{a1.id}/accept", headers=auth_headers(bob.membership, org))
    assert notes() == []
    client.post(f"/v1/assignments/{a2.id}/accept", headers=auth_headers(carol.membership, org))
    [note] = notes()
    assert note.recipient_id == lead.id and note.data["mission_code"] == mission.code and note.data["positions"] == 2
