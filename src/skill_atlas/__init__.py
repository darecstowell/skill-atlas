"""Skill Atlas: inventory, switch, and update the agent skills on this machine."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
WEB = PACKAGE / "web"


def _home() -> Path:
    """The clone root when run from a clone, else a per-user data folder."""
    root = PACKAGE.parent.parent
    if PACKAGE.parent.name == "src" and (root / "pyproject.toml").is_file():
        return root
    base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(base).expanduser() / "skill-atlas"


REPO = _home()
