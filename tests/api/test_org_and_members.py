from sqlalchemy import select

from mission_control.db import models as m
from tests.factories import PASSWORD, make_member, make_org


def test_only_directors_change_settings(client, db, auth_headers):
    org = make_org(db)
    for role in ("LEAD", "CREW"):
        headers = auth_headers(make_member(db, org, role), org)
        resp = client.patch("/v1/org/settings", json={"approvals_required": 2}, headers=headers)
        assert resp.status_code == 403
        assert "Director" in resp.json()["detail"]


def test_director_updates_settings_and_it_is_audited(client, db, auth_headers):
    org = make_org(db)
    headers = auth_headers(make_member(db, org, "DIRECTOR"), org)
    resp = client.patch("/v1/org/settings", json={"approvals_required": 2, "stale_offer_days": 5}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["approvals_required"] == 2 and resp.json()["stale_offer_days"] == 5
    event = db.scalar(select(m.AuditEvent).where(m.AuditEvent.action == "settings.updated"))
    assert event.data["after"]["approvals_required"] == 2


def test_settings_validation(client, db, auth_headers):
    org = make_org(db)
    headers = auth_headers(make_member(db, org, "DIRECTOR"), org)
    assert client.patch("/v1/org/settings", json={"approvals_required": 0}, headers=headers).status_code == 422


def test_director_adds_member_who_can_log_in(client, db, auth_headers):
    org = make_org(db)
    headers = auth_headers(make_member(db, org, "DIRECTOR"), org)
    resp = client.post(
        "/v1/members",
        json={"email": "New@Crew.test", "name": "New Crew", "role": "CREW", "password": "initial-pass"},
        headers=headers,
    )
    assert resp.status_code == 201 and resp.json()["email"] == "new@crew.test"
    login = client.post("/v1/auth/login", json={"email": "new@crew.test", "password": "initial-pass", "org": org.slug})
    assert login.status_code == 200 and login.json()["role"] == "CREW"


def test_duplicate_member_conflicts(client, db, auth_headers):
    org = make_org(db)
    headers = auth_headers(make_member(db, org, "DIRECTOR"), org)
    existing = make_member(db, org, "CREW")
    body = {"email": existing.user.email, "name": "X", "role": "CREW", "password": "whatever1"}
    assert client.post("/v1/members", json=body, headers=headers).status_code == 409


def test_director_deactivates_member(client, db, auth_headers):
    org = make_org(db)
    headers = auth_headers(make_member(db, org, "DIRECTOR"), org)
    crew = make_member(db, org, "CREW")
    resp = client.patch(f"/v1/members/{crew.id}", json={"active": False}, headers=headers)
    assert resp.status_code == 200 and resp.json()["active"] is False
    login = client.post("/v1/auth/login", json={"email": crew.user.email, "password": PASSWORD, "org": org.slug})
    assert login.status_code == 401


def test_director_cannot_deactivate_self(client, db, auth_headers):
    org = make_org(db)
    director = make_member(db, org, "DIRECTOR")
    resp = client.patch(f"/v1/members/{director.id}", json={"active": False}, headers=auth_headers(director, org))
    assert resp.status_code == 403


def test_isolation_members(client, db, auth_headers):
    """Org A's Director cannot list, read or modify Org B's members."""
    org_a, org_b = make_org(db), make_org(db)
    headers_a = auth_headers(make_member(db, org_a, "DIRECTOR"), org_a)
    b_member = make_member(db, org_b, "CREW")

    listed = client.get("/v1/members", headers=headers_a).json()
    assert str(b_member.id) not in {row["id"] for row in listed}
    assert client.get(f"/v1/members/{b_member.id}", headers=headers_a).status_code == 404
    patch = client.patch(f"/v1/members/{b_member.id}", json={"active": False}, headers=headers_a)
    assert patch.status_code == 404
    db.refresh(b_member)
    assert b_member.active is True


def test_settings_are_per_org(client, db, auth_headers):
    org_a, org_b = make_org(db), make_org(db)
    client.patch(
        "/v1/org/settings",
        json={"approvals_required": 3},
        headers=auth_headers(make_member(db, org_a, "DIRECTOR"), org_a),
    )
    b = client.get("/v1/org/settings", headers=auth_headers(make_member(db, org_b, "CREW"), org_b)).json()
    assert b["approvals_required"] == 1
