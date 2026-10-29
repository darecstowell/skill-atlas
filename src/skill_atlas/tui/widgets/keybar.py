"""The key hints at the bottom, read from keys.BAR. Each hint is a button for its key."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import RenderableType
from rich.style import Style
from rich.text import Text
from textual import events
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input

from ...core import views
from .. import commands, keys, theme
from ..messages import DataChanged, JobChanged, StateChanged
from . import app_of

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
TOTALS_FROM = 160
BUSY = {"update": ("u", "U", "Updating…"), "install": ("i", "I", "Installing…")}


@dataclass
class Hint:
    key: keys.Key
    label: str
    busy: bool = False

    @property
    def width(self) -> int:
        """The key, a space, the label, and 1 cell of hover padding on each side."""
        return 1 + cell_len(self.key.short) + 1 + cell_len(self.label) + 1


class KeyBar(Widget):
    """Hints for the focus and the selection at the left; totals at the right from 160 columns.

    Hints drop from the right as the bar narrows; help and quit stay. Click a hint to run it.
    """

    DEFAULT_CSS = """
    KeyBar { height: 1; padding: 0; background: $atlas-surface-1; color: $atlas-muted; }
    KeyBar.-off { display: none; }
    """

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self._flags: frozenset[str] | None = None
        self._shown: list[Hint] = []
        self._hover: int | None = None
        self._pressed: int | None = None
        self._job: dict | None = None
        self._frame = 0
        self._timer: Timer | None = None
        self._colors: dict[str, str] | None = None

    def on_mount(self) -> None:
        self.set_class(not app_of(self).state.key_hints, "-off")
        self.watch(self.screen, "focused", self._focus_moved, init=False)
        self.app.theme_changed_signal.subscribe(self, self._on_theme)

    def _on_theme(self, _: object) -> None:
        self._colors = None
        self.refresh()

    def _focus_moved(self) -> None:
        self.refresh()

    def on_data_changed(self, event: DataChanged) -> None:
        self._flags = None
        self.refresh()

    def on_state_changed(self, event: StateChanged) -> None:
        if "key_hints" in event.fields:
            self.set_class(not app_of(self).state.key_hints, "-off")
        self._flags = None
        self.refresh()

    def on_job_changed(self, event: JobChanged) -> None:
        self._job = event.view
        spin = self.busy_kind() is not None and self.app.animation_level == "full"
        if spin and self._timer is None:
            self._timer = self.set_interval(0.08, self._tick)
        elif not spin and self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.refresh()

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(SPIN)
        if any(h.busy for h in self._shown):
            self.refresh()

    def busy_kind(self) -> str | None:
        job = self._job
        if not job or job.get("done"):
            return None
        kind = job.get("kind")
        return kind if kind in BUSY else None

    def context(self) -> str:
        app = app_of(self)
        focused = app.main.focused
        if isinstance(focused, Input):
            return "search"
        in_panel = focused is not None and any(w.id == "detail-pane" for w in focused.ancestors)
        if in_panel and "panel" in keys.BAR:
            return "panel"
        return "marks" if app.state.marked else "list"

    def flags(self) -> frozenset[str]:
        if self._flags is None:
            self._flags = commands.flags(app_of(self))
        return self._flags

    def hints(self) -> list[Hint]:
        """The context's hints that apply now, before any drop for width."""
        have = self.flags()
        busy = BUSY.get(self.busy_kind() or "")
        out = []
        for k, label in keys.bar_labels(self.context()):
            if busy and k.name in busy[:2]:
                out.append(Hint(k, busy[2], busy=True))
            elif not k.needs or k.needs in have:
                out.append(Hint(k, label))
        return out

    @staticmethod
    def fit(hints: list[Hint], room: int, sticky: int = keys.STICKY) -> list[Hint]:
        """Drop hints from the right, but never the last `sticky`, until they fit in room."""
        keep = list(hints)
        sticky = min(sticky, len(keep))
        while len(keep) > sticky and sum(h.width + 1 for h in keep) - 1 > room:
            keep.pop(len(keep) - sticky - 1)
        return keep

    def totals(self) -> str:
        app = app_of(self)
        if app.data.insights is None:
            return ""
        n = commands.counts(app).get("all", 0)
        summary = commands.cost(app).get("summary") or "No tokens"
        return f"{views.plural(n, 'skill')} · {summary} in context"

    def render(self) -> RenderableType:
        if self._colors is None:
            self._colors = theme.colors(app_of(self))
        c = self._colors
        width = self.size.width
        totals = self.totals() if width >= TOTALS_FROM else ""
        room = width - (cell_len(totals) + 3 if totals else 0)
        self._shown = self.fit(self.hints(), room)
        muted, faint = Style(color=c["atlas-muted"]), Style(color=c["atlas-faint"])
        accent = Style(color=c["atlas-accent"])
        spin = self.app.animation_level == "full"
        line = Text(no_wrap=True, overflow="crop")
        for i, h in enumerate(self._shown):
            under = None
            if i == self._pressed:
                under = c["atlas-surface-3"]
            elif i == self._hover:
                under = c["atlas-surface-2"]
            cell = Style(bgcolor=under, meta={"hint": i})
            key, look = h.key.short, accent
            if h.busy:
                key, look = (SPIN[self._frame], accent) if spin else (key, faint)
            line.append(" ", cell)
            line.append(key, cell + look)
            line.append(f" {h.label} ", cell + muted)
            line.append(" ")
        if totals:
            line.pad_right(max(0, width - line.cell_len - cell_len(totals) - 1))
            words, _, cost = totals.partition(" · ")
            line.append(words, muted)
            line.append(" · ", faint)
            line.append(cost, muted)
        return line

    def _hint_at(self, event: events.MouseEvent) -> int | None:
        index = event.style.meta.get("hint")
        return index if isinstance(index, int) and index < len(self._shown) else None

    def on_mouse_move(self, event: events.MouseMove) -> None:
        index = self._hint_at(event)
        if index != self._hover:
            self._hover = index
            self.refresh()

    def on_leave(self, event: events.Leave) -> None:
        if self._hover is not None:
            self._hover = None
            self.refresh()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        index = self._hint_at(event)
        if index is None or event.button != 1:
            return
        event.stop()
        self._pressed = index
        self.capture_mouse()
        self.refresh()

    async def on_mouse_up(self, event: events.MouseUp) -> None:
        pressed, self._pressed = self._pressed, None
        if pressed is None:
            return
        event.stop()
        self.release_mouse()
        self.refresh()
        if self._hint_at(event) == pressed:
            await app_of(self).run_key(self._shown[pressed].key)
