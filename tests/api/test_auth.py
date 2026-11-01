from datetime import timedelta

import jwt

from mission_control.config import get_settings
from tests.factories import PASSWORD, make_member, make_org


def test_login_returns_org_scoped_token(client, db):
    org = make_org(db, slug="artemis")
    lead = make_member(db, org, "LEAD", email="Priya@Artemis.io")
    resp = client.post("/v1/auth/login", json={"email": "priya@artemis.io", "password": PASSWORD, "org": "artemis"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "LEAD" and body["org"]["slug"] == "artemis"
    claims = jwt.decode(
        body["token"],
        get_settings().jwt_secret,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["org"] == str(org.id) and claims["sub"] == str(lead.id)


def test_wrong_password_and_non_member_org_give_identical_errors(client, db):
    org_a = make_org(db, slug="org-a")
    make_org(db, slug="org-b")
    member = make_member(db, org_a, "CREW")
    bad_pw = client.post("/v1/auth/login", json={"email": member.user.email, "password": "nope", "org": "org-a"})
    no_member = client.post("/v1/auth/login", json={"email": member.user.email, "password": PASSWORD, "org": "org-b"})
    no_user = client.post("/v1/auth/login", json={"email": "ghost@x.test", "password": PASSWORD, "org": "org-a"})
    assert bad_pw.status_code == no_member.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_member.json() == no_user.json()
    assert bad_pw.headers["content-type"].startswith("application/problem+json")


def test_me_requires_token(client):
    resp = client.get("/v1/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "auth.unauthenticated"


def test_tampered_token_rejected(client, db, auth_headers):
    org = make_org(db)
    headers = auth_headers(make_member(db, org, "CREW"), org)
    tampered = headers["Authorization"][:-3] + "abc"
    assert client.get("/v1/me", headers={"Authorization": tampered}).status_code == 401


def test_expired_token_rejected(client, db, clock, auth_headers):
    org = make_org(db)
    headers = auth_headers(make_member(db, org, "CREW"), org)
    assert client.get("/v1/me", headers=headers).status_code == 200
    clock.set(clock.now() + timedelta(minutes=get_settings().token_ttl_minutes + 1))
    assert client.get("/v1/me", headers=headers).status_code == 401


def test_deactivated_membership_cannot_login_or_use_existing_token(client, db, auth_headers):
    org = make_org(db)
    member = make_member(db, org, "CREW")
    headers = auth_headers(member, org)
    member.active = False
    db.flush()
    assert client.get("/v1/me", headers=headers).status_code == 401
    resp = client.post("/v1/auth/login", json={"email": member.user.email, "password": PASSWORD, "org": org.slug})
    assert resp.status_code == 401


def test_same_user_different_role_per_org(client, db, auth_headers):
    org_a, org_b = make_org(db), make_org(db)
    lead = make_member(db, org_a, "LEAD", email="dual@x.test")
    crew = make_member(db, org_b, "CREW", email="dual@x.test")
    assert client.get("/v1/me", headers=auth_headers(lead, org_a)).json()["role"] == "LEAD"
    assert client.get("/v1/me", headers=auth_headers(crew, org_b)).json()["role"] == "CREW"
