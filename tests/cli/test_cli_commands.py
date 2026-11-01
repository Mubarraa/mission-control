"""Tasks 6.2/6.3: commands send the right requests and render useful output."""

import json

from mc.errors import EXIT_USAGE

MISSION = {
    "id": "m-1",
    "code": "ART-12",
    "name": "Lunar South Pole Survey",
    "state": "DRAFT",
    "revision": 1,
    "starts_at": "2027-03-01T00:00:00+00:00",
    "ends_at": "2027-03-21T00:00:00+00:00",
    "owner": {"id": "o", "name": "Priya"},
    "description": None,
    "submitted_by": None,
    "approvals": {"required": None, "received": 0, "approvers": []},
    "slots": [],
    "allowed_actions": ["cancel", "submit"],
}

ASSIGNMENT = {
    "id": "a1b2c3d4-0000-0000-0000-000000000000",
    "mission_code": "ART-12",
    "mission_name": "M",
    "mission_state": "APPROVED",
    "starts_at": "2027-03-01T00:00:00Z",
    "ends_at": "2027-03-21T00:00:00Z",
    "slot": "Geologist",
    "crew_id": "c",
    "crew_name": "Bob",
    "state": "ACCEPTED",
    "source": "MATCHER",
    "offered_at": "2027-01-01T00:00:00Z",
    "responded_at": None,
    "exit_reason": None,
}


def test_create_prints_code_and_next_hint(mc, mock_api, logged_in):
    rec = mock_api({("POST", "/v1/missions"): (201, MISSION)})
    code, out, _ = mc("mission", "create", "Lunar South Pole Survey", "--start", "2027-03-01", "--end", "2027-03-21")
    assert code == 0
    assert rec.body() == {
        "name": "Lunar South Pole Survey",
        "description": None,
        "starts_at": "2027-03-01T00:00:00+00:00",
        "ends_at": "2027-03-21T00:00:00+00:00",
    }
    assert "Created ART-12 (DRAFT)" in out and "Next: mc mission slot add ART-12" in out


def test_slot_add_parses_skill_specs(mc, mock_api, logged_in):
    rec = mock_api({("POST", "/v1/missions/ART-12/slots"): (201, MISSION)})
    code, _, _ = mc(
        "mission",
        "slot",
        "add",
        "ART-12",
        "--role",
        "EVA Lead",
        "--skill",
        "eva:3:cert",
        "--skill",
        "piloting:2",
        "--count",
        "2",
    )
    assert code == 0 and rec.body() == {
        "role_name": "EVA Lead",
        "headcount": 2,
        "requirements": [
            {"skill": "eva", "min_level": 3, "cert_required": True},
            {"skill": "piloting", "min_level": 2, "cert_required": False},
        ],
    }


def test_bad_skill_spec_is_usage_error(mc, mock_api, logged_in):
    mock_api({})
    code, _, err = mc("mission", "slot", "add", "ART-12", "--role", "X", "--skill", "eva")
    assert code == EXIT_USAGE and "SKILL:LEVEL" in err


def test_approve_sends_the_revision_reviewed(mc, mock_api, logged_in):
    rec = mock_api(
        {
            ("GET", "/v1/missions/ART-12"): (200, {**MISSION, "state": "PENDING_APPROVAL", "revision": 7}),
            ("POST", "/v1/missions/ART-12/approve"): (200, {**MISSION, "state": "APPROVED", "revision": 7}),
        }
    )
    code, out, _ = mc("mission", "approve", "ART-12")
    assert code == 0 and rec.body() == {"revision": 7} and "APPROVED" in out and "mc mission start ART-12" in out


def test_withdraw_prompts_for_reason_and_rejects_empty(mc, mock_api, logged_in):
    rec = mock_api(
        {
            ("GET", "/v1/assignments"): (200, [ASSIGNMENT]),
            ("POST", f"/v1/assignments/{ASSIGNMENT['id']}/withdraw"): (
                200,
                {**ASSIGNMENT, "state": "WITHDRAWN", "mission_state": "DRAFT"},
            ),
        }
    )
    code, out, err = mc("assignment", "withdraw", "a1b2", stdin="\n   \nknee injury\n")
    assert code == 0
    assert rec.body() == {"reason": "knee injury"}
    assert "lead has been notified" in out and "returned to DRAFT" in out


def test_ambiguous_short_id(mc, mock_api, logged_in):
    other = {**ASSIGNMENT, "id": "a1b2ffff-0000-0000-0000-000000000000"}
    mock_api({("GET", "/v1/assignments"): (200, [ASSIGNMENT, other])})
    code, _, err = mc("assignment", "accept", "a1b2")
    assert code == EXIT_USAGE and "type more characters" in err


