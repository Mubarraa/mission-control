"""Local session storage: ~/.config/mc/session.json (mode 0600). Only the token is stored, never the password."""

import json
import os
from pathlib import Path

DEFAULT_API = "http://localhost:8000"


def config_dir() -> Path:
    return Path(os.environ.get("MC_CONFIG_DIR", Path.home() / ".config" / "mc"))


def session_path() -> Path:
    return config_dir() / "session.json"


def load() -> dict:
    try:
        return json.loads(session_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(data: dict) -> Path:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(path, 0o600)
    return path


def clear() -> bool:
    try:
        session_path().unlink()
        return True
    except FileNotFoundError:
        return False


def api_url(override: str | None = None) -> str:
    return (override or os.environ.get("MC_API_URL") or load().get("api_url") or DEFAULT_API).rstrip("/")
