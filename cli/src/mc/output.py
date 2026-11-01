"""Rendering helpers: readable Rich output by default, raw JSON with --json."""

import json
from datetime import UTC, datetime
from typing import Any

from rich.console import Console
from rich.table import Table


class State:
    json: bool = False
    api: str | None = None


state = State()
console = Console(highlight=False, soft_wrap=True)
err = Console(stderr=True, highlight=False, soft_wrap=True)

ROLE_LABEL = {"DIRECTOR": "Director", "LEAD": "Mission Lead", "CREW": "Crew Member"}
STATE_STYLE = {
    "DRAFT": "yellow",
    "PENDING_APPROVAL": "magenta",
    "APPROVED": "green",
    "ACTIVE": "bold cyan",
    "COMPLETED": "dim",
    "CANCELLED": "dim",
    "ABORTED": "red",
    "PROPOSED": "yellow",
    "ACCEPTED": "green",
    "DECLINED": "red",
    "WITHDRAWN": "red",
    "RELEASED": "dim",
    "VERIFIED": "green",
    "UNVERIFIED": "yellow",
}


def emit(data: Any, render) -> None:
    """Print `data` as JSON in --json mode, otherwise call `render()`."""
    if state.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        render()


def ok(message: str) -> None:
    if not state.json:
        console.print(f"[green]✓[/green] {message}")


def info(message: str) -> None:
    if not state.json:
        console.print(message)


def next_steps(*commands: str) -> None:
    commands = tuple(c for c in commands if c)
    if state.json or not commands:
        return
    console.print(f"  [dim]Next:[/dim] [bold]{commands[0]}[/bold]")
    for c in commands[1:]:
        console.print(f"        [bold]{c}[/bold]")


def styled(value: str | None) -> str:
    if not value:
        return "-"
    style = STATE_STYLE.get(value)
    return f"[{style}]{value}[/{style}]" if style else value


def table(*columns: str, title: str | None = None) -> Table:
    t = Table(title=title, title_justify="left", header_style="bold", pad_edge=False, box=None, show_edge=False)
    for c in columns:
        t.add_column(c)
    return t


def day(value: str | datetime | None) -> str:
    if value is None:
        return "-"
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(UTC).strftime("%Y-%m-%d")


def window(start, end) -> str:
    return f"{day(start)} -> {day(end)}"


def short(value: str | None) -> str:
    return str(value)[:8] if value else "-"


def age(value: str | datetime, now: datetime | None = None) -> str:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    seconds = ((now or datetime.now(UTC)) - dt).total_seconds()
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def parse_when(value: str) -> str:
    """Accept YYYY-MM-DD (00:00 UTC) or a full ISO-8601 timestamp; return ISO with timezone."""
    from mc.errors import CliError

    text = value.strip()
    try:
        if len(text) == 10:
            return datetime.fromisoformat(text).replace(tzinfo=UTC).isoformat()
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()
    except ValueError as exc:
        raise CliError(f"'{value}' is not a date. Use YYYY-MM-DD or an ISO-8601 timestamp.") from exc
