import typer

from mc.commands.common import api, confirm, require_reason, resolve_assignment
from mc.output import console, emit, next_steps, ok, short, styled, table, window

app = typer.Typer(help="Respond to offers, withdraw, or release crew.", no_args_is_help=True)


@app.command("list")
def list_assignments(
    mission: str = typer.Option(None, "--mission", "-m", help="Only this mission"),
    state: str = typer.Option(None, "--state", "-s", help="e.g. PROPOSED, ACCEPTED"),
):
    """Your assignments (crew), or assignments across missions (Directors/Leads)."""
    rows = api().get("/assignments", mission=mission, state=state)

    def render():
        if not rows:
            console.print("No assignments.")
            return
        t = table("ID", "Mission", "Slot", "Crew", "Window", "State")
        for r in rows:
            t.add_row(
                short(r["id"]),
                r["mission_code"],
                r["slot"],
                r["crew_name"],
                window(r["starts_at"], r["ends_at"]),
                styled(r["state"]),
            )
        console.print(t)
        pending = next((r for r in rows if r["state"] == "PROPOSED"), None)
        if pending:
            next_steps(
                f"mc assignment accept {short(pending['id'])}",
                f'mc assignment decline {short(pending["id"])} --reason "..."',
            )

    emit(rows, render)


@app.command("accept")
def accept(assignment: str = typer.Argument(..., help="Assignment id (short id is fine)")):
    """Accept an offer. Your time is then blocked for the mission plus the recovery period."""
    a = api()
    x = a.post(f"/assignments/{resolve_assignment(a, assignment)['id']}/accept")
    emit(x, lambda: ok(f"Accepted {x['slot']} on {x['mission_code']} ({window(x['starts_at'], x['ends_at'])})"))


@app.command("decline")
def decline(assignment: str = typer.Argument(...), reason: str = typer.Option(None, "--reason", "-r")):
    """Decline an offer (a reason is required)."""
    a = api()
    target = resolve_assignment(a, assignment)
    x = a.post(f"/assignments/{target['id']}/decline", {"reason": require_reason(reason, "declining")})
    emit(x, lambda: ok(f"Declined {x['slot']} on {x['mission_code']}. The mission lead will see your reason."))


@app.command("withdraw")
def withdraw(assignment: str = typer.Argument(...), reason: str = typer.Option(None, "--reason", "-r")):
    """Withdraw from an accepted assignment before the mission starts (a reason is required)."""
    a = api()
    target = resolve_assignment(a, assignment)
    previous = target["mission_state"]
    x = a.post(f"/assignments/{target['id']}/withdraw", {"reason": require_reason(reason, "withdrawing")})

    def render():
        ok(f"Withdrew from {x['slot']} on {x['mission_code']}. The mission lead has been notified.")
        if previous != x["mission_state"]:
            console.print(f"  {x['mission_code']} returned to {styled(x['mission_state'])} and needs re-approval.")

    emit(x, render)


@app.command("release")
def release(
    assignment: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation"),
):
    """Release a crew member from a mission you own (Directors/mission owner)."""
    a = api()
    target = resolve_assignment(a, assignment)
    confirm(
        f"Release {target['crew_name']} from {target['slot']} on {target['mission_code']}? Their position reopens.", yes
    )
    x = a.post(f"/assignments/{target['id']}/release")
    emit(
        x,
        lambda: (
            ok(f"Released {x['crew_name']} from {x['slot']} on {x['mission_code']}"),
            next_steps(f"mc match {x['mission_code']}") if x["mission_state"] == "DRAFT" else None,
        ),
    )
