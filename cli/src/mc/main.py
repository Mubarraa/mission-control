"""`mc` - the Mission Control command-line client.

Noun-verb commands, readable output by default, `--json` anywhere on the command line for scripting.
Every command talks to the HTTP API only.
"""

import sys

import click
import typer

from mc import session
from mc.commands import assignments, auth, crew, guide, inbox, match, missions, org
from mc.errors import EXIT_USAGE, CliError
from mc.output import ROLE_LABEL, console, err, localize, next_steps, state

app = typer.Typer(
    name="mc",
    help="Mission Control: plan missions, staff them with the right crew, and get them approved.\n\n"
    "Start with `mc login --org <slug>`, then `mc inbox`. Add --json to any command for machine output.",
    no_args_is_help=False,
    invoke_without_command=True,
    epilog="Step-by-step guides: [bold]mc guide[/bold] or README.md -> Common workflows "
    "(onboard crew, plan & staff a mission, "
    "approve, handle changes). Every command has --help.",
    rich_markup_mode="rich",
    add_completion=False,
    pretty_exceptions_enable=False,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    api_url: str = typer.Option(None, "--api", envvar="MC_API_URL", help="API base URL", show_default=False),
) -> None:
    if api_url:
        state.api = api_url
    if ctx.invoked_subcommand is None:
        getting_started()


def getting_started() -> None:
    """Bare `mc`: where am I, and what should I do next? Uses only the local session (no API call)."""
    data = session.load()
    console.print("[bold]Mission Control[/bold] - plan missions, staff them with the right crew, get them approved.")
    console.print()
    if data.get("token"):
        role = ROLE_LABEL.get(data.get("role"), data.get("role"))
        org = data.get("org_name", data.get("org"))
        until = str(data.get("expires_at", "-"))[:16]
        console.print(
            f"Logged in as [bold]{data.get('email')}[/bold] - {role} at {org} [dim](session until {until})[/dim]"
        )
        next_steps(
            "mc inbox            (what needs your attention)",
            "mc guide            (step-by-step workflows)",
            "mc --help           (every command)",
        )
    else:
        console.print("You are not logged in.")
        next_steps(
            "mc login --org <slug>",
            "mc guide            (step-by-step workflows)",
            "mc --help           (every command)",
        )


app.command(rich_help_panel="Session")(auth.login)
app.command(rich_help_panel="Session")(auth.logout)
app.command(rich_help_panel="Session")(auth.whoami)
app.command("guide", rich_help_panel="Session")(guide.guide)
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
        err.print(f"[red]Error:[/red] {localize(exc.message)}")
        if exc.hint:
            err.print(f"  [dim]{localize(exc.hint)}[/dim]")
        return exc.exit_code
    except click.exceptions.UsageError as exc:
        exc.show()
        return EXIT_USAGE
    except (click.exceptions.Abort, typer.Abort):
        err.print("Aborted - nothing was changed.")
        return 1
    except (click.exceptions.Exit, typer.Exit) as exc:
        return exc.exit_code


def entrypoint() -> None:
    sys.exit(run())
