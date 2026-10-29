"""The detail panel's specs (plain, comparable data) and the widgets that draw them.

A builder returns specs; `reconcile` keeps a widget whose spec did not change and patches or
replaces the rest, so focus, hover, and scroll stay put while data loads.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from . import charts
from .switch import ToggleSwitch

GUTTER = 2
BAR = "▌"
LABEL_W = 12
BREAKS = "/.:-"


@dataclass(frozen=True)
class Act:
    """An action the panel runs, with string arguments."""

    name: str
    args: tuple[str, ...] = ()


class Acted(Message):
    """A control in the panel asks the panel to run `act`; `on` is set by switches."""

    def __init__(self, act: Act, on: bool | None = None) -> None:
        super().__init__()
        self.act = act
        self.on = on


@dataclass(frozen=True)
class TextEl:
    """Text wrapped to the width. cut="start" keeps one line and cuts the start with `…`."""

    text: Text
    cls: str = ""
    cut: str = ""
    tip: str = ""


@dataclass(frozen=True)
class Hint:
    """One action in a hint bar. tone: "", "primary", "danger", "warn", "busy", "done", or
    "plain" (a keyless action that is not painted as a link)."""

    label: str
    act: Act | None = None
    key: str = ""
    tone: str = ""
    tip: str = ""


@dataclass(frozen=True)
class HintsEl:
    id: str
    hints: tuple[Hint, ...]
    cls: str = ""


@dataclass(frozen=True)
class RowEl:
    """A row: left text, right text, an optional muted second line. keep: the side not cut."""

    id: str
    left: Text
    right: Text | None = None
    act: Act | None = None
    tip: str = ""
    sub: Text | None = None
    keep: str = "right"
    cls: str = ""
    cut: str = "end"


@dataclass(frozen=True)
class SwitchEl:
    """A switch. With `label` it is a Loaded by row; without, the compact title switch."""

    id: str
    act: Act
    on: bool
    label: str = ""
    tip: str = ""
    mixed: bool = False
    current: bool = False
    disabled: bool = False
    reason: str = "no switch"


@dataclass(frozen=True)
class TitleEl:
    text: Text
    switch: SwitchEl | None = None
    close: bool = True


@dataclass(frozen=True)
class DefEl:
    """Label and value rows; a long value wraps under itself. Values of the `cut` labels stay
    on one line, cut at the start. label_w 0 fits the longest label."""

    rows: tuple[tuple[str | Text, Text], ...]
    label_w: int = 0
    cut: tuple[str, ...] = ()


@dataclass(frozen=True)
class HeatEl:
    days: tuple[tuple[str, int], ...]
    today: date
    note: str = ""


@dataclass(frozen=True)
class SparkEl:
    text: Text


@dataclass(frozen=True)
class BarsEl:
    id: str
    rows: tuple[tuple[str, float], ...]
    acts: tuple[Act, ...]


@dataclass(frozen=True)
class SkelEl:
    """DetailSkeleton bars: one line per fraction of the width."""

    widths: tuple[float, ...]


@dataclass(frozen=True)
class BoxEl:
    """A container. Top-level boxes are the panel's blocks; `key` names them."""

    key: str
    items: tuple[El, ...]
    cls: str = ""


El = (
    TextEl
    | HintsEl
    | RowEl
    | SwitchEl
    | TitleEl
    | DefEl
    | HeatEl
    | SparkEl
    | BarsEl
    | SkelEl
    | BoxEl
)


