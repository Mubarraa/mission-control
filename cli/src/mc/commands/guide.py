import typer

from mc.errors import EXIT_USAGE, CliError
from mc.guides import GUIDES
from mc.output import console, emit, localize, next_steps


def guide(topic: str = typer.Argument(None, help="onboard (add a new crew member) | plan | approve | changes")) -> None:
    """Step-by-step guides for the main workflows, showing who runs each step."""
    if topic is None:
        data = {k: {"title": g["title"], "summary": g["summary"]} for k, g in GUIDES.items()}

        def render():
            console.print("[bold]Guides[/bold]")
            for key, g in GUIDES.items():
                console.print(f"  [bold]{key:<8}[/bold] {g['title']} - [dim]{g['summary']}[/dim]")
            next_steps("mc guide onboard")

        emit(data, render)
        return
    g = GUIDES.get(topic.lower())
    if g is None:
        raise CliError(f"No guide called '{topic}'. Choose one of: {', '.join(GUIDES)}.", EXIT_USAGE)
    emit(g, lambda: _render(g))


def _render(g: dict) -> None:
    console.print(f"[bold]{g['title']}[/bold]  [dim]{g['summary']}[/dim]")
    current = object()
    for role, command, note in g["steps"]:
        if role != current:
            console.print()
            if role:
                console.print(f"[bold cyan]{role}[/bold cyan]")
            current = role
        if command:
            console.print(f"  [bold]{localize(command)}[/bold]")
            if note:
                console.print(f"      [dim]{note}[/dim]")
        elif note:
            console.print(f"  [yellow]Note:[/yellow] {note}")
    console.print()
    console.print("[dim]Switch users with `" + localize("mc login --org <slug> --email <email>") + "`.[/dim]")
