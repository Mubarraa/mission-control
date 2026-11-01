import typer

from mc.client import seg
from mc.commands.common import api, confirm, require_reason
from mc.errors import CliError
from mc.output import console, emit, next_steps, ok, parse_when, short, styled, table, window

app = typer.Typer(help="Create, plan and move missions through their lifecycle.", no_args_is_help=True)
slot_app = typer.Typer(help="Crew slots: the roles a mission needs filled.", no_args_is_help=True)
app.add_typer(slot_app, name="slot")


# ---------------------------------------------------------------- rendering


def render_mission(mi: dict) -> None:
    console.print(
        f"[bold]{mi['code']}[/bold]  {mi['name']}   {window(mi['starts_at'], mi['ends_at'])}   "
        f"{styled(mi['state'])} r{mi['revision']}"
    )
    line = f"  Owner: {mi['owner']['name']}"
    if mi.get("submitted_by"):
        line += f"   Submitted by: {mi['submitted_by']['name']}"
    if mi["state"] == "PENDING_APPROVAL":
        names = ", ".join(a["name"] for a in mi["approvals"]["approvers"]) or "none yet"
        line += f"   Approvals: {mi['approvals']['received']}/{mi['approvals']['required']} ({names})"
    console.print(line)
    if mi.get("description"):
        console.print(f"  [dim]{mi['description']}[/dim]")
    if mi["slots"]:
        t = table("Slot", "Needs", "Crew", "Open")
        for s in mi["slots"]:
            needs = ", ".join(
                f"{r['skill']} {r['min_level']}+" + (" (cert)" if r["cert_required"] else "") for r in s["requirements"]
            )
            crew = ", ".join(f"{a['crew_name']} {styled(a['state'])}" for a in s["assignments"]) or "-"
            open_ = f"[red]{s['open_positions']}[/red]" if s["open_positions"] else "0"
            t.add_row(
                f"{s['role_name']} x{s['headcount']}" if s["headcount"] > 1 else s["role_name"],
                needs,
                crew,
                open_,
            )
        console.print(t)
    else:
        console.print("  [dim]No crew slots yet.[/dim]")
    next_steps(*suggest_next(mi))


def suggest_next(mi: dict) -> list[str]:
    code, state = mi["code"], mi["state"]
    if state == "DRAFT":
        if not mi["slots"]:
            return [f"mc mission slot add {code} --role Commander --skill piloting:4"]
        if any(s["open_positions"] for s in mi["slots"]):
            return [f"mc match {code}"]
        if all(s["accepted"] == s["headcount"] for s in mi["slots"]):
            return [f"mc mission submit {code}"]
        return ["mc inbox   (waiting for crew to accept their offers)"]
    if state == "PENDING_APPROVAL":
        return [f"mc mission approve {code}   (a Director other than the submitter)"]
    if state == "APPROVED":
        return [f"mc mission start {code}"]
    if state == "ACTIVE":
        return [f"mc mission complete {code}"]
    return []


# ---------------------------------------------------------------- missions


@app.command("list")
def list_missions(
    state: str = typer.Option(None, "--state", "-s", help="Filter, e.g. DRAFT or PENDING_APPROVAL"),
):
    """List missions (crew members see only missions they are on)."""
    rows = api().get("/missions", state=state)

    def render():
        if not rows:
            console.print("No missions found.")
            next_steps('mc mission create "Name" --start 2027-03-01 --end 2027-03-21')
            return
        t = table("Code", "Name", "Window", "State", "Owner")
        for r in rows:
            t.add_row(
                r["code"],
                r["name"],
                window(r["starts_at"], r["ends_at"]),
                styled(r["state"]),
                r["owner"]["name"],
            )
        console.print(t)

    emit(rows, render)