def wid(key: str, kind: str = "d") -> str:
    """A widget id for a spec key: ids allow only letters, digits, `_`, and `-`."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", key)
    if safe != key:
        safe += "-" + hashlib.sha1(key.encode()).hexdigest()[:6]
    return f"{kind}-{safe}"


def _act(widget: Widget, act: Act | None) -> None:
    if act is not None:
        widget.post_message(Acted(act))


class Part:
    """A widget that draws one spec and can take a new spec of the same kind in place."""

    spec: Any

    def patch(self, el: Any) -> bool:
        return False


def _wrap_line(line: Text, width: int) -> list[Text]:
    plain, n, start = line.plain, len(line.plain), 0
    out: list[Text] = []
    while n - start > width:
        end = start + width
        space = plain.rfind(" ", start, end + 1)
        if space > start:
            piece = line[start:space]
            piece.rstrip()
            out.append(piece)
            start = space + 1
            while start < n and plain[start] == " ":
                start += 1
            continue
        brk = max(plain.rfind(c, start, end) for c in BREAKS)
        stop = brk + 1 if brk >= start else end
        out.append(line[start:stop])
        start = stop
    out.append(line[start:])
    return out


def wrap_text(text: Text, width: int) -> list[Text]:
    """Word wrap. A word longer than the line breaks after `/ . : -`, else where it must."""
    width = max(1, width)
    out: list[Text] = []
    for line in text.split("\n", allow_blank=True):
        out += _wrap_line(line, width)
    return out


def cut_start(text: Text, width: int) -> Text:
    """One line, cut at the start with `…` so the end (a file or folder name) stays."""
    if text.cell_len <= width:
        return text
    head = text.blank_copy("…")
    head.append_text(text[len(text.plain) - max(0, width - 1) :])
    return head


class DetailText(Part, Widget):
    DEFAULT_CSS = """
    DetailText { height: auto; }
    """

    def __init__(self, el: TextEl) -> None:
        super().__init__(classes=el.cls or None)
        self.spec = el
        self.tooltip = el.tip or None

    def patch(self, el: TextEl) -> bool:
        if el.cls != self.spec.cls:
            return False
        self.spec = el
        self.tooltip = el.tip or None
        self.refresh(layout=True)
        return True

    def _lines(self, width: int) -> list[Text]:
        el: TextEl = self.spec
        return [cut_start(el.text, width)] if el.cut == "start" else wrap_text(el.text, width)

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return max(1, len(self._lines(width)))

    def render(self) -> Text:
        return Text("\n", no_wrap=True, end="").join(self._lines(self.size.width))


class Pressable(Widget):
    """Hover, focus, and pressed backgrounds, and the `▌` focus bar in the gutter."""

    COMPONENT_CLASSES: ClassVar[set[str]] = {"row--bar"}

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.add_class("-pressed")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.remove_class("-pressed")

    def on_leave(self, event: events.Leave) -> None:
        self.remove_class("-pressed")

    def _gutter(self) -> Text:
        bar = BAR if self.has_focus else " "
        return Text(bar.ljust(GUTTER), self.get_component_rich_style("row--bar", partial=True))


def _cut(text: Text, width: int, start: bool = False) -> Text:
    if text.cell_len <= width:
        return text
    if start:
        return cut_start(text, max(0, width))
    text = text.copy()
    text.truncate(max(0, width), overflow="ellipsis")
    return text


def _fit(left: Text, right: Text | None, width: int, keep: str, head: bool = False) -> Text:
    """Left text, then right text at the right edge. `keep` names the side that is not cut;
    `head` cuts the left text at its start."""
    right = right or Text()
    if keep == "left":
        left = _cut(left, width, head)
        right = _cut(right, width - left.cell_len - 1)
    else:
        right = _cut(right, width)
        left = _cut(left, width - right.cell_len - (1 if right.cell_len else 0), head)
    gap = max(0, width - left.cell_len - right.cell_len)
    return Text.assemble(left, " " * gap, right, no_wrap=True, end="")


class DetailRow(Part, Pressable):
    """A clickable row. Click, enter, or space runs its act."""

    DEFAULT_CSS = """
    DetailRow { height: auto; padding: 0 2 0 0; }
    DetailRow:hover { background: $atlas-surface-2; }
    DetailRow:focus { background: $atlas-selection; }
    DetailRow.-pressed { background: $atlas-surface-3; }
    DetailRow > .row--bar { color: $atlas-text; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "run", "Open", show=False),
    ]
    ALLOW_SELECT = False

    def __init__(self, el: RowEl) -> None:
        super().__init__(id=wid(el.id), classes=el.cls or None)
        self.spec = el
        self.can_focus = el.act is not None
        self.tooltip = el.tip or None

    def patch(self, el: RowEl) -> bool:
        if el.id != self.spec.id or el.cls != self.spec.cls:
            return False
        self.spec = el
        self.can_focus = el.act is not None
        self.tooltip = el.tip or None
        self.refresh(layout=True)
        return True

    def _sub(self, width: int) -> list[Text]:
        sub = self.spec.sub
        return [] if sub is None else wrap_text(sub, max(1, width - GUTTER))

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return 1 + len(self._sub(width))

    def render(self) -> Text:
        el: RowEl = self.spec
        width = max(0, self.size.width - GUTTER)
        head = el.cut == "start"
        line = Text.assemble(self._gutter(), _fit(el.left, el.right, width, el.keep, head))
        subs = [Text.assemble(" " * GUTTER, x) for x in self._sub(self.size.width)]
        return Text("\n", no_wrap=True, end="").join([line, *subs])

    def action_run(self) -> None:
        _act(self, self.spec.act)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if self.spec.act is not None:
            self.focus(scroll_visible=False)
            _act(self, self.spec.act)


