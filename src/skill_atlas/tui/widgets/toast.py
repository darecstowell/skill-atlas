"""Toasts: one short message at a time, at the bottom right, above the key bar."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events
from textual.containers import Container, Horizontal
from textual.timer import Timer
from textual.widgets import Static

from .. import theme

if TYPE_CHECKING:
    from rich.console import Console
    from textual.app import App
    from textual.screen import Screen

Severity = Literal["information", "warning", "error"]
Action = tuple[str, str, Callable[[], Any]]

MAX_WIDTH = 60
PADDING = 4
CLOSE_WIDTH = 4
LINES = 3
ENTER, EXIT = 0.15, 0.10
RESUME = 2.5
GLYPHS: dict[str, tuple[str, str]] = {
    "warning": ("!", "atlas-warn"),
    "error": ("✗", "atlas-danger"),
}


def duration(text: str, *, long: bool) -> float:
    """Seconds on screen: 0.3 s a word, at least 4 s, or 8 s for undo and error toasts."""
    return max(8.0 if long else 4.0, 0.3 * len(text.split()))


def room(hint: Text | None) -> int:
    """Cells for the body: the toast's width less its padding, the hint, and `✕`."""
    return MAX_WIDTH - PADDING - CLOSE_WIDTH - (cell_len(hint.plain) + 3 if hint else 0)


def fit(body: Text, width: int, console: Console) -> tuple[Text, bool]:
    """Wrap body at width; past LINES lines, end the last one with `…`. True if cut."""
    lines = body.wrap(console, width)
    if len(lines) <= LINES:
        return body, False
    last = lines[LINES - 1]
    last.rstrip()
    last.truncate(width - 1)
    last.append("…")
    return Text("\n").join(lines[:LINES]), True


class ToastArea(Container):
    """Holds the toast over every layer of its screen. Only the toast itself takes the mouse."""

    DEFAULT_CSS = """
    ToastArea {
        layer: atlas-toasts;
        overlay: screen;
        dock: bottom;
        width: 1fr;
        height: auto;
        align: right bottom;
        margin-bottom: 1;
        padding-right: 1;
        background: transparent;
        visibility: hidden;
    }
    """


class ToastHint(Static):
    """The action of a toast, such as `z Undo`. A click runs it."""

    DEFAULT_CSS = """
    ToastHint { width: auto; height: 1; padding: 0 1; margin-left: 1; }
    ToastHint:hover { background: $atlas-surface-2; }
    ToastHint.-pressed { background: $atlas-surface-1; }
    """

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.add_class("-pressed")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.remove_class("-pressed")

    def on_leave(self, event: events.Leave) -> None:
        self.remove_class("-pressed")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        toast = self.parent
        if isinstance(toast, AtlasToast):
            toast.act()


class ToastClose(Static):
    """The `✕` cell. A click closes the toast."""

    DEFAULT_CSS = """
    ToastClose { width: 3; height: 1; margin-left: 1; content-align: center middle; }
    ToastClose { color: $atlas-muted; }
    ToastClose:hover { background: $atlas-surface-2; color: $atlas-text; }
    """

    def __init__(self) -> None:
        super().__init__("✕")
        self.tooltip = "Dismiss"

    def on_click(self, event: events.Click) -> None:
        event.stop()
        toast = self.parent
        if isinstance(toast, AtlasToast):
            toast.close()