@app.command("create")
def create(
    name: str = typer.Argument(..., help="Mission name"),
    start: str = typer.Option(..., "--start", help="YYYY-MM-DD (UTC) or ISO-8601"),
    end: str = typer.Option(..., "--end", help="YYYY-MM-DD (UTC) or ISO-8601"),
    description: str = typer.Option(None, "--description", "-d"),
):
    """Create a DRAFT mission; you become its owner."""
    mi = api().post(
        "/missions",
        {
            "name": name,
            "description": description,
            "starts_at": parse_when(start),
            "ends_at": parse_when(end),
        },
    )
    emit(
        mi,
        lambda: (
            ok(f"Created [bold]{mi['code']}[/bold] ({mi['state']})  {window(mi['starts_at'], mi['ends_at'])}"),
            next_steps(f"mc mission slot add {mi['code']} --role Commander --skill piloting:4 --skill eva:3"),
        ),
    )


@app.command("show")
def show(ref: str = typer.Argument(..., help="Mission code, e.g. ART-12")):
    """Show a mission: window, state, slots and crew."""
    mi = api().get(f"/missions/{seg(ref)}")
    emit(mi, lambda: render_mission(mi))


@app.command("edit")
def edit(
    ref: str = typer.Argument(...),
    name: str = typer.Option(None, "--name"),
    start: str = typer.Option(None, "--start"),
    end: str = typer.Option(None, "--end"),
    description: str = typer.Option(None, "--description", "-d"),
):
    """Edit a mission. Changing dates is a material change: a pending/approved mission returns to DRAFT."""
    body = {
        "name": name,
        "description": description,
        "starts_at": parse_when(start) if start else None,
        "ends_at": parse_when(end) if end else None,
    }
    body = {k: v for k, v in body.items() if v is not None}
    if not body:
        raise CliError("Nothing to change. Pass --name, --start, --end or --description.")
    mi = api().patch(f"/missions/{seg(ref)}", body)
    emit(mi, lambda: (ok(f"Updated {mi['code']} (now r{mi['revision']}, {mi['state']})"), render_mission(mi)))


@app.command("history")
def history(ref: str = typer.Argument(...)):
    """Audit trail for a mission (Directors and the mission's lead)."""
    rows = api().get(f"/missions/{seg(ref)}/history")

    def render():
        t = table("When (UTC)", "Who", "Action", "Details")
        for e in rows:
            details = ", ".join(f"{k}={v}" for k, v in e["data"].items() if v not in (None, "", [], {}))
            t.add_row(e["at"][:16].replace("T", " "), (e["actor"] or {}).get("name", "-"), e["action"], details)
        console.print(t)

    emit(rows, render)


@app.command("offer")
def offer(
    ref: str = typer.Argument(..., help="Mission code"),
    crew: str = typer.Argument(..., help="Crew name or email"),
    slot: str = typer.Option(..., "--slot", help="Slot role name"),
):
    """Offer a slot to a specific crew member (they must be eligible)."""
    a = api().post(f"/missions/{seg(ref)}/assignments", {"slot": slot, "crew": crew})
    emit(
        a,
        lambda: (
            ok(f"Offered {a['slot']} on {a['mission_code']} to {a['crew_name']} \\[{short(a['id'])}]"),
            next_steps(f"mc mission show {a['mission_code']}"),
        ),
    )


# ---------------------------------------------------------------- slots


def _parse_skill(spec: str) -> dict:
    parts = spec.split(":")
    if len(parts) not in (2, 3) or not parts[1].isdigit() or (len(parts) == 3 and parts[2] != "cert"):
        raise CliError(f"'{spec}' is not SKILL:LEVEL or SKILL:LEVEL:cert (e.g. piloting:4, eva:3:cert).")
    return {"skill": parts[0], "min_level": int(parts[1]), "cert_required": len(parts) == 3}


@slot_app.command("add")
def slot_add(
    ref: str = typer.Argument(..., help="Mission code"),
    role: str = typer.Option(..., "--role", "-r", help="Role name, e.g. Commander"),
    count: int = typer.Option(1, "--count", "-n", min=1, help="How many people in this role"),
    skill: list[str] = typer.Option(..., "--skill", "-s", help="SKILL:LEVEL[:cert], repeatable"),
):
    """Add a crew slot with its skill requirements."""
    mi = api().post(
        f"/missions/{seg(ref)}/slots",
        {"role_name": role, "headcount": count, "requirements": [_parse_skill(s) for s in skill]},
    )
    emit(
        mi,
        lambda: (
            ok(f"Added {role}" + (f" x{count}" if count > 1 else "") + f" to {mi['code']} (r{mi['revision']})"),
            render_mission(mi),
        ),
    )