class DetailHints(Part, Widget, can_focus=True):
    """Action hints that wrap to the width. One focus stop; arrows move between hints.

    Each hint takes clicks on its label and one cell each side, and acts on mouse up.
    """

    DEFAULT_CSS = """
    DetailHints { height: auto; }
    DetailHints > .hint--key { color: $atlas-accent; }
    DetailHints > .hint--label { color: $atlas-text; }
    DetailHints > .hint--link { color: $atlas-accent; }
    DetailHints > .hint--busy { color: $atlas-muted; }
    DetailHints > .hint--done { color: $atlas-on; }
    DetailHints > .hint--danger { color: $atlas-danger; }
    DetailHints > .hint--warn { color: $atlas-warn; }
    DetailHints > .hint--hover { background: $atlas-surface-2; }
    DetailHints > .hint--danger-hover { background: $atlas-danger-tint; }
    DetailHints > .hint--focus { background: $atlas-selection; }
    DetailHints > .hint--pressed { background: $atlas-surface-3; }
    DetailHints > .hint--primary { background: $atlas-accent; color: $atlas-on-accent; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "hint--key",
        "hint--label",
        "hint--link",
        "hint--busy",
        "hint--done",
        "hint--danger",
        "hint--warn",
        "hint--hover",
        "hint--danger-hover",
        "hint--focus",
        "hint--pressed",
        "hint--primary",
    }
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "run", "Run", show=False),
        Binding("left", "step(-1)", "Previous", show=False),
        Binding("right", "step(1)", "Next", show=False),
    ]
    ALLOW_SELECT = False

    def __init__(self, el: HintsEl) -> None:
        super().__init__(id=wid(el.id), classes=el.cls or None)
        self.spec = el
        self.cursor = 0
        self._hover: int | None = None
        self._pressed: int | None = None

    @property
    def hints(self) -> tuple[Hint, ...]:
        return self.spec.hints

    def patch(self, el: HintsEl) -> bool:
        if el.id != self.spec.id or el.cls != self.spec.cls:
            return False
        self.spec = el
        self.cursor = min(self.cursor, max(0, len(el.hints) - 1))
        self._hover = self._pressed = None
        self.refresh(layout=True)
        return True

    @staticmethod
    def _cells(h: Hint) -> int:
        return len(h.label) + (len(h.key) + 1 if h.key else 0) + 2

    def _layout(self, width: int) -> list[tuple[int, int, int]]:
        """(line, x, width) for each hint; a gap of one cell between hints."""
        out, line, x = [], 0, 0
        for h in self.hints:
            w = self._cells(h)
            if x and x + w > width:
                line, x = line + 1, 0
            if not x and h.tone == "primary":
                x = 1
            out.append((line, x, w))
            x += w + 1
        return out

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        spots = self._layout(width)
        return spots[-1][0] + 1 if spots else 0

    def _style(self, name: str) -> Style:
        return self.get_component_rich_style(name, partial=True)

    def render(self) -> Text:
        spots = self._layout(self.size.width)
        lines = [Text(no_wrap=True, end="") for _ in range(spots[-1][0] + 1 if spots else 1)]
        for i, (h, (row, x, _)) in enumerate(zip(self.hints, spots, strict=True)):
            line = lines[row]
            line.append(" " * (x - line.cell_len))
            line.append_text(self._hint(i, h))
        return Text("\n", end="").join(lines)

    def _hint(self, i: int, h: Hint) -> Text:
        tone = h.tone
        toned = tone in ("busy", "done", "danger", "warn")
        link = not toned and not tone and not h.key and h.act is not None
        label = self._style(f"hint--{tone}" if toned else "hint--link" if link else "hint--label")
        key = self._style("hint--key")
        bg = Style()
        if tone == "primary":
            bg = self._style("hint--primary")
            key = label = Style()
        if h.act is not None:
            if i == self._pressed:
                bg = self._style("hint--pressed")
            elif self.has_focus and i == self.cursor:
                bg = self._style("hint--focus")
            elif i == self._hover:
                bg = self._style("hint--danger-hover" if tone == "danger" else "hint--hover")
        text = Text(" ", no_wrap=True, end="")
        if h.key:
            text.append(h.key, key).append(" ")
        text.append(h.label, label).append(" ")
        text.stylize(bg)
        return text

    def _at(self, event: events.MouseEvent) -> int | None:
        offset = event.get_content_offset(self)
        if offset is None:
            return None
        for i, (row, x, w) in enumerate(self._layout(self.size.width)):
            if row == offset.y and x <= offset.x < x + w:
                return i
        return None

    def move(self, step: int) -> bool:
        """Move the cursor inside the bar; False at either end."""
        to = self.cursor + step
        if not 0 <= to < len(self.hints):
            return False
        self.cursor = to
        self.refresh()
        return True

    def action_step(self, step: int) -> None:
        self.move(step)

    def action_run(self) -> None:
        if self.hints:
            _act(self, self.hints[self.cursor].act)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        i = self._at(event)
        if i != self._hover:
            self._hover = i
            tip = self.hints[i].tip if i is not None else ""
            self.tooltip = tip or None
            self.refresh()

    def on_leave(self, event: events.Leave) -> None:
        self._hover = self._pressed = None
        self.tooltip = None
        self.refresh()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        i = self._at(event)
        self._pressed = i if i is not None and self.hints[i].act is not None else None
        self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._pressed is not None:
            self._pressed = None
            self.refresh()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        i = self._at(event)
        if i is None or self.hints[i].act is None:
            return
        self.cursor = i
        self.focus(scroll_visible=False)
        _act(self, self.hints[i].act)


class DetailSwitch(Part, ToggleSwitch):
    """The title switch. It can show mixed (`━◐━`) for a group that is partly on."""

    def __init__(self, el: SwitchEl) -> None:
        super().__init__(el.on, label=el.tip, id=wid(el.id), disabled=el.disabled)
        self.spec = el
        self.mixed = el.mixed

    def patch(self, el: SwitchEl) -> bool:
        if el.id != self.spec.id or bool(el.label) != bool(self.spec.label):
            return False
        self.spec = el
        self.label = el.tip
        self.mixed = el.mixed
        self.disabled = el.disabled
        self.reason = el.reason
        self.on = el.on
        self._sync_tooltip()
        self.refresh()
        return True

    def toggle(self) -> None:
        self.mixed = False
        self.on = not self.on
        self.post_message(Acted(self.spec.act, self.on))

    def _switch(self) -> Text:
        if not self.mixed or self.disabled or self._moving:
            return super().render()
        style = self.get_component_rich_style
        colors = {
            "atlas-on": _hex(style("toggleswitch--on", partial=True)),
            "atlas-off": _hex(style("toggleswitch--off", partial=True)),
            "atlas-muted": _hex(style("toggleswitch--knob-off", partial=True)),
        }
        return charts.switch("mixed", colors, tip=None)

    def render(self) -> Text:
        return self._switch()


def _hex(style: Style) -> str:
    return style.color.get_truecolor().hex if style.color else ""


class HarnessSwitch(DetailSwitch):
    """A Loaded by row: the harness at the left; the switch and `on` or `off` at the right."""

    DEFAULT_CSS = """
    HarnessSwitch { width: 1fr; padding: 0 2 0 0; }
    HarnessSwitch.-current, HarnessSwitch.-current:disabled { background: $atlas-surface-2; }
    HarnessSwitch.-current:hover, HarnessSwitch.-current.-pressed {
        background: $atlas-surface-3;
    }
    HarnessSwitch.-current:focus { background: $atlas-selection; }
    HarnessSwitch > .harness--label { color: $atlas-muted; }
    HarnessSwitch.-current > .harness--label { color: $atlas-text; }
    HarnessSwitch > .row--bar { color: $atlas-text; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {"harness--label", "row--bar"}
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("x", "toggle_switch", "Toggle", show=False),
    ]

    def __init__(self, el: SwitchEl) -> None:
        super().__init__(el)
        self.show_state = True
        self.reason = el.reason
        self.set_class(el.current, "-current")

    def patch(self, el: SwitchEl) -> bool:
        if not super().patch(el):
            return False
        self.set_class(el.current, "-current")
        return True

    def render(self) -> Text:
        switch = self._switch()
        width = self.size.width
        bar = BAR if self.has_focus else " "
        gutter = Text(bar.ljust(GUTTER), self.get_component_rich_style("row--bar", partial=True))
        label = Text(self.spec.label, self.get_component_rich_style("harness--label", partial=True))
        return Text.assemble(gutter, _fit(label, switch, width - GUTTER, "right"))


