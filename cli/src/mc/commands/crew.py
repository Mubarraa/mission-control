import typer

from mc.client import seg
from mc.commands.common import api, resolve_prefix
from mc.output import console, day, emit, next_steps, ok, parse_when, short, styled, table

crew_app = typer.Typer(help="The crew roster: profiles, skills, availability, verification.", no_args_is_help=True)
profile_app = typer.Typer(help="Your own crew profile, skills and availability.", no_args_is_help=True)
skill_app = typer.Typer(help="Declare or remove your skills.", no_args_is_help=True)
unavail_app = typer.Typer(help="Record when you are unavailable.", no_args_is_help=True)
profile_app.add_typer(skill_app, name="skill")
profile_app.add_typer(unavail_app, name="unavailable")


def render_profile(c: dict, windows: list[dict] | None = None) -> None:
    status = "" if c["active"] else "  [red](inactive)[/red]"
    console.print(f"[bold]{c['display_name']}[/bold] <{c['email']}>{status}")
    if c.get("bio"):
        console.print(f"  [dim]{c['bio']}[/dim]")
    if c["skills"]:
        t = table("Skill", "Level", "Status", "Cert expires")
        for s in c["skills"]:
            if s["status"] == "VERIFIED":
                level = str(s["verified_level"])
            else:
                level = f"{s['claimed_level']} claimed" + (
                    f" ({s['verified_level']} verified)" if s["verified_level"] else ""
                )
            t.add_row(
                s["skill"],
                level,
                styled(s["status"]),
                day(s["cert_expires_on"]) if s["cert_expires_on"] else "-",
            )
        console.print(t)
    else:
        console.print("  [dim]No skills declared.[/dim]")
    if windows is not None:
        render_windows(windows)


def render_windows(windows: list[dict]) -> None:
    if not windows:
        console.print("  [dim]No unavailability recorded.[/dim]")
        return
    t = table("ID", "From", "To", "Type", "Note")
    for w in windows:
        t.add_row(short(w["id"]), day(w["starts_at"]), day(w["ends_at"]), w["label"], w.get("note") or "")
    console.print(t)


# ---------------------------------------------------------------- roster (Directors / Leads)


@crew_app.command("list")
def list_crew(skill: str = typer.Option(None, "--skill", help="Only crew who have this skill")):
    """List crew profiles."""
    rows = api().get("/crew", skill=skill)

    def render():
        t = table("Name", "Email", "Skills (verified)")
        for c in rows:
            skills = ", ".join(f"{s['skill']} {s['verified_level']}" for s in c["skills"] if s["verified_level"])
            pending = sum(1 for s in c["skills"] if s["status"] == "UNVERIFIED")
            t.add_row(
                c["display_name"],
                c["email"],
                skills + (f"  [yellow]+{pending} unverified[/yellow]" if pending else ""),
            )
        console.print(t)

    emit(rows, render)


@crew_app.command("show")
def show(crew: str = typer.Argument(..., help="Name, email or 'me'")):
    """Show a crew member's skills and availability."""
    a = api()
    c = a.get(f"/crew/{seg(crew)}")
    windows = a.get(f"/crew/{c['id']}/unavailability")
    emit({**c, "unavailability": windows}, lambda: render_profile(c, windows))


@crew_app.command("availability")
def availability(crew: str = typer.Argument(...)):
    """Show when a crew member is unavailable (private details are hidden from Leads)."""
    windows = api().get(f"/crew/{seg(crew)}/unavailability")
    emit(windows, lambda: render_windows(windows))


@crew_app.command("create")
def create(member: str = typer.Argument(..., help="Member email"), name: str = typer.Option(None, "--name")):
    """Create a crew profile for an existing member (Directors)."""
    c = api().post("/crew", {"member": member, "display_name": name})
    emit(
        c,
        lambda: (
            ok(f"Crew profile created for {c['display_name']}"),
            next_steps("They can now declare skills: mc profile skill set <skill> <level>"),
        ),
    )


@crew_app.command("verify")
def verify(
    crew: str = typer.Argument(..., help="Crew name or email"),
    skill: str = typer.Argument(..., help="Skill name"),
    level: int = typer.Option(None, "--level", min=1, max=5, help="Adjust the level while verifying"),
    cert_expires: str = typer.Option(None, "--cert-expires", help="Certification expiry, YYYY-MM-DD"),
):
    """Verify a crew member's claimed skill (Directors/Leads; never your own)."""
    body = {"level": level, "cert_expires_on": parse_when(cert_expires)[:10] if cert_expires else None}
    c = api().post(f"/crew/{seg(crew)}/skills/{seg(skill)}/verify", body)
    s = next(x for x in c["skills"] if x["skill"].lower() == skill.lower())
    emit(c, lambda: ok(f"Verified {c['display_name']}'s {s['skill']} at level {s['verified_level']}"))


# ---------------------------------------------------------------- self-service


@profile_app.command("show")
def profile_show():
    """Show your profile, skills and availability."""
    show("me")


@skill_app.command("set")
def skill_set(skill: str = typer.Argument(...), level: int = typer.Argument(..., min=1, max=5)):
    """Declare a skill or change its level (it then needs verification)."""
    c = api().put(f"/crew/me/skills/{seg(skill)}", {"level": level})
    emit(
        c,
        lambda: (
            ok(f"{skill} level {level} recorded - awaiting verification by a Director or Lead."),
            render_profile(c),
        ),
    )


@skill_app.command("remove")
def skill_remove(skill: str = typer.Argument(...)):
    """Remove a skill from your profile."""
    c = api().delete(f"/crew/me/skills/{seg(skill)}")
    emit(c, lambda: ok(f"Removed {skill}."))


@unavail_app.command("add")
def unavailable_add(
    start: str = typer.Argument(..., help="YYYY-MM-DD"),
    end: str = typer.Argument(..., help="YYYY-MM-DD (exclusive)"),
    category: str = typer.Option(..., "--category", "-c", help="LEAVE, TRAINING, MEDICAL or OTHER"),
    note: str = typer.Option(None, "--note", help="Private: only you and Directors see it"),
):
    """Record a period when you cannot be assigned."""
    w = api().post(
        "/crew/me/unavailability",
        {
            "starts_at": parse_when(start),
            "ends_at": parse_when(end),
            "category": category.upper(),
            "note": note,
        },
    )
    emit(w, lambda: ok(f"Unavailable {day(w['starts_at'])} to {day(w['ends_at'])} ({w['label']})"))


@unavail_app.command("list")
def unavailable_list():
    """List your unavailability windows."""
    windows = api().get("/crew/me/unavailability")
    emit(windows, lambda: render_windows(windows))


@unavail_app.command("remove")
def unavailable_remove(window_id: str = typer.Argument(..., help="Window id (short id is fine)")):
    """Remove an unavailability window."""
    a = api()
    w = resolve_prefix(a.get("/crew/me/unavailability"), window_id, "unavailability window")
    a.delete(f"/crew/me/unavailability/{w['id']}")
    emit({"removed": w["id"]}, lambda: ok("Removed."))
