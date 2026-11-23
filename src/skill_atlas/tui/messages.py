"""App-level messages.

The app sends StateChanged and DataChanged to every widget and screen that handles them,
so they do not bubble.
"""

from __future__ import annotations

from textual.message import Message


class SkillSelected(Message):
    """A widget moved to a skill path, or to None; open=True also shows the detail panel."""

    def __init__(self, path: str | None, open: bool = False) -> None:
        super().__init__()
        self.path = path
        self.open = open


class ItemSelected(Message):
    """A widget moved to a group id or an available skill (`a:<repo>:<path>`), as on the web."""

    def __init__(self, key: str | None, open: bool = False) -> None:
        super().__init__()
        self.key = key
        self.open = open


class StateChanged(Message):
    """app.state changed; fields names the UIState fields that changed."""

    bubble = False

    def __init__(self, fields: frozenset[str]) -> None:
        super().__init__()
        self.fields = fields


class JobChanged(Message):
    """An update or install job moved; view is the latest job view, or None when it ended."""

    bubble = False

    def __init__(self, view: dict | None) -> None:
        super().__init__()
        self.view = view


class DataChanged(Message):
    """app.data changed; parts names the parts (scan, usage, updates) that loaded or failed."""

    bubble = False

    def __init__(self, parts: frozenset[str]) -> None:
        super().__init__()
        self.parts = parts


class LoadStarted(Message):
    """A part (scan, usage, updates) started to load; app.data still holds its last result."""

    bubble = False

    def __init__(self, part: str) -> None:
        super().__init__()
        self.part = part