class CloseX(Static):
    """The ✕ that closes the panel."""

    DEFAULT_CSS = """
    CloseX { width: 3; height: 1; content-align: center middle; color: $atlas-muted; }
    CloseX:hover { background: $atlas-surface-2; color: $atlas-text; }
    """

    def __init__(self) -> None:
        super().__init__("✕")
        self.tooltip = "Close the panel"

    def on_click(self, event: events.Click) -> None:
        event.stop()
        _act(self, Act("close"))


class TitleRow(Part, Horizontal):
    DEFAULT_CSS = """
    TitleRow { height: auto; padding: 0 1 0 2; }
    TitleRow > Static.title { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    TitleRow > DetailSwitch { margin: 0 1 0 0; }
    """

    def __init__(self, el: TitleEl) -> None:
        title = Static(el.text, classes="title")
        title.tooltip = el.text.plain
        kids: list[Widget] = [title]
        if el.switch is not None:
            kids.append(DetailSwitch(el.switch))
        if el.close:
            kids.append(CloseX())
        super().__init__(*kids)
        self.spec = el

    def patch(self, el: TitleEl) -> bool:
        old: TitleEl = self.spec
        if (el.switch is None) != (old.switch is None) or el.close != old.close:
            return False
        if el.switch is not None and not self.query_one(DetailSwitch).patch(el.switch):
            return False
        title = self.query_one(".title", Static)
        title.update(el.text)
        title.tooltip = el.text.plain
        self.spec = el
        return True


