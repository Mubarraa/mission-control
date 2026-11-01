"""Thin HTTP client for the Mission Control API. Maps problem+json errors to CLI errors and exit codes."""

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from mc import session
from mc.errors import EXIT_AUTH, EXIT_SERVER, CliError, exit_code_for

# Tests replace this to route requests to an in-process app or a MockTransport.
HTTP_FACTORY: Callable[[str], httpx.Client] = lambda base_url: httpx.Client(base_url=base_url, timeout=15.0)  # noqa: E731


def seg(value: str) -> str:
    """Encode a user-supplied path segment (names may contain spaces)."""
    return quote(str(value), safe="")


class Api:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url
        self.token = token
        self.http = HTTP_FACTORY(base_url)

    def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            resp = self.http.request(method, f"/v1{path}", json=json, params=params, headers=headers)
        except httpx.TransportError as exc:
            raise CliError(
                f"Cannot reach the Mission Control API at {self.base_url}.",
                EXIT_SERVER,
                hint="Is the server running? Start it with `make run`, or point mc elsewhere with --api / MC_API_URL.",
            ) from exc
        if resp.status_code >= 400:
            raise _error(resp)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any = None) -> Any:
        return self.request("POST", path, json=json)

    def patch(self, path: str, json: Any) -> Any:
        return self.request("PATCH", path, json=json)

    def put(self, path: str, json: Any) -> Any:
        return self.request("PUT", path, json=json)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)


def _error(resp: httpx.Response) -> CliError:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    detail = body.get("detail") or f"The API returned HTTP {resp.status_code}."
    hint = None
    if resp.status_code == 401:
        hint = "Run `mc login` to start a new session."
    if body.get("allowed_actions"):
        hint = "Allowed now: " + ", ".join(body["allowed_actions"])
    return CliError(detail, exit_code_for(resp.status_code), hint=hint, body=body)


def authed(api_override: str | None = None) -> Api:
    data = session.load()
    if not data.get("token"):
        raise CliError("You are not logged in.", EXIT_AUTH, hint="Run `mc login --org <slug>` first.")
    return Api(session.api_url(api_override), data["token"])
