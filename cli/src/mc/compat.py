"""Exception classes from whichever click implementation Typer uses."""

import typer

# Newer Typer vendors its own copy of click (and doesn't install click); older Typer uses click itself.
# The CLI declares only typer/rich/httpx, so click is optional here - catch whichever is present.
_usage: list[type[Exception]] = []
_abort: list[type[BaseException]] = [typer.Abort]
_exit: list[type[BaseException]] = [typer.Exit]
try:
    from typer._click import exceptions as _tclick

    _usage.append(_tclick.UsageError)
except ImportError:  # pragma: no cover
    pass
try:
    import click

    _usage.append(click.exceptions.UsageError)
    _abort.append(click.exceptions.Abort)
    _exit.append(click.exceptions.Exit)
except ImportError:  # pragma: no cover - the installed CLI has no click
    pass
USAGE_ERRORS, ABORTS, EXITS = tuple(_usage), tuple(_abort), tuple(_exit)
