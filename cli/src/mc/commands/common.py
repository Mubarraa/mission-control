import typer

from mc import client
from mc.errors import EXIT_NOT_FOUND, EXIT_USAGE, CliError
from mc.output import state


def api() -> client.Api:
    return client.authed(state.api)


def require_reason(reason: str | None, what: str) -> str:
    """Prompt until a non-empty reason is given; never send an empty one."""
    while not (reason and reason.strip()):
        if reason is not None:
            typer.echo("A reason is required.", err=True)
        reason = typer.prompt(f"Reason for {what}", default="", show_default=False)
    return reason.strip()


def resolve_prefix(rows: list[dict], ref: str, what: str, key: str = "id") -> dict:
    """Let users type the short id shown in tables (first characters of a UUID)."""
    ref = ref.strip().lower()
    matches = [r for r in rows if str(r[key]).lower().startswith(ref)]
    if not matches:
        raise CliError(f"No {what} matches '{ref}'.", EXIT_NOT_FOUND)
    if len(matches) > 1:
        raise CliError(f"'{ref}' matches {len(matches)} {what}s; type more characters of the id.", EXIT_USAGE)
    return matches[0]


def resolve_assignment(a: client.Api, ref: str) -> dict:
    return resolve_prefix(a.get("/assignments"), ref, "assignment")


def confirm(message: str, yes: bool) -> None:
    """Ask before an irreversible action unless --yes was given. Declining raises Abort (no request sent)."""
    if not yes:
        typer.confirm(message, default=False, abort=True)
