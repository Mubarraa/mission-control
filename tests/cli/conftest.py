import io
import json
import os
import stat
from collections.abc import Callable

import httpx
import pytest

from mc import client, session
from mc.main import run


class Recorder:
    """httpx MockTransport that records requests and answers from a route table."""

    def __init__(self, routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response] | tuple[int, object]]):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        handler = self.routes.get(key)
        if handler is None:
            return httpx.Response(404, json={"detail": f"no route {key}", "code": "not_found"})
        if callable(handler):
            return handler(request)
        status, body = handler
        return httpx.Response(status, json=body)

    def body(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].content or b"null")


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_CONFIG_DIR", str(tmp_path / "mc"))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.delenv("MC_API_URL", raising=False)
    monkeypatch.delenv("MC_PASSWORD", raising=False)
    return tmp_path


@pytest.fixture
def mock_api(cli_env, monkeypatch):
    def install(routes) -> Recorder:
        rec = Recorder(routes)
        monkeypatch.setattr(
            client,
            "HTTP_FACTORY",
            lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(rec)),
        )
        return rec

    return install


@pytest.fixture
def logged_in(cli_env):
    session.save(
        {
            "api_url": "http://api.test",
            "token": "tok",
            "org": "artemis",
            "role": "LEAD",
            "email": "lead@x.test",
            "expires_at": "2099-01-01T00:00:00Z",
        }
    )


@pytest.fixture
def mc(capsys, monkeypatch):
    """mc(args, stdin="") -> (exit_code, stdout, stderr)"""

    def invoke(*args: str, stdin: str = ""):
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        code = run(list(args))
        out = capsys.readouterr()
        return code, out.out, out.err

    return invoke


def file_mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)
