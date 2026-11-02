import re
from pathlib import Path

from mission_control.api import banner

README = (Path(__file__).resolve().parents[2] / "README.md").read_text()


def test_banner_points_at_readme_sections_that_exist(monkeypatch, capsys):
    monkeypatch.setenv("MC_BANNER_URL", "http://localhost:8000")
    monkeypatch.setattr(banner, "_demo_seeded", lambda: True)
    banner.print_banner()
    text = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().err)
    sections = re.findall(r'README\.md -> "([^"]+)"', text)
    assert sections, "banner should point at the README"
    for name in sections:
        assert re.search(rf"^##+ {re.escape(name)}\s*$", README, re.M), f"README has no section '{name}'"


def test_banner_is_silent_without_flag(monkeypatch, capsys):
    monkeypatch.delenv("MC_BANNER_URL", raising=False)
    banner.print_banner()
    assert capsys.readouterr().err == ""
