"""Which command developers should type for the CLI: `mc` if installed (make install-cli), else `uv run mc`."""

import os
import shutil
import sys


def mc_command() -> str:
    # Ignore the project's own virtualenv (uv run puts it on PATH); look for an installed `mc` elsewhere.
    venv_bin = os.path.join(sys.prefix, "bin")
    path = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep) if os.path.abspath(p) != venv_bin)
    return "mc" if shutil.which("mc", path=path) else "uv run mc"
