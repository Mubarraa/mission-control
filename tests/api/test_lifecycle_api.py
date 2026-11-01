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


def _ready_mission(db, approvals_required=1, owner_role="LEAD"):
    """A DRAFT mission whose only slot is filled by an ACCEPTED crew member."""
    org = make_org(db, prefix="ART", approvals_required=approvals_required)
    owner = make_member(db, org, owner_role)
    geo = make_skill(db, org, "Geology")
    bob = make_crew(db, org, name="Bob", skills={geo: 4})
    mission = make_mission(db, org, owner, START)
    slot = make_slot(db, mission, "Geologist", {geo: 3})
    make_assignment(db, mission, slot, bob, "ACCEPTED")
    return org, owner, mission, geo, bob


def _post(client, headers, mission, action, **body):
    return client.post(f"/v1/missions/{mission.code}/{action}", json=body or None, headers=headers)


def test_submit_gate_lists_unfilled_slots(client, db, auth_headers):
    org, lead, mission, geo, _ = _ready_mission(db)
    make_slot(db, mission, "Commander", {geo: 1}, headcount=2)
    resp = _post(client, auth_headers(lead, org), mission, "submit")
    assert resp.status_code == 409 and resp.json()["code"] == "mission.unfilled_slots"
    assert resp.json()["unfilled"] == [{"slot": "Commander", "accepted": 0, "headcount": 2}]


def test_submit_then_other_director_approves(client, db, auth_headers):
    org, lead, mission, *_ = _ready_mission(db)
    submitted = _post(client, auth_headers(lead, org), mission, "submit").json()
    assert submitted["state"] == "PENDING_APPROVAL" and submitted["submitted_by"]["id"] == str(lead.id)
    director = make_member(db, org, "DIRECTOR")
    approved = _post(client, auth_headers(director, org), mission, "approve", revision=submitted["revision"])
    assert approved.status_code == 200 and approved.json()["state"] == "APPROVED"


def test_lead_cannot_approve_own_mission(client, db, auth_headers):
    org, lead, mission, *_ = _ready_mission(db)
    h = auth_headers(lead, org)
    rev = _post(client, h, mission, "submit").json()["revision"]
    assert _post(client, h, mission, "approve", revision=rev).status_code == 403


def test_director_cannot_approve_own_submission(client, db, auth_headers):
    org, director, mission, *_ = _ready_mission(db, owner_role="DIRECTOR")
    h = auth_headers(director, org)
    rev = _post(client, h, mission, "submit").json()["revision"]
    resp = _post(client, h, mission, "approve", revision=rev)
    assert resp.status_code == 403 and resp.json()["code"] == "approval.self_approval"
    assert "different Director" in resp.json()["detail"]


def test_two_approvals_required(client, db, auth_headers):
    org, lead, mission, *_ = _ready_mission(db, approvals_required=2)
    rev = _post(client, auth_headers(lead, org), mission, "submit").json()["revision"]
    d1, d2 = make_member(db, org, "DIRECTOR"), make_member(db, org, "DIRECTOR")
    first = _post(client, auth_headers(d1, org), mission, "approve", revision=rev).json()
    assert first["state"] == "PENDING_APPROVAL" and first["approvals"] == {
        "required": 2,
        "received": 1,
        "approvers": [{"id": str(d1.id), "name": d1.user.name}],
    }
    again = _post(client, auth_headers(d1, org), mission, "approve", revision=rev)
    assert again.status_code == 409 and again.json()["code"] == "approval.duplicate"
    assert _post(client, auth_headers(d2, org), mission, "approve", revision=rev).json()["state"] == "APPROVED"


def test_policy_change_does_not_affect_pending_mission(client, db, auth_headers):
    org, lead, mission, *_ = _ready_mission(db, approvals_required=1)
    rev = _post(client, auth_headers(lead, org), mission, "submit").json()["revision"]
    director = make_member(db, org, "DIRECTOR")
    hd = auth_headers(director, org)
    client.patch("/v1/org/settings", json={"approvals_required": 2}, headers=hd)
    assert (
        _post(client, auth_headers(make_member(db, org, "DIRECTOR"), org), mission, "approve", revision=rev).json()[
            "state"
        ]
        == "APPROVED"
    )


