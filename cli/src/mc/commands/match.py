import typer

from mc.client import seg
from mc.commands.common import api
from mc.output import console, emit, next_steps, ok, short, table, window


def match(
    ref: str = typer.Argument(..., help="Mission code, e.g. ART-12"),
    role: str = typer.Argument(None, help="With --explain: only this slot"),
    explain: bool = typer.Option(False, "--explain", "-x", help="Show score breakdowns, alternatives and why-not"),
    all_reasons: bool = typer.Option(False, "--all", help="List every excluded candidate, not just the closest 5"),
    apply: bool = typer.Option(False, "--apply", help="Offer the suggested crew their positions"),
    only: list[str] = typer.Option(None, "--only", help="With --apply: only these roles (repeatable)"),
):
    """Suggest the best crew for a mission's open positions, and explain why."""
    a = api()
    result = a.get(f"/missions/{seg(ref)}/match", all="true" if all_reasons else None)

    if apply:
        wanted = {o.lower() for o in only or []}
        pairs = [
            {"slot_id": p["slot_id"], "crew_id": p["suggestion"]["crew_id"]}
            for p in result["positions"]
            if p["suggestion"] and (not wanted or p["role_name"].lower() in wanted or p["label"].lower() in wanted)
        ]
        if not pairs:
            emit({"applied": [], "rejected": []}, lambda: console.print("No suggestions to apply."))
            return
        out = a.post(f"/missions/{seg(ref)}/match/apply", {"pairs": pairs})

        def render_apply():
            for x in out["applied"]:
                ok(f"Offered {x['slot']} to {x['crew_name']} \\[{short(x['id'])}]")
            for x in out["rejected"]:
                console.print(f"[red]x[/red] {x['crew_name'] or x['crew_id']}: {x['reason']}")
            next_steps(
                "Crew accept via `mc assignment accept` - track progress with `mc inbox`",
                f"mc mission show {result['mission_code']}",
            )

        emit(out, render_apply)
        return

    emit(result, lambda: _render(result, explain, role))


def _render(r: dict, explain: bool, role: str | None) -> None:
    console.print(
        f"  [bold]{r['mission_code']}[/bold]  {r['mission_name']}   {window(r['starts_at'], r['ends_at'])}   "
        f"DRAFT r{r['revision']}"
    )
    if not r["positions"]:
        console.print("  Every position already has an offer or an accepted crew member.")
        next_steps(f"mc mission show {r['mission_code']}")
        return
    t = table("Position", "Suggested", "Score", "Why")
    for p in r["positions"]:
        s = p["suggestion"]
        if s:
            t.add_row(p["label"], s["name"], f"{s['score']:.2f}", s["reason"])
        else:
            t.add_row(
                p["label"],
                "[red]- unfilled -[/red]",
                "-",
                f"[red]0 eligible ({p['excluded_total']} excluded)[/red]",
            )
    console.print(t)
    sm = r["summary"]
    console.print(f"  {sm['filled']} of {sm['open']} positions filled.")

    if explain:
        for p in r["positions"]:
            if role and role.lower() not in (p["role_name"].lower(), p["label"].lower()):
                continue
            _explain(p)

    hints = []
    if sm["filled"]:
        hints.append(
            f"mc match {r['mission_code']} --apply      (offers the {sm['filled']} suggestion"
            f"{'s' if sm['filled'] != 1 else ''})"
        )
    gap = next((p for p in r["positions"] if not p["suggestion"]), None)
    if gap and not explain:
        hints.append(f'mc match {r["mission_code"]} --explain "{gap["role_name"]}"')
    if (
        gap
        and explain
        and any(rule["rule"] == "UNVERIFIED_WOULD_QUALIFY" for e in gap["unfilled_reasons"] for rule in e["rules"])
    ):
        hints.append("mc crew verify <crew> <skill>      (a pending claim would fill the gap)")
    next_steps(*hints)


def _explain(p: dict) -> None:
    console.print()
    console.print(f"[bold]{p['label']}[/bold]")
    s = p["suggestion"]
    if s:
        b = s["breakdown"]
        console.print(
            f"  Suggested: [bold]{s['name']}[/bold] {s['score']:.2f}   fit {b['fit']:.2f} · "
            f"right-size {b['rightsizing']:.2f} · workload {b['workload']:.2f} · "
            f"experience {b['experience']:.2f}" + (f" · penalty -{b['penalty']:.2f}" if b["penalty"] else "")
        )
        for alt in p["alternatives"]:
            console.print(f"  [dim]alt[/dim] {alt['name']} {alt['score']:.2f}  {alt['reason']}")
        if not p["alternatives"]:
            console.print("  [dim]No other eligible crew.[/dim]")
        return
    console.print("  [red]No eligible crew.[/red] Closest candidates:")
    for e in p["unfilled_reasons"]:
        details = "; ".join(rule["detail"] for rule in e["rules"])
        console.print(f"    {e['name']:<18} {details}")
    hidden = p["excluded_total"] - len(p["unfilled_reasons"])
    if hidden > 0:
        console.print(f"    [dim]... and {hidden} more (use --all)[/dim]")
