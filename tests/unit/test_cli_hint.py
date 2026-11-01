import os
import stat

from mission_control.cli_hint import mc_command


def test_suggests_plain_mc_only_when_installed_outside_the_venv(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", "/usr/bin")
    assert mc_command() == "uv run mc"
    exe = bin_dir / "mc"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin")
    assert mc_command() == "mc"
