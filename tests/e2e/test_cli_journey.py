"""End-to-end: the primary workflow driven entirely through `mc`, against the real API app and Postgres.

The CLI's HTTP client is pointed at the in-process FastAPI app (same routes, auth, services and database
as production), so this exercises CLI -> HTTP -> API -> Postgres with no mocks.
"""

import json

import pytest
from fastapi.testclient import TestClient

from mc import client
from mc.errors import EXIT_AUTH, EXIT_NOT_FOUND
from mission_control.seed import DEMO_PASSWORD, seed


@pytest.fixture
def live(app, db, cli_env, monkeypatch):
    seed(db)
    http = TestClient(app)
    monkeypatch.setattr(client, "HTTP_FACTORY", lambda base: http)
    monkeypatch.setenv("MC_PASSWORD", DEMO_PASSWORD)


def as_(mc, email, org="artemis-labs"):
    code, out, err = mc("login", "--org", org, "--email", email, "--api", "http://testserver")
    assert code == 0, err


def ok_json(mc, *args):
    code, out, err = mc(*args, "--json")
    assert code == 0, err
    return json.loads(out)


def test_full_mission_journey_through_the_cli(live, mc):
    # Lead plans the mission.
    as_(mc, "priya@artemis.io")
    mission = ok_json(mc, "mission", "create", "Far Side Relay", "--start", "2027-04-05", "--end", "2027-04-25")
    code = mission["code"]
    ok_json(mc, "mission", "slot", "add", code, "--role", "Commander", "--skill", "piloting:4")
    ok_json(mc, "mission", "slot", "add", code, "--role", "Geologist", "--skill", "geology:3")

    # Matcher suggests a crew; the table is readable; the lead applies it.
    rc, table, _ = mc("match", code)
    assert rc == 0 and "Alice Okafor" in table and "Bob Lindqvist" in table and "--apply" in table
    applied = ok_json(mc, "match", code, "--apply")
    assert {a["crew_name"] for a in applied["applied"]} == {"Alice Okafor", "Bob Lindqvist"}

    # Crew accept from their inboxes.
    for email in ("alice@artemis.io", "bob@artemis.io"):
        as_(mc, email)
        offer = ok_json(mc, "inbox")["offers"][0]
        rc, out, err = mc("assignment", "accept", offer["assignment_id"][:8])
        assert rc == 0 and "Accepted" in out, err

    # Lead submits, and cannot approve their own mission.
    as_(mc, "priya@artemis.io")
    assert ok_json(mc, "mission", "submit", code)["state"] == "PENDING_APPROVAL"
    rc, _, err = mc("mission", "approve", code)
    assert rc == EXIT_AUTH and "Director" in err

    # A Director approves.
    as_(mc, "amara@artemis.io")
    assert any(r["code"] == code for r in ok_json(mc, "inbox")["approvals"])
    rc, out, _ = mc("mission", "approve", code)
    assert rc == 0 and "APPROVED" in out
    assert ok_json(mc, "mission", "show", code)["state"] == "APPROVED"


def test_cross_tenant_lookup_is_not_found(live, mc):
    as_(mc, "oskar@orion.space", org="orion-dynamics")
    rc, _, err = mc("mission", "show", "ART-3")
    assert rc == EXIT_NOT_FOUND and "not found" in err.lower()
    assert ok_json(mc, "crew", "list") == [] or all(
        c["email"].endswith("@orion.space") for c in ok_json(mc, "crew", "list")
    )


def test_withdrawal_notifies_lead_end_to_end(live, mc):
    as_(mc, "priya@artemis.io")
    code = ok_json(mc, "mission", "create", "Short Hop", "--start", "2027-07-01", "--end", "2027-07-05")["code"]
    ok_json(mc, "mission", "slot", "add", code, "--role", "Geologist", "--skill", "geology:3")
    ok_json(mc, "match", code, "--apply")
    as_(mc, "bob@artemis.io")
    offer = ok_json(mc, "inbox")["offers"][0]["assignment_id"]
    mc("assignment", "accept", offer[:8])
    rc, out, _ = mc("assignment", "withdraw", offer[:8], "--reason", "Knee injury")
    assert rc == 0 and "notified" in out
    as_(mc, "priya@artemis.io")
    rc, out, _ = mc("inbox")
    assert "Bob Lindqvist withdrew from Geologist" in out and 'Reason: "Knee injury"' in out
