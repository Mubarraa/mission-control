from tests.factories import make_crew, make_member, make_org, make_skill


def _ctx(db, auth_headers):
    org = make_org(db)
    director = make_member(db, org, "DIRECTOR")
    return org, director, auth_headers(director, org)


# ------------------------------------------------------------------ taxonomy (3.1)


def test_director_defines_skill_and_duplicates_conflict(client, db, auth_headers):
    org, _, h = _ctx(db, auth_headers)
    assert client.post("/v1/skills", json={"name": "EVA", "category": "Operations"}, headers=h).status_code == 201
    dup = client.post("/v1/skills", json={"name": "eva"}, headers=h)
    assert dup.status_code == 409 and dup.json()["code"] == "skill.exists"


def test_same_skill_name_in_other_org_is_fine(client, db, auth_headers):
    org_a, _, h_a = _ctx(db, auth_headers)
    org_b, _, h_b = _ctx(db, auth_headers)
    assert client.post("/v1/skills", json={"name": "EVA"}, headers=h_a).status_code == 201
    assert client.post("/v1/skills", json={"name": "EVA"}, headers=h_b).status_code == 201


def test_only_directors_manage_skills(client, db, auth_headers):
    org = make_org(db)
    h = auth_headers(make_member(db, org, "LEAD"), org)
    assert client.post("/v1/skills", json={"name": "EVA"}, headers=h).status_code == 403


def test_deactivated_skill_hidden_by_default(client, db, auth_headers):
    org, _, h = _ctx(db, auth_headers)
    make_skill(db, org, "Old")
    assert client.patch("/v1/skills/old", json={"active": False}, headers=h).status_code == 200
    assert [s["name"] for s in client.get("/v1/skills", headers=h).json()] == []
    assert len(client.get("/v1/skills?include_inactive=true", headers=h).json()) == 1


def test_crew_cannot_read_other_profiles(client, db, auth_headers):
    org = make_org(db)
    me = make_crew(db, org, name="Me")
    other = make_crew(db, org, name="Other")
    h = auth_headers(me.membership, org)
    assert client.get(f"/v1/crew/{other.id}", headers=h).status_code == 404
    assert client.get("/v1/crew/me", headers=h).json()["id"] == str(me.id)
    assert [c["id"] for c in client.get("/v1/crew", headers=h).json()] == [str(me.id)]


def test_director_creates_crew_profile(client, db, auth_headers):
    org, _, h = _ctx(db, auth_headers)
    member = make_member(db, org, "LEAD", name="Lead Who Flies")
    resp = client.post("/v1/crew", json={"member": member.user.email}, headers=h)
    assert resp.status_code == 201 and resp.json()["display_name"] == "Lead Who Flies"
    assert client.post("/v1/crew", json={"member": str(member.id)}, headers=h).status_code == 409


def test_isolation_skills_and_crew(client, db, auth_headers):
    org_a, _, h_a = _ctx(db, auth_headers)
    org_b = make_org(db)
    skill_b = make_skill(db, org_b, "Secret Skill")
    crew_b = make_crew(db, org_b, name="Org B Crew", skills={skill_b: 3})
    assert client.get("/v1/skills", headers=h_a).json() == []
    assert client.get("/v1/crew", headers=h_a).json() == []
    assert client.get(f"/v1/crew/{crew_b.id}", headers=h_a).status_code == 404
    assert client.get(f"/v1/crew/{crew_b.membership.user.email}", headers=h_a).status_code == 404
    assert client.patch(f"/v1/skills/{skill_b.id}", json={"active": False}, headers=h_a).status_code == 404
    assert client.patch(f"/v1/crew/{crew_b.id}", json={"active": False}, headers=h_a).status_code == 404
    assert client.post(f"/v1/crew/{crew_b.id}/skills/{skill_b.id}/verify", json={}, headers=h_a).status_code == 404


# ------------------------------------------------------------------ declare / verify (3.2)


def test_self_declared_skill_is_unverified(client, db, auth_headers):
    org = make_org(db)
    make_skill(db, org, "Geology")
    bob = make_crew(db, org, name="Bob")
    resp = client.put("/v1/crew/me/skills/geology", json={"level": 4}, headers=auth_headers(bob.membership, org))
    skill = resp.json()["skills"][0]
    assert skill["status"] == "UNVERIFIED" and skill["claimed_level"] == 4 and skill["verified_level"] is None


def test_crew_cannot_edit_another_profile(client, db, auth_headers):
    org = make_org(db)
    make_skill(db, org, "Geology")
    bob, alice = make_crew(db, org, name="Bob"), make_crew(db, org, name="Alice")
    resp = client.put(
        f"/v1/crew/{alice.id}/skills/geology", json={"level": 5}, headers=auth_headers(bob.membership, org)
    )
    assert resp.status_code == 404


def test_lead_verifies_with_adjusted_level(client, db, auth_headers):
    org = make_org(db)
    geo = make_skill(db, org, "Geology")
    bob = make_crew(db, org, name="Bob")
    client.put("/v1/crew/me/skills/geology", json={"level": 4}, headers=auth_headers(bob.membership, org))
    lead = make_member(db, org, "LEAD")
    resp = client.post(f"/v1/crew/{bob.id}/skills/{geo.id}/verify", json={"level": 3}, headers=auth_headers(lead, org))
    skill = resp.json()["skills"][0]
    assert skill["status"] == "VERIFIED" and skill["verified_level"] == 3 and skill["verified_at"]