class AtlasToast(Horizontal):
    """One message, an optional action, and `✕`. The mouse over it pauses its timer."""

    DEFAULT_CSS = """
    AtlasToast {
        visibility: visible;
        width: auto;
        max-width: 60;
        height: auto;
        padding: 1 2;
        background: $atlas-surface-3;
        color: $atlas-text;
    }
    AtlasToast > .toast--body { width: auto; height: auto; max-height: 3; }
    """

    def __init__(
        self,
        text: Text,
        *,
        hint: Text | None,
        callback: Callable[[], Any] | None,
        seconds: float,
        on_close: Callable[[], Any] | None = None,
        full: str | None = None,
        fade: bool = True,
    ) -> None:
        body = Static(text, classes="toast--body")
        body.styles.max_width = room(hint)
        body.tooltip = full
        children: list[Static] = [body]
        if hint is not None:
            children.append(ToastHint(hint))
        children.append(ToastClose())
        super().__init__(*children)
        self.text = text
        self.full = full
        self.seconds = seconds
        self._hint = hint
        self._fade = fade
        self._callback = callback
        self._on_close = on_close
        self._timer: Timer | None = None
        self._deadline: float | None = None
        self._leaving = False
        self._next: AtlasToast | None = None

    def on_mount(self) -> None:
        if self._fade and self.app.animation_level == "full":
            self.styles.opacity = 0.0
            self.styles.animate(
                "opacity",
                1.0,
                duration=ENTER,
                easing="out_cubic",
                level="full",
                on_complete=self._settled,
            )
        self._arm(self.seconds)
        self.app.screen_change_signal.subscribe(self, self._carry, immediate=True)

    def _settled(self) -> None:
        # Children keep the style they cached at opacity 0 until told it changed.
        for w in (self, *self.walk_children()):
            w.notify_style_update()
            w.refresh()

    def _arm(self, seconds: float) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(seconds, self.close)
        self._deadline = time.monotonic() + seconds

    @property
    def remaining(self) -> float:
        """Seconds left on screen; a paused toast gets RESUME once the mouse goes."""
        if self._deadline is None:
            return RESUME
        return max(0.0, self._deadline - time.monotonic())

    def _carry(self, screen: Screen[Any]) -> None:
        """When this toast's screen closes, show it on the screen below with the time it had."""
        if self._leaving or not self.is_attached or self.screen in self.app.screen_stack:
            return
        left = self.remaining
        if left <= 0:
            return
        new = AtlasToast(
            self.text,
            hint=self._hint,
            callback=self._callback,
            seconds=left,
            on_close=self._on_close,
            full=self.full,
            fade=False,
        )
        self._callback = self._on_close = None
        self.close(motion=False)
        self._next = new
        _place(screen, new)

    def on_enter(self, event: events.Enter) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
            self._deadline = None

    def on_leave(self, event: events.Leave) -> None:
        if not self._leaving and not self.is_mouse_over:
            self._arm(RESUME)

    def act(self) -> None:
        """Run the action once, then close."""
        callback, self._callback = self._callback, None
        self.close()
        if callback is not None:
            result = callback()
            if inspect.isawaitable(result):
                self.app.run_worker(result, group="atlas-toast")

    def close(self, *, motion: bool = True) -> None:
        """Fade out and leave; `motion=False` leaves at once, as when a new toast replaces it."""
        if self._next is not None:
            self._next.close(motion=motion)
            return
        if self._leaving:
            return
        self._leaving = True
        if self._timer is not None:
            self._timer.stop()
        done, self._on_close = self._on_close, None
        if done is not None:
            done()
        if motion and self.is_attached and self.app.animation_level == "full":
            self.styles.animate(
                "opacity",
                0.0,
                duration=EXIT,
                easing="in_cubic",
                level="full",
                on_complete=self.remove,
            )
        else:
            self.remove()

    @property
    def closing(self) -> bool:
        return self._next.closing if self._next is not None else self._leaving


def _place(screen: Screen[Any], widget: AtlasToast) -> None:
    areas = screen.query_children(ToastArea)
    if areas:
        areas.first().mount(widget)
    else:
        screen.mount(ToastArea(widget))


def _toasts(app: App[Any]) -> list[AtlasToast]:
    return [t for s in app.screen_stack for t in s.query(AtlasToast)]


def current(app: App[Any]) -> AtlasToast | None:
    """The toast on screen, if one is there and not on its way out."""
    return next((t for t in _toasts(app) if not t.closing), None)


def dismiss(app: App[Any]) -> None:
    """Close the toast on screen, with its exit motion."""
    for t in _toasts(app):
        t.close()


def toast(
    app: App[Any],
    text: str | Text,
    *,
    severity: Severity = "information",
    action: Action | None = None,
    seconds: float | None = None,
    on_close: Callable[[], Any] | None = None,
) -> AtlasToast:
    """Show one toast and replace any other at once. A str is plain text, never markup.

    action is (key, label, callback): the toast shows `key label`, and a click runs callback.
    """
    colors = theme.colors(app)
    body = Text(text) if isinstance(text, str) else text.copy()
    glyph = GLYPHS.get(severity)
    if glyph:
        body = Text.assemble((f"{glyph[0]} ", Style(color=colors[glyph[1]])), body)
    hint = None
    if action is not None:
        key, label, _ = action
        hint = Text.assemble((key, Style(color=colors["atlas-accent"])), f" {label}")
    words = body.plain + (f" {action[1]}" if action else "")
    long = action is not None or severity == "error"
    for old in _toasts(app):
        old.close(motion=False)
    shown, cut = fit(body, room(hint), app.console)
    widget = AtlasToast(
        shown,
        hint=hint,
        callback=action[2] if action else None,
        seconds=seconds if seconds is not None else duration(words, long=long),
        on_close=on_close,
        full=body.plain if cut else None,
    )
    _place(app.screen, widget)
    return widget
