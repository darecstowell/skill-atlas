"""A focusable on/off switch that draws like the list's switches."""

from __future__ import annotations

from typing import ClassVar

from rich.color import Color, blend_rgb
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget

from . import charts

MOVE_SECONDS = 0.06


def _hex(style: Style) -> str:
    return style.color.get_truecolor().hex if style.color else ""


def _mix(a: Style, b: Style) -> Style:
    if a.color is None or b.color is None:
        return b
    rgb = blend_rgb(a.color.get_truecolor(), b.color.get_truecolor(), 0.5)
    return Style(color=Color.from_triplet(rgb))


class ToggleSwitch(Widget, can_focus=True):
    """`━━●` on, `○━━` off. Enter, space, or a click toggles it and posts `Changed`.

    Setting `on` in code is silent, so a failed write can revert it without a new `Changed`.
    """

    DEFAULT_CSS = """
    ToggleSwitch {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    ToggleSwitch:hover { background: $atlas-surface-2; }
    ToggleSwitch:focus { background: $atlas-selection; }
    ToggleSwitch.-pressed { background: $atlas-surface-3; }
    ToggleSwitch:disabled { background: transparent; }
    ToggleSwitch > .toggleswitch--on { color: $atlas-on; }
    ToggleSwitch > .toggleswitch--off { color: $atlas-off; }
    ToggleSwitch > .toggleswitch--knob-off { color: $atlas-muted; }
    ToggleSwitch > .toggleswitch--disabled { color: $atlas-faint; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "toggleswitch--on",
        "toggleswitch--off",
        "toggleswitch--knob-off",
        "toggleswitch--disabled",
    }
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "toggle_switch", "Toggle", show=False),
    ]
    ALLOW_SELECT = False

    on: reactive[bool] = reactive(False)

    class Changed(Message):
        """The user turned the switch on or off."""

        def __init__(self, switch: ToggleSwitch, on: bool) -> None:
            super().__init__()
            self.switch = switch
            self.on = on

        @property
        def control(self) -> ToggleSwitch:
            return self.switch

    def __init__(
        self,
        on: bool = False,
        *,
        label: str | None = None,
        show_state: bool = False,
        reason: str = "no switch",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        """`label` names what the switch controls, for its tooltip: `Codex: turn off`.

        When disabled, `reason` replaces the state word and is the tooltip.
        """
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.label = label
        self.show_state = show_state
        self.reason = reason
        self._moving = False
        self._move_timer: Timer | None = None
        self.set_reactive(ToggleSwitch.on, on)
        self._sync_tooltip()

    def toggle(self) -> None:
        """Flip the switch as the user would and post `Changed`."""
        self.on = not self.on
        self.post_message(self.Changed(self, self.on))

    def action_toggle_switch(self) -> None:
        self.toggle()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.add_class("-pressed")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.remove_class("-pressed")

    def on_leave(self, event: events.Leave) -> None:
        self.remove_class("-pressed")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.toggle()
        if self.app.animation_level == "full":
            self._moving = True
            self._move_timer = self.set_timer(MOVE_SECONDS, self._settle)
            self.refresh()

    def watch_on(self) -> None:
        self._settle()
        self._sync_tooltip()

    def _watch_disabled(self) -> None:
        self._sync_tooltip()
        self.refresh(layout=True)

    def _sync_tooltip(self) -> None:
        if self.disabled:
            self.tooltip = self.reason
            return
        action = "turn off" if self.on else "turn on"
        self.tooltip = f"{self.label}: {action}" if self.label else action.capitalize()

    def _settle(self) -> None:
        if self._move_timer is not None:
            self._move_timer.stop()
            self._move_timer = None
        if self._moving:
            self._moving = False
            self.refresh()

    def render(self) -> Text:
        style = self.get_component_rich_style
        on, off = style("toggleswitch--on", partial=True), style("toggleswitch--off", partial=True)
        faint = style("toggleswitch--disabled", partial=True)
        if self._moving and not self.disabled:
            text = Text(charts.SWITCH["moving"], _mix(on, off), no_wrap=True, end="")
        else:
            colors = {
                "atlas-on": _hex(on),
                "atlas-off": _hex(off),
                "atlas-muted": _hex(style("toggleswitch--knob-off", partial=True)),
                "atlas-faint": _hex(faint),
            }
            text = charts.switch(self.on, colors, disabled=self.disabled)
        if self.show_state and self.disabled:
            text.append(" ").append(self.reason, faint)
        elif self.show_state:
            text.append(" ").append("on " if self.on else "off", on if self.on else off)
        return text
