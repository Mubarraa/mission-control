"""`mc` - the Mission Control command-line client.

Noun-verb commands, readable output by default, `--json` anywhere on the command line for scripting.
Every command talks to the HTTP API only.
"""

import sys

import click
import typer

from mc.commands import assignments, auth, crew, inbox, match, missions, org
from mc.errors import EXIT_USAGE, CliError
from mc.output import err, state

app = typer.Typer(
    name="mc",
    help="Mission Control: plan missions, staff them with the right crew, and get them approved.\n\n"
    "Start with `mc login --org <slug>`, then `mc inbox`. Add --json to any command for machine output.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
    pretty_exceptions_enable=False,
)


@app.callback()
def main(
    api_url: str = typer.Option(None, "--api", envvar="MC_API_URL", help="API base URL", show_default=False),
) -> None:
    if api_url:
        state.api = api_url


app.command(rich_help_panel="Session")(auth.login)
app.command(rich_help_panel="Session")(auth.logout)
app.command(rich_help_panel="Session")(auth.whoami)
app.add_typer(inbox.app, name="inbox", rich_help_panel="Daily work")
app.command("match", rich_help_panel="Daily work")(match.match)
app.add_typer(missions.app, name="mission", rich_help_panel="Daily work")
app.add_typer(assignments.app, name="assignment", rich_help_panel="Daily work")
app.add_typer(crew.profile_app, name="profile", rich_help_panel="Crew")
app.add_typer(crew.crew_app, name="crew", rich_help_panel="Crew")
app.add_typer(org.skill_app, name="skill", rich_help_panel="Organisation")
app.add_typer(org.member_app, name="member", rich_help_panel="Organisation")
app.add_typer(org.org_app, name="org", rich_help_panel="Organisation")


def run(argv: list[str] | None = None) -> int:
    """Entry point with consistent error handling and exit codes. Returns the exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    state.json = "--json" in args
    args = [a for a in args if a != "--json"]
    state.api = None
    try:
        result = app(args, prog_name="mc", standalone_mode=False)
        return result if isinstance(result, int) else 0
    except CliError as exc:
        err.print(f"[red]Error:[/red] {exc.message}")
        if exc.hint:
            err.print(f"  [dim]{exc.hint}[/dim]")
        return exc.exit_code
    except click.exceptions.UsageError as exc:
        exc.show()
        return EXIT_USAGE
    except click.exceptions.Abort:
        err.print("Aborted.")
        return 1
    except click.exceptions.Exit as exc:
        return exc.exit_code


def entrypoint() -> None:
    sys.exit(run())
