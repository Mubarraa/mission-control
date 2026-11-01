"""Task 6.1: session, errors -> exit codes, --json (httpx MockTransport, no server)."""

import json

import httpx

from mc import session
from mc.errors import EXIT_AUTH, EXIT_CONFLICT, EXIT_NOT_FOUND, EXIT_SERVER
from tests.cli.conftest import file_mode

ME = {
    "token": "secret-token",
    "expires_at": "2027-01-15T17:00:00Z",
    "role": "LEAD",
    "membership_id": "m1",
    "crew_id": None,
    "user": {"id": "u1", "email": "priya@artemis.io", "name": "Priya"},
    "org": {"id": "o1", "slug": "artemis", "name": "Artemis Labs"},
}


def test_login_saves_token_only_with_0600(mc, mock_api, cli_env):
    rec = mock_api({("POST", "/v1/auth/login"): (200, ME)})
    code, out, _ = mc(
        "login",
        "--org",
        "artemis",
        "--email",
        "priya@artemis.io",
        "--api",
        "http://api.test",
        stdin="hunter2\n",
    )
    assert code == 0
    assert "Logged in as priya@artemis.io (Mission Lead, Artemis Labs)" in out and "mc inbox" in out
    assert rec.body() == {"email": "priya@artemis.io", "password": "hunter2", "org": "artemis"}
    path = session.session_path()
    assert file_mode(path) == 0o600
    stored = json.loads(path.read_text())
    assert stored["token"] == "secret-token" and "hunter2" not in path.read_text()


def test_password_is_not_echoed(mc, mock_api):
    mock_api({("POST", "/v1/auth/login"): (200, ME)})
    _, out, _ = mc("login", "--org", "artemis", "--email", "p@x", "--api", "http://api.test", stdin="hunter2\n")
    assert "hunter2" not in out


def test_not_logged_in(mc, cli_env):
    code, _, err = mc("mission", "list")
    assert code == EXIT_AUTH and "mc login" in err


def _problem(status, detail, code="x", **extra):
    return (status, {"status": status, "detail": detail, "code": code, **extra})


def test_exit_codes_map_from_http_status(mc, mock_api, logged_in):
    for status, expected in [
        (401, EXIT_AUTH),
        (403, EXIT_AUTH),
        (404, EXIT_NOT_FOUND),
        (409, EXIT_CONFLICT),
        (422, EXIT_CONFLICT),
        (500, EXIT_SERVER),
    ]:
        mock_api({("GET", "/v1/missions/ART-1"): _problem(status, f"problem {status}")})
        code, out, err = mc("mission", "show", "ART-1")
        assert code == expected, status
        assert f"problem {status}" in err and "Traceback" not in err + out


def test_business_rule_error_is_one_readable_line(mc, mock_api, logged_in):
    mock_api(
        {
            ("GET", "/v1/missions/ART-1"): (200, {"revision": 3}),
            ("POST", "/v1/missions/ART-1/approve"): _problem(
                403,
                "You submitted ART-1; a different Director must approve or reject it.",
                "approval.self_approval",
            ),
        }
    )
    code, out, err = mc("mission", "approve", "ART-1")
    assert code == EXIT_AUTH and "different Director" in err


def test_illegal_transition_shows_allowed_actions(mc, mock_api, logged_in):
    mock_api(
        {
            ("POST", "/v1/missions/ART-1/start"): _problem(
                409, "Cannot start ART-1: it is DRAFT.", allowed_actions=["cancel", "submit"]
            )
        }
    )
    code, _, err = mc("mission", "start", "ART-1")
    assert code == EXIT_CONFLICT and "Allowed now: cancel, submit" in err


def test_api_unreachable(mc, cli_env, monkeypatch, logged_in):
    from mc import client

    def boom(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(
        client, "HTTP_FACTORY", lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(boom))
    )
    code, _, err = mc("inbox")
    assert code == EXIT_SERVER and "http://api.test" in err and "make run" in err


def test_json_flag_anywhere_prints_only_json(mc, mock_api, logged_in):
    rows = [
        {
            "code": "ART-1",
            "name": "M",
            "state": "DRAFT",
            "starts_at": "2027-03-01T00:00:00Z",
            "ends_at": "2027-03-21T00:00:00Z",
            "revision": 1,
            "owner": {"id": "x", "name": "Priya"},
            "id": "1",
        }
    ]
    mock_api({("GET", "/v1/missions"): (200, rows)})
    for args in (("mission", "list", "--json"), ("--json", "mission", "list")):
        code, out, _ = mc(*args)
        assert code == 0 and json.loads(out) == rows


def test_logout(mc, logged_in):
    code, out, _ = mc("logout")
    assert code == 0 and "Logged out" in out and session.load() == {}
