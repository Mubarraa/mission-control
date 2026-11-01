import typer

from mc.client import seg
from mc.commands.common import api
from mc.errors import EXIT_NOT_FOUND, CliError
from mc.output import ROLE_LABEL, console, emit, next_steps, ok, table

org_app = typer.Typer(help="Organisation settings (Directors).", no_args_is_help=True)
member_app = typer.Typer(help="Members and roles (Directors).", no_args_is_help=True)
skill_app = typer.Typer(help="The organisation's skill taxonomy.", no_args_is_help=True)


@org_app.command("settings")
def settings(
    approvals: int = typer.Option(None, "--approvals", min=1, max=5, help="Approvals a mission needs"),
    recovery_days: int = typer.Option(None, "--recovery-days", min=0, help="Rest days after a mission"),
    stale_offer_days: int = typer.Option(None, "--stale-offer-days", min=1, help="Flag unanswered offers after"),
):
    """Show settings, or change them (Directors)."""
    a = api()
    changes = {
        "approvals_required": approvals,
        "recovery_buffer_days": recovery_days,
        "stale_offer_days": stale_offer_days,
    }
    changes = {k: v for k, v in changes.items() if v is not None}
    s = a.patch("/org/settings", changes) if changes else a.get("/org/settings")

    def render():
        if changes:
            ok("Settings updated.")
        console.print(f"[bold]{s['name']}[/bold] ({s['slug']})   mission codes {s['mission_prefix']}-N")
        console.print(f"  Approvals required:   {s['approvals_required']}")
        console.print(f"  Recovery buffer:      {s['recovery_buffer_days']} days")
        console.print(f"  Stale offer after:    {s['stale_offer_days']} days")

    emit(s, render)


@member_app.command("list")
def member_list():
    """List members and their roles."""
    rows = api().get("/members")

    def render():
        t = table("Name", "Email", "Role", "Active")
        for r in rows:
            t.add_row(r["name"], r["email"], ROLE_LABEL[r["role"]], "yes" if r["active"] else "[red]no[/red]")
        console.print(t)

    emit(rows, render)


@member_app.command("add")
def member_add(
    email: str = typer.Argument(...),
    name: str = typer.Option(..., "--name"),
    role: str = typer.Option(..., "--role", help="DIRECTOR, LEAD or CREW"),
    crew: bool = typer.Option(False, "--crew", help="Also create a crew profile"),
    password: str = typer.Option(None, "--password", help="Initial password (prompted if omitted)"),
):
    """Add a member with an initial password."""
    password = password or typer.prompt("Initial password", hide_input=True, confirmation_prompt=True)
    a = api()
    member = a.post("/members", {"email": email, "name": name, "role": role.upper(), "password": password})
    profile = a.post("/crew", {"member": member["email"]}) if crew else None
    emit(
        {"member": member, "crew": profile},
        lambda: (
            ok(f"Added {member['name']} as {ROLE_LABEL[member['role']]}" + (" with a crew profile" if profile else "")),
            next_steps(f"They log in with: mc login --org <slug> --email {member['email']}"),
        ),
    )


@member_app.command("deactivate")
def member_deactivate(email: str = typer.Argument(...)):
    """Deactivate a member (history is kept; they can no longer log in)."""
    a = api()
    member = next((m for m in a.get("/members") if m["email"].lower() == email.lower()), None)
    if member is None:
        raise CliError(f"No member with email {email}.", EXIT_NOT_FOUND)
    m = a.patch(f"/members/{member['id']}", {"active": False})
    emit(m, lambda: ok(f"Deactivated {m['name']}."))


@skill_app.command("list")
def skill_list():
    """List the organisation's skills."""
    rows = api().get("/skills")

    def render():
        t = table("Skill", "Category", "Description")
        for r in rows:
            t.add_row(r["name"], r["category"] or "-", r["description"] or "")
        console.print(t)

    emit(rows, render)


@skill_app.command("add")
def skill_add(
    name: str = typer.Argument(...),
    category: str = typer.Option(None, "--category", "-c"),
    description: str = typer.Option(None, "--description", "-d"),
):
    """Add a skill to the taxonomy (Directors)."""
    s = api().post("/skills", {"name": name, "category": category, "description": description})
    emit(s, lambda: ok(f"Added skill {s['name']}"))


@skill_app.command("deactivate")
def skill_deactivate(name: str = typer.Argument(...)):
    """Hide a skill from new requirements and profiles (Directors)."""
    s = api().patch(f"/skills/{seg(name)}", {"active": False})
    emit(s, lambda: ok(f"Deactivated skill {s['name']}"))