def test_cannot_verify_own_skills(client, db, auth_headers):
    org = make_org(db)
    make_skill(db, org, "Piloting")
    lead_member = make_member(db, org, "LEAD")
    make_crew(db, org, member=lead_member, name="Flying Lead")
    h = auth_headers(lead_member, org)
    client.put("/v1/crew/me/skills/piloting", json={"level": 5}, headers=h)
    resp = client.post("/v1/crew/me/skills/piloting/verify", json={}, headers=h)
    assert resp.status_code == 403 and resp.json()["code"] == "crew_skill.self_verification"


def test_editing_verified_skill_returns_it_to_unverified_but_keeps_verified_level(client, db, auth_headers):
    org = make_org(db)
    pil = make_skill(db, org, "Piloting")
    alice = make_crew(db, org, name="Alice", skills={pil: 3})
    resp = client.put("/v1/crew/me/skills/piloting", json={"level": 5}, headers=auth_headers(alice.membership, org))
    skill = resp.json()["skills"][0]
    assert skill["status"] == "UNVERIFIED" and skill["claimed_level"] == 5 and skill["verified_level"] == 3


def test_crew_cannot_verify(client, db, auth_headers):
    org = make_org(db)
    geo = make_skill(db, org, "Geology")
    bob, alice = make_crew(db, org, name="Bob", skills={geo: 2}), make_crew(db, org, name="Alice")
    resp = client.post(f"/v1/crew/{bob.id}/skills/geology/verify", json={}, headers=auth_headers(alice.membership, org))
    assert resp.status_code == 403


def test_removing_a_skill(client, db, auth_headers):
    org = make_org(db)
    geo = make_skill(db, org, "Geology")
    bob = make_crew(db, org, name="Bob", skills={geo: 2})
    resp = client.delete("/v1/crew/me/skills/geology", headers=auth_headers(bob.membership, org))
    assert resp.json()["skills"] == []


def test_invalid_level_rejected(client, db, auth_headers):
    org = make_org(db)
    make_skill(db, org, "Geology")
    bob = make_crew(db, org, name="Bob")
    h = auth_headers(bob.membership, org)
    assert client.put("/v1/crew/me/skills/geology", json={"level": 6}, headers=h).status_code == 422
    assert client.put("/v1/crew/me/skills/geology", json={"level": 0}, headers=h).status_code == 422


# ------------------------------------------------------------------ unavailability (3.3)

WIN = {"starts_at": "2027-03-01T00:00:00Z", "ends_at": "2027-03-08T00:00:00Z"}


def test_lead_sees_privacy_view_director_sees_full(client, db, auth_headers):
    org = make_org(db)
    bob = make_crew(db, org, name="Bob")
    hb = auth_headers(bob.membership, org)
    client.post("/v1/crew/me/unavailability", json={**WIN, "category": "MEDICAL", "note": "knee surgery"}, headers=hb)
    client.post(
        "/v1/crew/me/unavailability",
        json={"starts_at": "2027-04-01T00:00:00Z", "ends_at": "2027-04-03T00:00:00Z", "category": "LEAVE"},
        headers=hb,
    )
    lead_view = client.get(f"/v1/crew/{bob.id}/unavailability", headers=auth_headers(make_member(db, org, "LEAD"), org))
    labels = [(w["label"], w["category"], w["note"]) for w in lead_view.json()]
    assert labels == [("Unavailable", None, None), ("LEAVE", None, None)]
    dir_view = client.get(
        f"/v1/crew/{bob.id}/unavailability", headers=auth_headers(make_member(db, org, "DIRECTOR"), org)
    )
    assert dir_view.json()[0]["category"] == "MEDICAL" and dir_view.json()[0]["note"] == "knee surgery"


def test_invalid_window_rejected(client, db, auth_headers):
    org = make_org(db)
    bob = make_crew(db, org, name="Bob")
    resp = client.post(
        "/v1/crew/me/unavailability",
        json={"starts_at": WIN["ends_at"], "ends_at": WIN["starts_at"], "category": "LEAVE"},
        headers=auth_headers(bob.membership, org),
    )
    assert resp.status_code == 422


def test_naive_datetimes_rejected(client, db, auth_headers):
    org = make_org(db)
    bob = make_crew(db, org, name="Bob")
    resp = client.post(
        "/v1/crew/me/unavailability",
        json={"starts_at": "2027-03-01T00:00:00", "ends_at": "2027-03-02T00:00:00", "category": "LEAVE"},
        headers=auth_headers(bob.membership, org),
    )
    assert resp.status_code == 422


def test_director_records_for_crew_lead_cannot(client, db, auth_headers):
    org = make_org(db)
    bob = make_crew(db, org, name="Bob")
    body = {**WIN, "category": "TRAINING"}
    lead_h = auth_headers(make_member(db, org, "LEAD"), org)
    assert client.post(f"/v1/crew/{bob.id}/unavailability", json=body, headers=lead_h).status_code == 403
    dir_h = auth_headers(make_member(db, org, "DIRECTOR"), org)
    assert client.post(f"/v1/crew/{bob.id}/unavailability", json=body, headers=dir_h).status_code == 201


def test_remove_window(client, db, auth_headers):
    org = make_org(db)
    bob = make_crew(db, org, name="Bob")
    h = auth_headers(bob.membership, org)
    wid = client.post("/v1/crew/me/unavailability", json={**WIN, "category": "LEAVE"}, headers=h).json()["id"]
    assert client.delete(f"/v1/crew/me/unavailability/{wid}", headers=h).status_code == 204
    assert client.get("/v1/crew/me/unavailability", headers=h).json() == []
