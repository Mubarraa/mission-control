from sqlalchemy import select

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

WINDOW = {"starts_at": "2027-03-01T00:00:00Z", "ends_at": "2027-03-21T00:00:00Z"}


def _lead(db, auth_headers, prefix="ART"):
    org = make_org(db, prefix=prefix)
    lead = make_member(db, org, "LEAD")
    return org, lead, auth_headers(lead, org)


def test_lead_creates_mission_with_code_and_draft_state(client, db, auth_headers):
    org, lead, h = _lead(db, auth_headers)
    resp = client.post("/v1/missions", json={"name": "Lunar South Pole Survey", **WINDOW}, headers=h)
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == "ART-1" and body["state"] == "DRAFT" and body["revision"] == 1
    assert body["owner"]["id"] == str(lead.id) and "submit" in body["allowed_actions"]
    second = client.post("/v1/missions", json={"name": "Second", **WINDOW}, headers=h).json()
    assert second["code"] == "ART-2"


def test_code_accepted_wherever_mission_is_referenced(client, db, auth_headers):
    org, _, h = _lead(db, auth_headers)
    mid = client.post("/v1/missions", json={"name": "M", **WINDOW}, headers=h).json()["id"]
    assert client.get("/v1/missions/art-1", headers=h).json()["id"] == mid
    assert client.get(f"/v1/missions/{mid}", headers=h).json()["code"] == "ART-1"


def test_invalid_windows(client, db, auth_headers):
    _, _, h = _lead(db, auth_headers)
    backwards = {"name": "M", "starts_at": WINDOW["ends_at"], "ends_at": WINDOW["starts_at"]}
    assert client.post("/v1/missions", json=backwards, headers=h).status_code == 422
    past = {"name": "M", "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-01-05T00:00:00Z"}
    resp = client.post("/v1/missions", json=past, headers=h)
    assert resp.status_code == 422 and resp.json()["code"] == "mission.start_in_past"


def test_crew_cannot_create_missions(client, db, auth_headers):
    org = make_org(db)
    h = auth_headers(make_member(db, org, "CREW"), org)
    assert client.post("/v1/missions", json={"name": "M", **WINDOW}, headers=h).status_code == 403


def test_add_slot_bumps_revision(client, db, auth_headers):
    org, _, h = _lead(db, auth_headers)
    make_skill(db, org, "Geology")
    client.post("/v1/missions", json={"name": "M", **WINDOW}, headers=h)
    resp = client.post(
        "/v1/missions/ART-1/slots",
        json={
            "role_name": "Geologist",
            "headcount": 2,
            "requirements": [{"skill": "geology", "min_level": 3}],
        },
        headers=h,
    )
    body = resp.json()
    assert resp.status_code == 201 and body["revision"] == 2
    assert body["slots"][0]["open_positions"] == 2 and body["slots"][0]["requirements"][0]["min_level"] == 3


def test_unknown_or_other_org_skill_rejected(client, db, auth_headers):
    org, _, h = _lead(db, auth_headers)
    other = make_org(db)
    foreign = make_skill(db, other, "Xenobiology")
    client.post("/v1/missions", json={"name": "M", **WINDOW}, headers=h)
    for ref in ("nonexistent", str(foreign.id)):
        resp = client.post(
            "/v1/missions/ART-1/slots",
            json={"role_name": "X", "requirements": [{"skill": ref, "min_level": 2}]},
            headers=h,
        )
        assert resp.status_code == 404 and resp.json()["code"] == "skill.not_found"


def test_other_lead_cannot_edit(client, db, auth_headers):
    org, _, h = _lead(db, auth_headers)
    client.post("/v1/missions", json={"name": "M", **WINDOW}, headers=h)
    other = auth_headers(make_member(db, org, "LEAD"), org)
    assert client.patch("/v1/missions/ART-1", json={"name": "Hijack"}, headers=other).status_code == 403


def test_crew_sees_only_missions_they_are_on(client, db, auth_headers, clock):
    org, lead, h = _lead(db, auth_headers)
    geo = make_skill(db, org, "Geology")
    bob = make_crew(db, org, name="Bob", skills={geo: 4})
    on = make_mission(db, org, lead, clock.now().replace(year=2027, month=3))
    off = make_mission(db, org, lead, clock.now().replace(year=2027, month=4))
    make_assignment(db, on, make_slot(db, on, "Geologist", {geo: 3}), bob)
    hb = auth_headers(bob.membership, org)
    assert [x["code"] for x in client.get("/v1/missions", headers=hb).json()] == [on.code]
    assert client.get(f"/v1/missions/{off.code}", headers=hb).status_code == 404


def test_window_edit_is_material_and_audited(client, db, auth_headers):
    org, _, h = _lead(db, auth_headers)
    client.post("/v1/missions", json={"name": "M", **WINDOW}, headers=h)
    resp = client.patch("/v1/missions/ART-1", json={"ends_at": "2027-03-25T00:00:00Z"}, headers=h)
    assert resp.json()["revision"] == 2
    rename = client.patch("/v1/missions/ART-1", json={"name": "Renamed"}, headers=h)
    assert rename.json()["revision"] == 2  # names are not material
    history = client.get("/v1/missions/ART-1/history", headers=h).json()
    assert [e["action"] for e in history] == ["mission.created", "mission.changed"]


def test_isolation_missions_and_slots(client, db, auth_headers):
    org_a, _, h_a = _lead(db, auth_headers, prefix="AAA")
    org_b, _, h_b = _lead(db, auth_headers, prefix="BBB")
    make_skill(db, org_b, "Geology")
    b = client.post("/v1/missions", json={"name": "Secret", **WINDOW}, headers=h_b).json()
    client.post(
        "/v1/missions/BBB-1/slots",
        json={"role_name": "G", "requirements": [{"skill": "geology", "min_level": 1}]},
        headers=h_b,
    )
    assert client.get("/v1/missions", headers=h_a).json() == []
    for ref in ("BBB-1", b["id"]):
        assert client.get(f"/v1/missions/{ref}", headers=h_a).status_code == 404
        assert client.patch(f"/v1/missions/{ref}", json={"name": "x"}, headers=h_a).status_code == 404
        assert (
            client.post(
                f"/v1/missions/{ref}/slots",
                json={"role_name": "x", "requirements": [{"skill": "g", "min_level": 1}]},
                headers=h_a,
            ).status_code
            == 404
        )
        assert client.get(f"/v1/missions/{ref}/history", headers=h_a).status_code == 404
    slot_id = db.scalar(select(m.MissionSlot.id).where(m.MissionSlot.org_id == org_b.id))
    assert client.delete(f"/v1/missions/BBB-1/slots/{slot_id}", headers=h_a).status_code == 404