MATCH = {
    "mission_code": "ART-12",
    "mission_name": "Lunar South Pole Survey",
    "revision": 4,
    "starts_at": "2027-03-01T00:00:00+00:00",
    "ends_at": "2027-03-21T00:00:00+00:00",
    "summary": {"open": 2, "filled": 1, "unfilled": 1},
    "positions": [
        {
            "slot_id": "s1",
            "role_name": "Commander",
            "index": 1,
            "label": "Commander",
            "excluded_total": 0,
            "suggestion": {
                "crew_id": "c1",
                "name": "Alice Okafor",
                "score": 0.91,
                "breakdown": {"fit": 1, "rightsizing": 1, "workload": 0.9, "experience": 0.6, "penalty": 0},
                "reason": "piloting 5 (needs 4+)",
            },
            "alternatives": [],
            "unfilled_reasons": [],
        },
        {
            "slot_id": "s2",
            "role_name": "Geologist",
            "index": 1,
            "label": "Geologist",
            "excluded_total": 1,
            "suggestion": None,
            "alternatives": [],
            "unfilled_reasons": [
                {
                    "crew_id": "c2",
                    "name": "Bob",
                    "tier": 0,
                    "rules": [
                        {"rule": "SKILL_MISSING", "detail": "no verified geology", "blocking": True},
                        {
                            "rule": "UNVERIFIED_WOULD_QUALIFY",
                            "detail": "claims geology 4 (unverified); verifying would qualify",
                            "blocking": False,
                        },
                    ],
                }
            ],
        },
    ],
}


def test_match_table_highlights_gaps_and_suggests_next(mc, mock_api, logged_in):
    mock_api({("GET", "/v1/missions/ART-12/match"): (200, MATCH)})
    code, out, _ = mc("match", "ART-12")
    assert code == 0
    assert "Alice Okafor" in out and "0.91" in out and "- unfilled -" in out
    assert "1 of 2 positions filled" in out
    assert "mc match ART-12 --apply" in out and 'mc match ART-12 --explain "Geologist"' in out


def test_match_explain_shows_why_not(mc, mock_api, logged_in):
    mock_api({("GET", "/v1/missions/ART-12/match"): (200, MATCH)})
    code, out, _ = mc("match", "ART-12", "--explain", "Geologist")
    assert "claims geology 4 (unverified); verifying would qualify" in out
    assert "mc crew verify" in out and "Alice Okafor 0.91" not in out  # filtered to the Geologist slot


def test_match_apply_offers_suggestions(mc, mock_api, logged_in):
    rec = mock_api(
        {
            ("GET", "/v1/missions/ART-12/match"): (200, MATCH),
            ("POST", "/v1/missions/ART-12/match/apply"): (
                200,
                {
                    "applied": [{**ASSIGNMENT, "crew_name": "Alice Okafor", "slot": "Commander"}],
                    "rejected": [],
                },
            ),
        }
    )
    code, out, _ = mc("match", "ART-12", "--apply")
    assert code == 0 and rec.body() == {"pairs": [{"slot_id": "s1", "crew_id": "c1"}]}
    assert "Offered Commander to Alice Okafor" in out


def test_inbox_renders_withdrawal_notification(mc, mock_api, logged_in):
    inbox = {
        "role": "LEAD",
        "stale_offer_days": 3,
        "approvals": [],
        "missions": [],
        "offers": [],
        "skills_awaiting_verification": [],
        "notifications": [
            {
                "id": "n1234567-x",
                "kind": "crew.withdrew",
                "mission_id": "m",
                "created_at": "2027-01-15T07:00:00Z",
                "data": {
                    "mission_code": "ART-12",
                    "crew": "Bob Lindqvist",
                    "slot": "Geologist #1",
                    "reason": "Knee injury",
                    "returned_to_draft": True,
                },
            }
        ],
    }
    mock_api({("GET", "/v1/inbox"): (200, inbox)})
    code, out, _ = mc("inbox")
    assert "ART-12 back to DRAFT - Bob Lindqvist withdrew from Geologist #1" in out
    assert 'Reason: "Knee injury"' in out and "mc inbox dismiss n1234567" in out


def test_inbox_json(mc, mock_api, logged_in):
    body = {
        "role": "CREW",
        "notifications": [],
        "approvals": [],
        "missions": [],
        "offers": [],
        "skills_awaiting_verification": [],
        "stale_offer_days": 3,
    }
    mock_api({("GET", "/v1/inbox"): (200, body)})
    code, out, _ = mc("inbox", "--json")
    assert code == 0 and json.loads(out) == body


def test_hints_default_to_uv_run(mc, mock_api, logged_in, monkeypatch):
    monkeypatch.delenv("MC_COMMAND")
    mock_api({("POST", "/v1/missions"): (201, MISSION)})
    _, out, _ = mc("mission", "create", "M", "--start", "2027-03-01", "--end", "2027-03-21")
    assert "Next: uv run mc mission slot add ART-12" in out


def test_error_hints_use_prefix_too(mc, cli_env, monkeypatch):
    monkeypatch.setenv("MC_COMMAND", "uv run mc")
    _, _, err = mc("mission", "list")  # not logged in
    assert "Run `uv run mc login --org <slug>` first." in err


def test_custom_prefix(mc, mock_api, logged_in, monkeypatch):
    monkeypatch.setenv("MC_COMMAND", "mcx")
    mock_api({("POST", "/v1/missions"): (201, MISSION)})
    _, out, _ = mc("mission", "create", "M", "--start", "2027-03-01", "--end", "2027-03-21")
    assert "Next: mcx mission slot add ART-12" in out and "uv run" not in out