@slot_app.command("remove")
def slot_remove(ref: str = typer.Argument(...), slot: str = typer.Argument(..., help="Slot role name")):
    """Remove a slot that has no assignment history."""
    mi = api().delete(f"/missions/{seg(ref)}/slots/{seg(slot)}")
    emit(mi, lambda: (ok(f"Removed {slot} from {mi['code']}"), render_mission(mi)))


# ---------------------------------------------------------------- lifecycle


def _transition(ref: str, action: str, body: dict | None = None) -> dict:
    return api().post(f"/missions/{seg(ref)}/{action}", body)


@app.command("submit")
def submit(ref: str = typer.Argument(...)):
    """Submit for approval (every position needs an accepted crew member)."""
    mi = _transition(ref, "submit")
    emit(
        mi,
        lambda: (
            ok(f"{mi['code']} submitted for approval (r{mi['revision']})"),
            next_steps("A Director other than you approves it: mc mission approve " + mi["code"]),
        ),
    )


@app.command("approve")
def approve(ref: str = typer.Argument(...)):
    """Approve a pending mission (Directors; not your own submission)."""
    a = api()
    current = a.get(f"/missions/{seg(ref)}")
    mi = a.post(f"/missions/{seg(ref)}/approve", {"revision": current["revision"]})

    def render():
        if mi["state"] == "APPROVED":
            ok(f"{mi['code']} is [green]APPROVED[/green]")
            next_steps(f"mc mission start {mi['code']}")
        else:
            ok(f"Approval recorded for {mi['code']}: {mi['approvals']['received']}/{mi['approvals']['required']}")

    emit(mi, render)


@app.command("reject")
def reject(ref: str = typer.Argument(...), reason: str = typer.Option(None, "--reason", "-r")):
    """Reject a pending mission back to DRAFT, with a reason."""
    a = api()
    current = a.get(f"/missions/{seg(ref)}")
    text = require_reason(reason, "rejecting")
    mi = a.post(f"/missions/{seg(ref)}/reject", {"revision": current["revision"], "reason": text})
    emit(mi, lambda: ok(f"{mi['code']} rejected and returned to DRAFT."))


def _simple(action: str, verb: str, help_text: str):
    def command(ref: str = typer.Argument(..., help="Mission code")):
        mi = _transition(ref, action)
        emit(mi, lambda: (ok(f"{mi['code']} {verb} -> {styled(mi['state'])}"), next_steps(*suggest_next(mi))))

    command.__doc__ = help_text
    app.command(action)(command)


_simple("withdraw", "withdrawn from approval", "Pull a pending mission back to DRAFT.")
_simple("start", "started", "Start an approved mission.")
_simple("complete", "completed", "Mark an active mission complete.")


def _destructive(action: str, verb: str, help_text: str, consequence: str):
    def command(
        ref: str = typer.Argument(..., help="Mission code"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation"),
    ):
        a = api()
        mi = a.get(f"/missions/{seg(ref)}")
        crew = sum(len(s["assignments"]) for s in mi["slots"])
        confirm(f"{action.capitalize()} {mi['code']} ({mi['name']})? {consequence.format(crew=crew)}", yes)
        result = a.post(f"/missions/{seg(ref)}/{action}")
        emit(result, lambda: ok(f"{result['code']} {verb} -> {styled(result['state'])}"))

    command.__doc__ = help_text
    app.command(action)(command)


_destructive("abort", "aborted", "Abort an active mission.", "This ends the mission and cannot be undone.")
_destructive(
    "cancel",
    "cancelled",
    "Cancel a mission that has not started (releases its crew).",
    "This releases {crew} crew member(s) and cannot be undone.",
)