def test_edit_while_pending_voids_and_returns_to_draft(client, db, auth_headers):
    org, lead, mission, *_ = _ready_mission(db, approvals_required=2)
    hl = auth_headers(lead, org)
    rev = _post(client, hl, mission, "submit").json()["revision"]
    director = make_member(db, org, "DIRECTOR")
    _post(client, auth_headers(director, org), mission, "approve", revision=rev)
    edited = client.patch(
        f"/v1/missions/{mission.code}",
        json={"ends_at": (mission.ends_at + timedelta(days=2)).isoformat()},
        headers=hl,
    ).json()
    assert edited["state"] == "DRAFT" and edited["revision"] == rev + 1 and edited["approvals"]["received"] == 0
    actions = [e["action"] for e in client.get(f"/v1/missions/{mission.code}/history", headers=hl).json()]
    assert "mission.auto_withdrawn" in actions


def test_stale_approval_rejected(client, db, auth_headers):
    org, lead, mission, *_ = _ready_mission(db)
    rev = _post(client, auth_headers(lead, org), mission, "submit").json()["revision"]
    resp = _post(client, auth_headers(make_member(db, org, "DIRECTOR"), org), mission, "approve", revision=rev - 1)
    assert resp.status_code == 409 and resp.json()["code"] == "approval.stale"


def test_rejection_requires_reason_and_returns_to_draft(client, db, auth_headers):
    org, lead, mission, *_ = _ready_mission(db)
    rev = _post(client, auth_headers(lead, org), mission, "submit").json()["revision"]
    hd = auth_headers(make_member(db, org, "DIRECTOR"), org)
    assert _post(client, hd, mission, "reject", revision=rev).status_code == 422
    rejected = _post(client, hd, mission, "reject", revision=rev, reason="Need a backup geologist").json()
    assert rejected["state"] == "DRAFT" and rejected["revision"] == rev + 1


def test_submit_after_start_date_rejected(client, db, auth_headers, clock):
    org, lead, mission, *_ = _ready_mission(db)
    clock.set(mission.starts_at + timedelta(hours=1))
    resp = _post(client, auth_headers(lead, org), mission, "submit")
    assert resp.status_code == 409 and resp.json()["code"] == "mission.window_started"


def test_approve_after_start_date_rejected(client, db, auth_headers, clock):
    org, lead, mission, *_ = _ready_mission(db)
    director = make_member(db, org, "DIRECTOR")
    rev = _post(client, auth_headers(lead, org), mission, "submit").json()["revision"]
    clock.set(mission.starts_at)
    hd, hl = auth_headers(director, org), auth_headers(lead, org)  # fresh tokens at the new time
    resp = _post(client, hd, mission, "approve", revision=rev)
    assert resp.status_code == 409 and resp.json()["code"] == "mission.window_started"
    assert client.get(f"/v1/missions/{mission.code}", headers=hl).json()["state"] == "PENDING_APPROVAL"


def test_full_lifecycle_and_illegal_transition(client, db, auth_headers):
    org, lead, mission, *_ = _ready_mission(db)
    hl = auth_headers(lead, org)
    bad = _post(client, hl, mission, "start")
    assert bad.status_code == 409 and bad.json()["allowed_actions"] == ["cancel", "submit"]
    rev = _post(client, hl, mission, "submit").json()["revision"]
    _post(client, auth_headers(make_member(db, org, "DIRECTOR"), org), mission, "approve", revision=rev)
    assert _post(client, hl, mission, "start").json()["state"] == "ACTIVE"
    assert _post(client, hl, mission, "complete").json()["state"] == "COMPLETED"
    assert _post(client, hl, mission, "cancel").status_code == 409


def test_cancel_releases_assignments(client, db, auth_headers):
    org, lead, mission, geo, bob = _ready_mission(db)
    hl = auth_headers(lead, org)
    assert _post(client, hl, mission, "cancel").json()["state"] == "CANCELLED"
    rows = client.get("/v1/crew/me/assignments", headers=auth_headers(bob.membership, org)).json()
    assert rows[0]["state"] == "RELEASED"


def test_other_lead_and_crew_cannot_transition(client, db, auth_headers):
    org, lead, mission, geo, bob = _ready_mission(db)
    other = auth_headers(make_member(db, org, "LEAD"), org)
    assert _post(client, other, mission, "submit").status_code == 403
    crew_h = auth_headers(bob.membership, org)
    resp = _post(client, crew_h, mission, "cancel")
    assert resp.status_code == 403
