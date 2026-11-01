import typer

from mc.commands.common import api, resolve_prefix
from mc.output import ROLE_LABEL, age, console, day, emit, next_steps, ok, short, styled, window

app = typer.Typer(help="What needs your attention.", invoke_without_command=True, no_args_is_help=False)


@app.callback(invoke_without_command=True)
def inbox(ctx: typer.Context) -> None:
    """Your home screen: notifications, approvals, missions needing attention, offers."""
    if ctx.invoked_subcommand:
        return
    data = api().get("/inbox")
    emit(data, lambda: _render(data))


@app.command("dismiss")
def dismiss(
    notification: str = typer.Argument(..., help="Notification id (the short id shown in `mc inbox`)"),
):
    """Dismiss a notification."""
    a = api()
    note = resolve_prefix(a.get("/inbox")["notifications"], notification, "notification")
    result = a.post(f"/notifications/{note['id']}/dismiss")
    emit(result, lambda: ok("Notification dismissed."))


def _render(d: dict) -> None:
    empty = True
    hints: list[str] = []
    if d["notifications"]:
        empty = False
        console.print(f"[bold]NOTIFICATIONS[/bold] ({len(d['notifications'])} new)")
        for n in d["notifications"]:
            data = n["data"]
            if n["kind"] == "crew.withdrew":
                state_note = " back to DRAFT" if data.get("returned_to_draft") else ""
                console.print(
                    f"  [red]![/red] \\[{short(n['id'])}] [bold]{data['mission_code']}[/bold]{state_note} - "
                    f"{data['crew']} withdrew from {data['slot']}   [dim]{age(n['created_at'])}[/dim]"
                )
                console.print(f'      Reason: "{data["reason"]}"')
                hints += [f"mc match {data['mission_code']}", f"mc inbox dismiss {short(n['id'])}"]
            else:
                console.print(f"  \\[{short(n['id'])}] {n['kind']}: {data}")
        console.print()
    if d["approvals"]:
        empty = False
        console.print("[bold]AWAITING APPROVAL[/bold]")
        for r in d["approvals"]:
            flag = ""
            if r["needs_other_approver"]:
                flag = "  [yellow](you submitted or own it - needs another Director)[/yellow]"
            elif r["already_approved"]:
                flag = "  [dim](you approved; waiting for others)[/dim]"
            console.print(
                f"  [bold]{r['code']}[/bold] {r['name']}  starts {day(r['starts_at'])}  "
                f"by {r['submitted_by']}  approvals {r['received']}/{r['required']}{flag}"
            )
            if r["can_approve"]:
                hints.append(f"mc mission show {r['code']}   then   mc mission approve {r['code']}")
        console.print()
    if d["missions"]:
        empty = False
        console.print("[bold]YOUR MISSIONS[/bold]")
        for mi in d["missions"]:
            console.print(
                f"  [bold]{mi['code']}[/bold] {mi['name']}  {styled(mi['state'])}  starts {day(mi['starts_at'])}"
            )
            if mi.get("rejection"):
                console.print(f'      [red]Rejected by {mi["rejection"]["by"]}:[/red] "{mi["rejection"]["reason"]}"')
            for u in mi["unfilled"]:
                console.print(
                    f"      {u['slot']}: {u['accepted']}/{u['headcount']} accepted"
                    + (f", {u['offered']} offered" if u["offered"] else "")
                )
            for o in mi["offers"]:
                stale = "  [red]! stale[/red]" if o["stale"] else ""
                console.print(
                    f"      offer \\[{short(o['assignment_id'])}] {o['crew']} -> {o['slot']}, "
                    f"{o['age_days']:g}d old{stale}"
                )
                if o["stale"]:
                    hints.append(f"follow up with {o['crew']}, or: mc assignment release {short(o['assignment_id'])}")
            for x in mi["exits"]:
                console.print(f'      [dim]{x["crew"]} {x["state"].lower()} {x["slot"]}: "{x["reason"]}"[/dim]')
            if mi["ready_to_submit"]:
                hints.append(f"mc mission submit {mi['code']}")
            elif mi["state"] == "DRAFT" and mi["unfilled"] and not any(u["offered"] for u in mi["unfilled"]):
                hints.append(f"mc match {mi['code']}")
        console.print()
    if d["offers"]:
        empty = False
        console.print("[bold]ASSIGNMENT OFFERS[/bold]")
        for o in d["offers"]:
            console.print(
                f"  \\[{short(o['assignment_id'])}] [bold]{o['mission_code']}[/bold] {o['mission_name']} - "
                f"{o['slot']}, {window(o['starts_at'], o['ends_at'])}"
            )
            hints.append(
                f"mc assignment accept {short(o['assignment_id'])}   |   "
                f'mc assignment decline {short(o["assignment_id"])} --reason "..."'
            )
        console.print()
    if d["skills_awaiting_verification"]:
        empty = False
        console.print("[bold]SKILLS AWAITING VERIFICATION[/bold]")
        for s in d["skills_awaiting_verification"]:
            current = f" (verified {s['verified_level']} still applies)" if s["verified_level"] else ""
            console.print(f"  {s['skill']} level {s['claimed_level']}{current}")
        console.print()
    if empty:
        console.print(f"Nothing needs your attention right now. [dim]({ROLE_LABEL.get(d['role'], d['role'])})[/dim]")
        hints.append("mc mission list")
    next_steps(*dict.fromkeys(hints))