class DefList(Part, Widget):
    """Rows of a muted label column and a value that wraps under itself."""

    DEFAULT_CSS = """
    DefList { height: auto; }
    DefList > .def--label { color: $atlas-muted; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {"def--label"}

    def __init__(self, el: DefEl) -> None:
        super().__init__()
        self.spec = el

    def patch(self, el: DefEl) -> bool:
        self.spec = el
        self.refresh(layout=True)
        return True

    def _label_w(self) -> int:
        el: DefEl = self.spec
        names = [label.plain if isinstance(label, Text) else label for label, _ in el.rows]
        longest = max(map(len, names), default=0)
        return el.label_w or max(LABEL_W, longest + 2)

    def _lines(self, width: int) -> list[tuple[Text, str | None]]:
        el: DefEl = self.spec
        label_style = self.get_component_rich_style("def--label", partial=True)
        label_w = self._label_w()
        room = max(8, width - label_w)
        out: list[tuple[Text, str | None]] = []
        for label, value in el.rows:
            name = label if isinstance(label, Text) else Text(label, label_style)
            cut = name.plain in el.cut
            parts = [cut_start(value, room)] if cut else wrap_text(value, room)
            tip = value.plain if cut and value.cell_len > room else None
            for i, part in enumerate(parts):
                head = name.copy() if i == 0 else Text("")
                head.pad_right(label_w - head.cell_len)
                out.append((Text.assemble(head, part, no_wrap=True, end=""), tip))
        return out

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return max(1, len(self._lines(width)))

    def render(self) -> Text:
        return Text("\n", no_wrap=True, end="").join(t for t, _ in self._lines(self.size.width))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        offset = event.get_content_offset(self)
        lines = self._lines(self.size.width)
        tip = lines[offset.y][1] if offset is not None and 0 <= offset.y < len(lines) else None
        self.tooltip = tip

    def on_leave(self, event: events.Leave) -> None:
        self.tooltip = None


class HeatView(Part, charts.Heatmap):
    def __init__(self, el: HeatEl) -> None:
        super().__init__(dict(el.days), weeks=26, today=el.today, note=el.note, id="d-heat")
        self.spec = el

    def patch(self, el: HeatEl) -> bool:
        self.spec = el
        self.today = el.today
        self.note = el.note
        self.days = dict(el.days)
        self.refresh(layout=True)
        return True


class SparkView(Part, Static):
    """A sparkline whose cells carry week tooltips."""

    DEFAULT_CSS = """
    SparkView { height: 1; }
    """

    def __init__(self, el: SparkEl) -> None:
        super().__init__(el.text)
        self.spec = el

    def patch(self, el: SparkEl) -> bool:
        self.spec = el
        self.update(el.text)
        return True

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self.tooltip = charts.tip_of(event.style)


class Bars(Part, charts.BarChart):
    """Top skills by uses. A click opens the skill."""

    def __init__(self, el: BarsEl) -> None:
        super().__init__(el.rows, fmt=lambda v: f"{int(v):,}", id=wid(el.id))
        self.spec = el

    def patch(self, el: BarsEl) -> bool:
        if el.id != self.spec.id:
            return False
        self.spec = el
        self.rows = el.rows
        return True

    def on_bar_chart_selected(self, event: charts.BarChart.Selected) -> None:
        event.stop()
        _act(self, self.spec.acts[event.index])


class DetailSkeleton(Part, Widget):
    """Bars of `$atlas-surface-2` that hold the place of text while it loads."""

    DEFAULT_CSS = """
    DetailSkeleton { height: auto; }
    DetailSkeleton > .skel--bar { background: $atlas-surface-2; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {"skel--bar"}

    def __init__(self, el: SkelEl) -> None:
        super().__init__()
        self.spec = el

    def patch(self, el: SkelEl) -> bool:
        grow = len(el.widths) != len(self.spec.widths)
        self.spec = el
        self.refresh(layout=grow)
        return True

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return len(self.spec.widths)

    def render(self) -> Text:
        bar = self.get_component_rich_style("skel--bar", partial=True)
        width = self.size.width
        return Text("\n", end="").join(
            Text(" " * max(1, round(width * f)), bar, end="") for f in self.spec.widths
        )


class DetailBox(Part, Vertical):
    DEFAULT_CSS = """
    DetailBox { height: auto; }
    """

    def __init__(self, el: BoxEl) -> None:
        super().__init__(*(make(x) for x in el.items), id=wid(el.key, "b"), classes=el.cls or None)
        self.spec = el


def make(el: El) -> Widget:
    """A new widget for a spec."""
    if isinstance(el, TextEl):
        return DetailText(el)
    if isinstance(el, HintsEl):
        return DetailHints(el)
    if isinstance(el, RowEl):
        return DetailRow(el)
    if isinstance(el, SwitchEl):
        return HarnessSwitch(el) if el.label else DetailSwitch(el)
    if isinstance(el, TitleEl):
        return TitleRow(el)
    if isinstance(el, DefEl):
        return DefList(el)
    if isinstance(el, HeatEl):
        return HeatView(el)
    if isinstance(el, SparkEl):
        return SparkView(el)
    if isinstance(el, BarsEl):
        return Bars(el)
    if isinstance(el, SkelEl):
        return DetailSkeleton(el)
    return DetailBox(el)


def _fits(w: Widget, el: El) -> bool:
    if not isinstance(w, Part) or type(w.spec) is not type(el):
        return False
    spec: Any = w.spec
    if isinstance(el, BoxEl):
        return bool(spec.key == el.key)
    if isinstance(el, SwitchEl):
        return bool(spec.id == el.id and bool(spec.label) == bool(el.label))
    return getattr(spec, "id", None) == getattr(el, "id", None)


async def reconcile(parent: Widget, items: Sequence[El]) -> None:
    """Make parent's children draw items: keep equal ones, patch alike ones, replace the rest."""
    old = list(parent.children)
    keep: list[Widget | None] = []
    for i, el in enumerate(items):
        w = old[i] if i < len(old) else None
        if w is None or not _fits(w, el):
            keep.append(None)
            continue
        assert isinstance(w, Part)
        if w.spec == el:
            keep.append(w)
        elif isinstance(w, DetailBox) and isinstance(el, BoxEl):
            await reconcile(w, el.items)
            w.set_classes(el.cls)
            w.spec = el
            keep.append(w)
        else:
            keep.append(w if w.patch(el) else None)
    kept = {id(w) for w in keep if w is not None}
    gone = [w for w in old if id(w) not in kept]
    if gone:
        await parent.remove_children(gone)
    if not kept:
        if items:
            await parent.mount_all([make(el) for el in items])
        return
    i = 0
    while i < len(items):
        if keep[i] is not None:
            i += 1
            continue
        j = i
        while j < len(items) and keep[j] is None:
            j += 1
        fresh = [make(el) for el in items[i:j]]
        if i == 0:
            await parent.mount(*fresh, before=keep[j])
        else:
            await parent.mount(*fresh, after=keep[i - 1])
        keep[i:j] = fresh
        i = j
