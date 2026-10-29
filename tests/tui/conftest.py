import threading
from dataclasses import dataclass
from datetime import datetime

import pytest

from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui import state
from skill_atlas.tui.app import AtlasApp

UIState = state.UIState


@dataclass
class OpenDetailState(UIState):
    """The defaults the older tests assume: every repo open, rows with all their detail."""

    opened: frozenset[str] = frozenset({state.ALL_OPEN})
    row_detail: bool = True


@pytest.fixture(autouse=True)
def truecolor(monkeypatch):
    """Rich picks 256 colors when COLORTERM is unset (as in CI); pin true color for stable tests."""
    monkeypatch.setenv("COLORTERM", "truecolor")


@pytest.fixture(autouse=True)
def open_detail(monkeypatch):
    """Apps start with every repo open and detail rows. Ask for `new_defaults` for the real ones."""
    monkeypatch.setattr(state, "UIState", OpenDetailState)


@pytest.fixture
def new_defaults(monkeypatch):
    """The real UIState defaults: repos fold in the All view, and rows are short."""
    monkeypatch.setattr(state, "UIState", UIState)


class StubAtlas:
    """A small fake core. Set `gate` to hold the scan, or `fail` to make a part raise."""

    def __init__(self, n: int = 24):
        self.n = n
        self.gate: threading.Event | None = None
        self.fail: set[str] = set()

    def _check(self, part):
        if part in self.fail:
            raise OSError(f"{part} broke")

    def now(self):
        return datetime.now().astimezone()

    def data(self):
        if self.gate is not None:
            self.gate.wait(5)
        self._check("scan")
        harnesses = {
            "claude-personal": {"name": "Claude Code", "label": "Claude Code · personal"},
            "codex": {"name": "Codex", "label": "Codex"},
        }
        for h in harnesses.values():
            h.update(home="/tmp/stub", switch="", config="", store=True)
        skills = [
            {
                "name": f"skill-{i:02d}",
                "dir_name": f"skill-{i:02d}",
                "description": f"Stub skill number {i}.",
                "scope": "personal",
                "path": f"/stub/skills/skill-{i:02d}/SKILL.md",
                "dir": f"/stub/skills/skill-{i:02d}",
                "harnesses": list(harnesses),
                "origin": {"source": "acme/skills" if i % 2 else "stub/tools"},
                "problems": [
                    {"level": "warn", "message": "Bad frontmatter.", "hint": "Fix the frontmatter."}
                ]
                if i == 3
                else [],
                "security": {"level": "none"},
                "tokens_listed": 40 + i,
            }
            for i in range(self.n)
        ]
        return {"harnesses": harnesses, "settings": {}, "skills": skills, "count": len(skills)}

    def usage(self):
        self._check("usage")
        return {"status": "ready", "skills": {}, "counters": {}, "first_day": None}

    def updates(self, refresh=False):
        self._check("updates")
        return {"skills": {"skill-01": "outdated"}, "errors": {}, "available": {}, "watched": []}


@pytest.fixture
def prefs(tmp_path, monkeypatch):
    path = tmp_path / "prefs" / "tui.json"
    monkeypatch.setenv("SKILL_ATLAS_TUI_PREFS", str(path))
    return path


@pytest.fixture
def stub():
    return StubAtlas()


@pytest.fixture
def app(prefs):
    """An app over DemoAtlas, with its prefs file in tmp_path."""
    return AtlasApp(DemoAtlas())
