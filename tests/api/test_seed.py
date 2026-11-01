from sqlalchemy import func, select

from mission_control.db import models as m
from mission_control.seed import DEMO_PASSWORD, seed


def test_seed_is_rerunnable_and_match_shows_designed_scenarios(client, db):
    seed(db)
    assert seed(db) == []  # second run is a no-op
    assert (
        db.scalar(
            select(func.count())
            .select_from(m.Organisation)
            .where(m.Organisation.slug.in_(["artemis-labs", "orion-dynamics"]))
        )
        == 2
    )

    login = client.post(
        "/v1/auth/login", json={"email": "priya@artemis.io", "password": DEMO_PASSWORD, "org": "artemis-labs"}
    )
    h = {"Authorization": f"Bearer {login.json()['token']}"}
    body = client.get("/v1/missions/ART-3/match", headers=h).json()
    picks = {p["label"]: (p["suggestion"] or {}).get("name") for p in body["positions"]}
    assert picks["Commander"] == "Alice Okafor"  # greedy trap: Alice is the only free pilot
    assert picks["Geologist #1"] == "Bob Lindqvist"
    assert picks["Geologist #2"] is None  # Dev's claim is unverified, Hana is on leave
    assert picks["EVA Specialist"] == "Ivan Petrov"  # Carol's cert expires mid-mission
    assert picks["Flight Surgeon"] == "Gabe Ito"  # right-sizing beats the level-5 expert
    gap = next(p for p in body["positions"] if p["label"] == "Geologist #2")
    assert gap["unfilled_reasons"][0]["name"] == "Dev Patel"  # closest: verifying would qualify


def test_logins_lists_everyone_and_marks_demo_passwords(db, capsys):
    from mission_control.seed import logins, print_logins
    from tests.factories import make_member

    seed(db)
    org = db.scalar(select(m.Organisation).where(m.Organisation.slug == "artemis-labs"))
    make_member(db, org, "CREW", email="sam@artemis.io", name="Sam Rivera")  # added later, own password
    rows = {r["email"]: r for r in logins(db)}
    assert rows["priya@artemis.io"]["demo_password"] and rows["priya@artemis.io"]["role"] == "LEAD"
    assert rows["sam@artemis.io"]["demo_password"] is False
    assert {"carol@artemis.io", "kai@orion.space", "oskar@orion.space"} <= set(rows)
    print_logins(db)
    out = capsys.readouterr().out
    assert DEMO_PASSWORD in out and "sam@artemis.io" in out and "own" in out
