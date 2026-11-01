from datetime import timedelta

from sqlalchemy import func, select

from mission_control.db import models as m
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


def _world(db):
    org = make_org(db, prefix="ART")
    lead = make_member(db, org, "LEAD")
    pil, geo = make_skill(db, org, "Piloting"), make_skill(db, org, "Geology")
    alice = make_crew(db, org, name="Alice", skills={pil: 5, geo: 5})
    bob = make_crew(db, org, name="Bob", skills={pil: 2, geo: 4})
    mission = make_mission(db, org, lead, START, days=20)
    make_slot(db, mission, "Commander", {pil: 4})
    make_slot(db, mission, "Geologist", {geo: 3})
    return org, lead, mission, alice, bob, pil, geo


def test_match_suggests_optimal_crew_and_writes_nothing(client, db, auth_headers):
    org, lead, mission, alice, bob, *_ = _world(db)
    before = db.scalar(select(func.count()).select_from(m.Assignment))
    resp = client.get(f"/v1/missions/{mission.code}/match", headers=auth_headers(lead, org))
    assert resp.status_code == 200
    body = resp.json()
    assert {p["label"]: p["suggestion"]["name"] for p in body["positions"]} == {
        "Commander": "Alice",
        "Geologist": "Bob",
    }
    assert body["summary"] == {"open": 2, "filled": 2, "unfilled": 0}
    assert set(body["positions"][0]["suggestion"]["breakdown"]) == {
        "fit",
        "rightsizing",
        "workload",
        "experience",
        "penalty",
    }
    assert db.scalar(select(func.count()).select_from(m.Assignment)) == before


def test_match_considers_only_open_positions(client, db, auth_headers):
    org, lead, mission, alice, bob, *_ = _world(db)
    make_assignment(db, mission, mission.slots[0], alice)  # Commander already offered to Alice
    body = client.get(f"/v1/missions/{mission.code}/match", headers=auth_headers(lead, org)).json()
    assert [p["label"] for p in body["positions"]] == ["Geologist"]
    assert body["positions"][0]["suggestion"]["name"] == "Bob"


def test_unfillable_slot_reports_why_not(client, db, auth_headers):
    org, lead, mission, alice, bob, pil, geo = _world(db)
    eva = make_skill(db, org, "EVA")
    make_slot(db, mission, "EVA Specialist", {eva: 3})
    body = client.get(f"/v1/missions/{mission.code}/match", headers=auth_headers(lead, org)).json()
    gap = body["positions"][2]
    assert gap["suggestion"] is None and gap["excluded_total"] == 2
    assert gap["unfilled_reasons"][0]["rules"][0]["detail"] == "no verified eva"


def test_apply_creates_proposed_offers(client, db, auth_headers):
    org, lead, mission, alice, bob, *_ = _world(db)
    h = auth_headers(lead, org)
    body = client.get(f"/v1/missions/{mission.code}/match", headers=h).json()
    pairs = [{"slot_id": p["slot_id"], "crew_id": p["suggestion"]["crew_id"]} for p in body["positions"]]
    resp = client.post(f"/v1/missions/{mission.code}/match/apply", json={"pairs": pairs}, headers=h)
    assert resp.status_code == 200
    out = resp.json()
    assert out["rejected"] == [] and {a["state"] for a in out["applied"]} == {"PROPOSED"}
    assert {a["source"] for a in out["applied"]} == {"MATCHER"}


def test_stale_suggestion_rejected_others_applied(client, db, auth_headers):
    org, lead, mission, alice, bob, pil, geo = _world(db)
    h = auth_headers(lead, org)
    body = client.get(f"/v1/missions/{mission.code}/match", headers=h).json()
    # Bob accepts a conflicting mission after the match ran.
    other = make_mission(db, org, lead, START + timedelta(days=2))
    make_assignment(db, other, make_slot(db, other, "Geologist", {geo: 3}), bob, "ACCEPTED")
    pairs = [{"slot_id": p["slot_id"], "crew_id": p["suggestion"]["crew_id"]} for p in body["positions"]]
    out = client.post(f"/v1/missions/{mission.code}/match/apply", json={"pairs": pairs}, headers=h).json()
    assert [a["crew_name"] for a in out["applied"]] == ["Alice"]
    assert out["rejected"][0]["crew_name"] == "Bob" and other.code in out["rejected"][0]["reason"]


def test_match_on_non_draft_mission_conflicts(client, db, auth_headers):
    org, lead, mission, *_ = _world(db)
    mission.state = "PENDING_APPROVAL"
    db.flush()
    resp = client.get(f"/v1/missions/{mission.code}/match", headers=auth_headers(lead, org))
    assert resp.status_code == 409 and resp.json()["code"] == "match.mission_not_draft"


def test_manual_offer_to_ineligible_crew_rejected(client, db, auth_headers):
    org, lead, mission, alice, bob, *_ = _world(db)
    resp = client.post(
        f"/v1/missions/{mission.code}/assignments",
        json={"slot": "Commander", "crew": "Bob"},
        headers=auth_headers(lead, org),
    )
    assert resp.status_code == 409 and "piloting 2 < 4 required" in resp.json()["detail"]


def test_crew_and_other_leads_cannot_run_match(client, db, auth_headers):
    org, lead, mission, alice, *_ = _world(db)
    assert (
        client.get(
            f"/v1/missions/{mission.code}/match", headers=auth_headers(make_member(db, org, "LEAD"), org)
        ).status_code
        == 403
    )
    assert (
        client.get(f"/v1/missions/{mission.code}/match", headers=auth_headers(alice.membership, org)).status_code == 403
    )


def test_isolation_matching(client, db, auth_headers):
    org, lead, mission, *_ = _world(db)
    other = make_org(db)
    h = auth_headers(make_member(db, other, "DIRECTOR"), other)
    assert client.get(f"/v1/missions/{mission.code}/match", headers=h).status_code == 404
    # Org B's crew never show up in Org A's results or why-not lists.
    make_crew(db, other, name="Outsider", skills={make_skill(db, other, "Piloting"): 5})
    body = client.get(f"/v1/missions/{mission.code}/match?all=true", headers=auth_headers(lead, org)).json()
    names = {s["name"] for p in body["positions"] for s in p["alternatives"]} | {
        e["name"] for p in body["positions"] for e in p["unfilled_reasons"]
    }
    assert "Outsider" not in names
