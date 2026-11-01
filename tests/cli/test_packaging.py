"""The installed CLI only has its declared dependencies (typer, rich, httpx). Guard against importing others."""

import subprocess
import sys

BLOCK_AND_RUN = """
import sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'click', 'mission_control', 'sqlalchemy', 'fastapi', 'scipy'}:
            raise ImportError(f'{name} is not a dependency of the CLI')
sys.meta_path.insert(0, Block())
from mc.main import run
sys.exit(run(['guide']))
"""


def test_cli_runs_with_only_its_declared_dependencies():
    result = subprocess.run([sys.executable, "-c", BLOCK_AND_RUN], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "onboard" in result.stdout
