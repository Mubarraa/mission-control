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


# ------------------------------------------------------------------ self-guidance (task group 8)

import shlex  # noqa: E402

import click  # noqa: E402
import typer.main  # noqa: E402

from mc.guides import GUIDES  # noqa: E402
from mc.main import app as mc_app  # noqa: E402


def test_guide_lists_topics(mc, cli_env):
    code, out, _ = mc("guide")
    assert code == 0 and all(t in out for t in GUIDES) and "mc guide onboard" in out


def test_guide_renders_steps_by_role(mc, cli_env):
    code, out, _ = mc("guide", "onboard")
    assert code == 0 and "Director or Lead" in out and 'mc crew verify "Sam Rivera" geology' in out


def test_unknown_guide(mc, cli_env):
    code, _, err = mc("guide", "nope")
    assert code == EXIT_USAGE and "'nope' is not one of" in err


def test_every_guide_command_is_a_real_mc_command():
    root = typer.main.get_command(mc_app)
    for topic, g in GUIDES.items():
        for _, command, _ in g["steps"]:
            if not command:
                continue
            tokens = shlex.split(command)[1:]
            cmd, path = root, []
            while isinstance(cmd, click.Group) and tokens and tokens[0] in cmd.commands:
                path.append(tokens.pop(0))
                cmd = cmd.commands[path[-1]]
            assert not isinstance(cmd, click.Group), f"{topic}: '{command}' is not a full command"
            cmd.make_context(" ".join(path), tokens)  # raises if options/arguments don't parse


def test_bare_mc_when_logged_out(mc, cli_env):
    code, out, _ = mc()
    assert code == 0 and "not logged in" in out and "mc login --org <slug>" in out and "mc guide" in out


def test_bare_mc_when_logged_in(mc, logged_in):
    code, out, _ = mc()
    assert code == 0 and "lead@x.test" in out and "Mission Lead" in out and "mc inbox" in out


def test_cancel_declined_sends_nothing(mc, mock_api, logged_in):
    rec = mock_api({("GET", "/v1/missions/ART-12"): (200, MISSION)})
    code, _, _ = mc("mission", "cancel", "ART-12", stdin="n\n")
    assert code == 1 and [r.method for r in rec.requests] == ["GET"]


def test_cancel_with_yes_skips_prompt(mc, mock_api, logged_in):
    rec = mock_api(
        {
            ("GET", "/v1/missions/ART-12"): (200, MISSION),
            ("POST", "/v1/missions/ART-12/cancel"): (200, {**MISSION, "state": "CANCELLED"}),
        }
    )
    code, out, _ = mc("mission", "cancel", "ART-12", "--yes")
    assert code == 0 and rec.requests[-1].method == "POST" and "CANCELLED" in out


def test_release_asks_and_proceeds_on_yes(mc, mock_api, logged_in):
    rec = mock_api(
        {
            ("GET", "/v1/assignments"): (200, [ASSIGNMENT]),
            ("POST", f"/v1/assignments/{ASSIGNMENT['id']}/release"): (200, {**ASSIGNMENT, "state": "RELEASED"}),
        }
    )
    code, out, _ = mc("assignment", "release", "a1b2", stdin="y\n")
    assert code == 0 and "Release Bob from Geologist on ART-12?" in out and rec.requests[-1].method == "POST"


def test_inbox_lists_every_slot_with_progress(mc, mock_api, logged_in):
    inbox = {
        "role": "LEAD",
        "stale_offer_days": 3,
        "approvals": [],
        "offers": [],
        "notifications": [],
        "skills_awaiting_verification": [],
        "missions": [
            {
                "code": "ART-3",
                "name": "Lunar South Pole Survey",
                "state": "DRAFT",
                "starts_at": "2027-03-01T00:00:00Z",
                "accepted_total": 1,
                "positions_total": 3,
                "rejection": None,
                "exits": [],
                "ready_to_submit": False,
                "offers": [],
                "unfilled": [{"slot": "Geologist", "accepted": 0, "offered": 2, "headcount": 2}],
                "slots": [
                    {"slot": "Commander", "headcount": 1, "accepted": ["Alice Okafor"], "offered": [], "open": 0},
                    {
                        "slot": "Geologist",
                        "headcount": 2,
                        "accepted": [],
                        "open": 0,
                        "offered": [
                            {
                                "assignment_id": "fe430147-x",
                                "crew": "Bob Lindqvist",
                                "slot": "Geologist",
                                "age_days": 0.0,
                                "stale": False,
                            },
                            {
                                "assignment_id": "4aa83618-x",
                                "crew": "Dev Patel",
                                "slot": "Geologist",
                                "age_days": 4.0,
                                "stale": True,
                            },
                        ],
                    },
                ],
            }
        ],
    }
    mock_api({("GET", "/v1/inbox"): (200, inbox)})
    code, out, _ = mc("inbox")
    assert code == 0 and "1 of 3 accepted" in out
    assert "Commander  Alice Okafor ACCEPTED ✓" in out
    assert "Bob Lindqvist offered just now [fe430147]" in out and "Dev Patel offered 4d ago [4aa83618] ! stale" in out
    assert "waiting for 2 crew to accept - mc mission show ART-3" in out


def test_inbox_renders_fully_crewed_notification(mc, mock_api, logged_in):
    inbox = {
        "role": "LEAD",
        "stale_offer_days": 3,
        "approvals": [],
        "missions": [],
        "offers": [],
        "skills_awaiting_verification": [],
        "notifications": [
            {
                "id": "3f2a91c0-x",
                "kind": "mission.fully_crewed",
                "mission_id": "m",
                "created_at": "2027-01-15T07:00:00Z",
                "data": {"mission_code": "ART-3", "mission_name": "Survey", "positions": 5},
            }
        ],
    }
    mock_api({("GET", "/v1/inbox"): (200, inbox)})
    _, out, _ = mc("inbox")
    assert "ART-3 is fully crewed - all 5 positions accepted" in out and "mc mission submit ART-3" in out


def test_guide_rejects_unknown_topic_clearly(mc, cli_env):
    code, out, err = mc("guide", "Getting", "started")
    assert code == EXIT_USAGE and "Traceback" not in out + err
    assert "'Getting' is not one of" in err and "onboard" in err and "mc guide --help" in err
