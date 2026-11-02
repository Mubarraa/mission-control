"""Developer start-up banner: tells someone who just ran `make run` what to do in a second terminal.

Shown only when MC_BANNER_URL is set (the Makefile's `run` target sets it), so tests and production stay quiet.
"""

import os
import sys

from sqlalchemy import select

from mission_control.cli_hint import mc_command

B, D, G, Y, R = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[0m"


def _demo_seeded() -> bool | None:
    try:
        from mission_control.db import models as m
        from mission_control.db.session import get_engine

        with get_engine().connect() as conn:
            return (
                conn.execute(select(m.Organisation.id).where(m.Organisation.slug == "artemis-labs")).first() is not None
            )
    except Exception:  # noqa: BLE001 - the banner must never stop the server starting
        return None


def pad(mc: str, used: int = 0) -> str:
    """Align the comment column regardless of whether the command is `mc` or `uv run mc`."""
    return " " * max(2, 26 - len(mc) - used)


def print_banner() -> None:
    url = os.environ.get("MC_BANNER_URL")
    if not url:
        return
    seeded = _demo_seeded()
    mc = mc_command()
    lines = [
        "",
        f"{G}{B}Mission Control API is running{R} at {B}{url}{R}   {D}(interactive API docs: {url}/docs){R}",
        "",
        f"{B}Next, in a second terminal{R} (this one stays busy serving requests):",
    ]
    if seeded:
        lines += [
            f"  {mc} login --org artemis-labs --email priya@artemis.io   {D}# password: mission-control-demo{R}",
            f"  {mc} inbox{pad(mc)}# what needs your attention",
            f"  {mc} match ART-3{pad(mc, 6)}# crew suggestions for the seeded survey",
        ]
    elif seeded is False:
        lines += [f"  {Y}make seed{R}                       # load the demo organisations first, then log in"]
    else:
        lines += [f"  {Y}Database not reachable:{R} run `make up && make migrate && make seed`"]
    if mc != "mc":
        lines += [f"  make install-cli                {D}# optional: then just type `mc` instead of `uv run mc`{R}"]
    lines += [
        f"  {mc} guide{pad(mc)}{D}# step-by-step workflows, by role{R}",
        f"  {mc} --help{pad(mc, 1)}{D}# every command, grouped by workflow{R}",
        f"  make logins                     {D}# list every login (demo password: mission-control-demo){R}",
        f"  make demo                       {D}# narrated end-to-end walkthrough (about a minute){R}",
        "",
        f'{B}Tasks for each role:{R} README.md -> "Guide by role" (Director, Mission Lead, Crew Member)',
        f"{D}Stop the server with Ctrl+C.{R}",
        "",
    ]
    print("\n".join(lines), file=sys.stderr, flush=True)
