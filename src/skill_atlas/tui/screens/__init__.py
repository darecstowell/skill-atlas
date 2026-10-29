"""Screens that open over the main screen, and the base class they share."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, TypeVar

from rich.cells import cell_len
from textual import events
from textual.binding import Binding, BindingType
from textual.content import Content
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from .. import keys
from ..widgets import charts

R = TypeVar("R")
Variant = Literal["plain", "primary", "danger", "warn"]
SPIN_SECONDS = 0.08


class AtlasModal(ModalScreen[R]):
    """A dialog over a dimmed main screen. esc, the ✕ cell, or a click outside dismisses it.

    Set CLOSE_ON_OUTSIDE = False where a stray click must not cancel, such as confirm-delete.
    """

    CLOSE_ON_OUTSIDE: ClassVar[bool] = True
    BINDINGS: ClassVar[list[BindingType]] = keys.bindings("modal")
    DEFAULT_CSS = """
    AtlasModal { align: center middle; background: $background 60%; }
    """

    def action_close(self) -> None:
        self.dismiss(None)

    def on_click(self, event: events.Click) -> None:
        # Offset clicks can name the screen as the widget; ask what is under the pointer.
        under = self.get_widget_at(event.screen_x, event.screen_y)[0]
        if under is self and self.CLOSE_ON_OUTSIDE:
            event.stop()
            self.dismiss(None)


class CloseCell(Static):
    """The ✕ that closes the screen it is on. Three cells wide, so it is easy to hit."""

    DEFAULT_CSS = """
    CloseCell { width: 3; height: 1; content-align: center middle; color: $atlas-muted; }
    CloseCell:hover { background: $atlas-surface-2; color: $atlas-text; }
    """

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__("✕", id=id, classes=classes)
        self.tooltip = "Close"

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.screen.dismiss(None)


class HintButton(Widget, can_focus=True):
    """A button drawn as a key hint, `u Update`. Enter, space, or a mouse up on it runs
    `action` on its screen; the screen binds the key itself."""

    DEFAULT_CSS = """
    HintButton { width: auto; height: 1; padding: 0 1; color: $atlas-text; }
    HintButton > .hintbutton--key { color: $atlas-accent; }
    HintButton:hover { background: $atlas-surface-2; }
    HintButton.-pressed { background: $atlas-surface-3; }
    HintButton.-primary { background: $atlas-accent; color: $atlas-on-accent; }
    HintButton.-primary > .hintbutton--key { color: $atlas-on-accent; }
    HintButton.-primary:hover { background-tint: $atlas-on-accent 12%; }
    HintButton.-primary.-pressed { background-tint: $atlas-on-accent 24%; }
    HintButton.-danger { background: $atlas-danger-tint; color: $atlas-danger; }
    HintButton.-danger > .hintbutton--key { color: $atlas-danger; }
    HintButton.-danger:hover { background-tint: $atlas-danger 12%; }
    HintButton.-danger.-pressed { background-tint: $atlas-danger 24%; }
    HintButton.-warn { background: $atlas-warn-tint; color: $atlas-warn; }
    HintButton.-warn > .hintbutton--key { color: $atlas-warn; }
    HintButton.-warn:hover { background-tint: $atlas-warn 12%; }
    HintButton.-warn.-pressed { background-tint: $atlas-warn 24%; }
    HintButton:disabled { background: transparent; color: $atlas-faint; }
    HintButton:disabled > .hintbutton--key { color: $atlas-faint; }
    HintButton:focus { background: $atlas-selection; color: $atlas-text; }
    HintButton:focus > .hintbutton--key { color: $atlas-accent; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {"hintbutton--key"}
    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter,space", "press", show=False)]
    ALLOW_SELECT = False

    busy: reactive[bool] = reactive(False)

    def __init__(
        self,
        key: str,
        label: str,
        action: str,
        *,
        variant: Variant = "plain",
        busy_label: str = "",
        focusable: bool = True,
        tooltip: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled)
        self.add_class(f"-{variant}")
        self.key, self.label, self.action = key, label, action
        self.busy_label = busy_label or label
        self.can_focus = focusable
        self.tooltip = tooltip
        self._frame = 0
        self._spinner: Timer | None = None

    def relabel(self, label: str, busy_label: str = "") -> None:
        self.label = label
        self.busy_label = busy_label or self.busy_label
        self.refresh(layout=True)

    def _room(self) -> int:
        return max(cell_len(self.label), cell_len(self.busy_label))

    def get_content_width(self, container: Any, viewport: Any) -> int:
        return (cell_len(self.key) + 1 if self.key else 0) + self._room()

    def get_content_height(self, container: Any, viewport: Any, width: int) -> int:
        return 1

    def render(self) -> Content:
        key, label = self.key, self.label
        if self.busy:
            spin = charts.SPINNER[self._frame] if self._spinner is not None else ""
            key, label = spin.ljust(cell_len(self.key)), self.busy_label
        pad = " " * (self._room() - cell_len(label))
        if not self.key:
            return Content(label + pad)
        return Content.assemble(
            (key, self.get_visual_style("hintbutton--key", partial=True)), " ", label + pad
        )

    def watch_busy(self, busy: bool) -> None:
        if busy and self.app.animation_level == "full":
            self._frame = 0
            self._spinner = self.set_interval(SPIN_SECONDS, self._spin)
        elif self._spinner is not None:
            self._spinner.stop()
            self._spinner = None
        self.refresh()

    def _spin(self) -> None:
        self._frame = (self._frame + 1) % len(charts.SPINNER)
        self.refresh()

    async def action_press(self) -> None:
        if not self.disabled and not self.busy:
            await self.app.run_action(self.action, self.screen)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        event.stop()
        self.capture_mouse()
        self.add_class("-pressed")

    async def on_mouse_up(self, event: events.MouseUp) -> None:
        event.stop()
        pressed = self.has_class("-pressed")
        self.release_mouse()
        self.remove_class("-pressed")
        if pressed and self.region.contains(event.screen_x, event.screen_y):
            await self.action_press()

    def on_click(self, event: events.Click) -> None:
        event.stop()
