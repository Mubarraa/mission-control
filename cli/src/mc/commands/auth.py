import os

import typer

from mc import client, session
from mc.commands.common import api
from mc.output import ROLE_LABEL, console, emit, next_steps, ok, state


def login(
    org: str = typer.Option(None, "--org", "-o", help="Organisation slug, e.g. artemis-labs"),
    email: str = typer.Option(None, "--email", "-e", help="Your email address"),
    api_url: str = typer.Option(None, "--api", help="API base URL (default http://localhost:8000)"),
) -> None:
    """Log in to an organisation. The password is prompted (hidden) or read from MC_PASSWORD."""
    org = org or typer.prompt("Organisation")
    email = email or typer.prompt("Email")
    password = os.environ.get("MC_PASSWORD") or typer.prompt("Password", hide_input=True)
    base = session.api_url(api_url or state.api)
    me = client.Api(base).post("/auth/login", {"email": email, "password": password, "org": org})
    session.save(
        {
            "api_url": base,
            "token": me["token"],
            "expires_at": me["expires_at"],
            "org": me["org"]["slug"],
            "org_name": me["org"]["name"],
            "email": me["user"]["email"],
            "name": me["user"]["name"],
            "role": me["role"],
        }
    )
    emit(
        {k: v for k, v in me.items() if k != "token"},
        lambda: (
            ok(f"Logged in as [bold]{me['user']['email']}[/bold] ({ROLE_LABEL[me['role']]}, {me['org']['name']})"),
            next_steps("mc inbox"),
        ),
    )


def logout() -> None:
    """Forget the stored session."""
    removed = session.clear()
    emit({"logged_out": removed}, lambda: ok("Logged out." if removed else "You were not logged in."))


def whoami() -> None:
    """Show who you are logged in as."""
    me = api().get("/me")
    data = session.load()

    def render():
        console.print(f"[bold]{me['user']['name']}[/bold] <{me['user']['email']}>")
        console.print(f"  {ROLE_LABEL[me['role']]} at {me['org']['name']} ({me['org']['slug']})")
        console.print(f"  Crew profile: {'yes' if me['crew_id'] else 'no'}")
        console.print(f"  API: {data.get('api_url')}   session expires {data.get('expires_at', '-')[:16]}")

    emit(me, render)
