"""The panel that shows in the detail area when no skill is selected.

Two lines of counts, the items that need you, then the other sections behind one row. Every
control works with the mouse alone, and with tab, up and down, and enter or space.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events, work
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.geometry import Size
from textual.screen import Screen
from textual.widget import Widget

from ...core import views
from .. import state, theme
from ..messages import DataChanged, SkillSelected, StateChanged
from . import app_of, charts

if TYPE_CHECKING:
    from ..app import AtlasApp

Seg = tuple[str, str] | Text
Cue = tuple[str, str] | None

SHORT = 30
OPEN = ":open"
ATTN = "inv.attn"
MORE = "inv.more"
DISPLAY = "inv.disp"
DEFAULT_OPEN = frozenset({ATTN})
PANES = (
    (ATTN, "Needs attention"),
    ("inv.use", "Usage"),
    ("inv.cost", "Context cost"),
    ("inv.ovl", "Overlap"),
    ("inv.sec", "Security"),
    ("inv.prof", "Profiles"),
    ("inv.set", "Skill set"),
    (DISPLAY, "Display"),
)
# The sections that hide while the skill folders are read-only.
WRITE_ONLY = frozenset({"inv.use", "inv.prof", "inv.set"})
# Shorter names for the More row, so the default panel width shows every section.
MORE_NAMES = {"inv.cost": "cost"}
LABEL_W = 12
TONES = ("text", "muted", "faint", "accent", "on", "warn", "danger", "strong", "bar", "active")
# Tokens that the chart renderers read, and the tone that holds each one.
CHART_TONES = {
    "atlas-text": "text",
    "atlas-muted": "muted",
    "atlas-faint": "faint",
    "atlas-accent": "accent",
    "atlas-on": "on",
    "atlas-off": "off",
    "atlas-spark": "spark",
    "atlas-border": "border",
}
NBSP, GLUE = "\u00a0", "\ue000"
GLYPHS = {"danger": "✗", "warn": "!", "ok": "✓"}
COUNTS = (
    ("on", "on", "on", "on"),
    ("off", "off", "off", "text"),
    ("updates", "update", "updates", "accent"),
)
COUNT_TIPS = {
    "on": "Show the skills that are on",
    "off": "Show the skills that are off",
    "updates": "Show the skills that have updates",
}
FACTS = (
    ("untracked", "untracked", "untracked"),
    ("duplicates", "duplicate", "duplicates"),
    ("edited", "edited", "edited"),
)
MODE_LABELS = {"system": "System", "light": "Light", "dark": "Dark"}
SORT_LABELS = {"name": "Name", "uses": "Most used", "recent": "Recent", "cost": "Cost"}
GROUP_LABELS = {"source": "Source", "type": "Scope"}
CHECKS = (
    ("row_detail", "Show descriptions in the list"),
    ("compact", "Compact rows"),
    ("show_project", "Show project skills"),
    ("show_stale", "Show old plugin versions"),
    ("key_hints", "Show keyboard hints"),
)
CHECK_TIPS = {"row_detail": "Rows also show the sparkline and every tag."}
SIZE_LABELS = {"regular": "Regular", "large": "Large"}
MOTION_LABELS = {"full": "Full", "reduced": "Reduced", "off": "Off"}
DISPLAY_FIELDS = frozenset(
    {"palette", "mode", "group_by", "sort", "group_size", "motion", "detail_open"}
    | {f for f, _ in CHECKS}
)
DATA_DELAY = 0.05
DATA_FIELDS = frozenset({"harness", "show_project", "show_stale", "folded"})
SHOW_FIELDS = frozenset({"selected", "selected_key", "detail_open"})
COST_NOTE = "Estimate: about 4 characters per token. A skill's body loads only when it runs."
SET_LEAD = (
    "Save your skills, sources, and switches to a file. "
    "Import the file on a different computer to get the same set."
)
NO_PROFILES = (
    "No profiles yet. A profile keeps which skills are on and off, "
    "so you can switch them all in one step."
)
ALL_CLEAR = "Nothing needs your attention. The skill folders and lock files have no problems."
IMPORT_NOTE = "Import… asks for the path of a file that Skill Atlas exported."


def section_open(folded: frozenset[str], key: str, default: bool) -> bool:
    """A section the user folded or opened stays so; the others use the default."""
    if key in folded:
        return False
    return True if key + OPEN in folded else default


def with_section(folded: frozenset[str], key: str, open: bool) -> frozenset[str]:
    """`folded` with the user's choice for one section: `key` folded, `key:open` open."""
    return (folded - {key, key + OPEN}) | {key + OPEN if open else key}


def facts(inv: dict[str, int]) -> list[str]:
    """The faint second line: untracked, duplicate, and edited counts that are not zero."""
    return [f"{n:,} {one if n == 1 else many}" for key, one, many in FACTS if (n := inv.get(key))]


def more_names(writable: bool) -> list[str]:
    """The sections behind More, as the More row names them."""
    names = [MORE_NAMES.get(k, t) for k, t in PANES[1:] if writable or k not in WRITE_ONLY]
    return [n[:1].upper() + n[1:] if i == 0 else n.lower() for i, n in enumerate(names)]


def _cut(text: Text, width: int) -> Text:
    if text.cell_len <= width:
        return text
    out = text.copy()
    out.truncate(max(0, width), overflow="ellipsis")
    return out


async def call_feature(app: AtlasApp, module: str, func: str, *args: Any) -> None:
    """Run `skill_atlas.tui.<module>.<func>(app, *args)`; a toast says so if it is not built."""
    name = f"skill_atlas.tui.{module}"
    try:
        fn = getattr(importlib.import_module(name), func, None)
    except ModuleNotFoundError as e:
        if e.name != name:
            raise
        fn = None
    if fn is None:
        app.notify("This action does not work yet.", severity="warning")
        return
    result = fn(app, *args)
    if inspect.isawaitable(result):
        await result


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------


class Toned(Widget):
    """Paints text in the theme's tones, through its component classes."""

    DEFAULT_CSS = """
    Toned > .row--text { color: $atlas-text; }
    Toned > .row--muted { color: $atlas-muted; }
    Toned > .row--faint { color: $atlas-faint; }
    Toned > .row--accent { color: $atlas-accent; }
    Toned > .row--on { color: $atlas-on; }
    Toned > .row--warn { color: $atlas-warn; }
    Toned > .row--danger { color: $atlas-danger; }
    Toned > .row--strong { color: $atlas-text; text-style: bold; }
    Toned > .row--bar { color: $atlas-text; }
    Toned > .row--active { color: $atlas-text; background: $atlas-surface-3; }
    Toned > .row--link { color: $atlas-muted; }
    Toned:hover > .row--link, Toned:focus > .row--link { color: $atlas-accent; }
    Toned > .row--off { color: $atlas-off; }
    Toned > .row--spark { color: $atlas-spark; }
    Toned > .row--border { color: $atlas-border; }
    Toned:disabled > .row--text { color: $atlas-faint; }
    Toned:disabled > .row--muted { color: $atlas-faint; }
    Toned:disabled > .row--warn { color: $atlas-faint; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        f"row--{t}" for t in (*TONES, "link", "off", "spark", "border")
    }
    ALLOW_SELECT = False

    def tone(self, name: str) -> Style:
        return self.get_component_rich_style(f"row--{name}", partial=True)

    def palette(self) -> dict[str, str]:
        """The chart tokens as hex, from this widget's styles, so they follow the theme."""
        out = {}
        for token, name in CHART_TONES.items():
            color = self.tone(name).color
            if color is not None:
                out[token] = color.get_truecolor().hex
        return out

    def paint(self, segs: Sequence[Seg]) -> Text:
        out = Text(end="")
        for seg in segs:
            if isinstance(seg, Text):
                out.append_text(seg)
            else:
                out.append(seg[0], self.tone(seg[1]))
        return out

    def bar(self) -> Text:
        """The focus bar and its gap: `▌ ` when focused, else two spaces."""
        return Text("▌ " if self.has_focus else "  ", self.tone("bar"), end="")

    def on_focus(self, event: events.Focus) -> None:
        self.refresh()

    def on_blur(self, event: events.Blur) -> None:
        self.refresh()


class PanelRow(Toned):
    """A panel line: text under an optional glyph, wrapped, with the focus bar in col 0.

    `right` sits at the right edge of the first line. `keep_right` cuts the text, not `right`.
    """

    DEFAULT_CSS = """
    PanelRow { height: auto; width: 1fr; }
    """

    def __init__(
        self,
        segs: Sequence[Seg] = (),
        *,
        glyph: tuple[str, str] | None = None,
        right: Sequence[Seg] = (),
        keep_right: bool = False,
        tip: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled)
        self.segs = list(segs)
        self.glyph = glyph
        self.right = list(right)
        self.keep_right = keep_right
        if tip:
            self.tooltip = tip

    def set(self, segs: Sequence[Seg], right: Sequence[Seg] = ()) -> None:
        segs, right = list(segs), list(right)
        if (segs, right) != (self.segs, self.right):
            self.segs, self.right = segs, right
            self.refresh(layout=True)

    def lines(self, width: int) -> list[Text]:
        inner = max(1, width - 4)
        lead = Text(end="")
        if self.glyph:
            lead = Text(self.glyph[0] + " ", self.tone(self.glyph[1]), end="")
        room = max(1, inner - lead.cell_len)
        text = self.paint(self.segs)
        # Rich breaks at U+00A0, so a one-cell stand-in keeps a link's words on one line.
        text.plain = text.plain.replace(NBSP, GLUE)
        rows = list(text.wrap(self.app.console, room)) or [Text(end="")]
        out = []
        for i, line in enumerate(rows):
            line.plain = line.plain.replace(GLUE, " ")
            line.rstrip()
            row = self.bar().append_text(lead if i == 0 else Text(" " * lead.cell_len))
            if i == 0 and self.right:
                right = self.paint(self.right)
                if self.keep_right:
                    line = _cut(line, room - right.cell_len - 2)
                else:
                    right = _cut(right, max(0, room - line.cell_len - 2))
                gap = " " * max(1, room - line.cell_len - right.cell_len)
                row.append_text(line).append(gap).append_text(right)
            else:
                row.append_text(line)
            out.append(row.append(" " * max(0, width - row.cell_len)))
        return out

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return len(self.lines(width))

    def render(self) -> Text:
        if not self.size.width:
            return Text()
        return Text("\n", end="").join(self.lines(self.size.width))


class Line(PanelRow):
    """Text that does nothing when clicked."""


class Drawn(Line):
    """A line that a chart renderer draws from the current theme, such as a spark or a meter."""

    def __init__(self, draw: Callable[[dict[str, str]], Text], **kw: Any) -> None:
        super().__init__((), **kw)
        self.draw = draw

    def lines(self, width: int) -> list[Text]:
        self.segs = [self.draw(self.palette())]
        return super().lines(width)


class Act(PanelRow, can_focus=True):
    """A row that runs `do` on a click, enter, or space."""

    DEFAULT_CSS = """
    Act:hover { background: $atlas-surface-2; }
    Act:focus { background: $atlas-selection; }
    Act.-pressed { background: $atlas-surface-3; }
    Act:disabled { background: transparent; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "press", "Run", show=False),
    ]

    def __init__(
        self,
        segs: Sequence[Seg] = (),
        *,
        do: Callable[[], object] | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(segs, **kw)
        self.do = do

    async def press(self) -> None:
        result = self.do() if self.do is not None else None
        if inspect.isawaitable(result):
            # On the app, so the work goes on when the panel builds this row again.
            self.app.run_worker(result, group="side-press")

    async def action_press(self) -> None:
        await self.press()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.add_class("-pressed")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.remove_class("-pressed")

    def on_leave(self, event: events.Leave) -> None:
        self.remove_class("-pressed")

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        await self.press()


class Chip(Act):
    """A button: its label on a background step, with no focus bar."""

    DEFAULT_CSS = """
    Chip { width: auto; height: 1; background: $atlas-surface-2; margin-right: 2; }
    Chip:last-child { margin-right: 0; }
    Chip:hover { background: $atlas-surface-3; }
    """

    def get_content_width(self, container: Size, viewport: Size) -> int:
        return self.paint(self.segs).cell_len + 2

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return 1

    def render(self) -> Text:
        return Text(" ", end="").append_text(self.paint(self.segs)).append(" ")


class Tile(Act):
    """A number above its label that opens a view. At zero it is disabled."""

    DEFAULT_CSS = """
    Tile { width: 1fr; height: 2; padding: 0 1; }
    """

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return 2

    def render(self) -> Text:
        return self.paint(self.segs)


class Entry(Act):
    """An action on one line: the glyph, the text cut to fit, and `right` at the right edge."""

    def lines(self, width: int) -> list[Text]:
        row = self.bar()
        if self.glyph:
            row.append(self.glyph[0] + " ", self.tone(self.glyph[1]))
        right = self.paint(self.right)
        room = max(1, width - 2 - row.cell_len - right.cell_len)
        text = _cut(self.paint(self.segs), room - (2 if right else 0))
        row.append_text(text).append(" " * max(0, room - text.cell_len)).append_text(right)
        return [row.append(" " * max(0, width - row.cell_len))]


class Brief(Line):
    """Faint phrases on one line. Phrases that do not fit become `…`; the tooltip has them all."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.parts: list[str] = []

    def show(self, parts: list[str]) -> None:
        self.display = bool(parts)
        if parts != self.parts:
            self.parts = parts
            self._tip(self.size.width)
            self.refresh()

    def fit(self, width: int) -> str:
        room = width - 4
        for n in range(len(self.parts), 0, -1):
            text = ", ".join(self.parts[:n]) + ("" if n == len(self.parts) else ", …")
            if cell_len(text) <= room:
                return text
        return _cut(Text(", ".join(self.parts)), max(1, room)).plain

    def lines(self, width: int) -> list[Text]:
        row = self.bar().append(self.fit(width), self.tone("faint"))
        return [row.append(" " * max(0, width - row.cell_len))]

    def _tip(self, width: int) -> None:
        full = ", ".join(self.parts)
        self.tooltip = full if width and self.fit(width) != full else None

    def on_resize(self, event: events.Resize) -> None:
        self._tip(event.size.width)


class Counts(Line):
    """On, off, and updates. A count that is not zero is a link to its view."""

    DEFAULT_CSS = """
    Counts.-link { pointer: pointer; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.parts: list[tuple[str, str, str, str]] = []
        self._hits: list[tuple[int, int, int, str]] = []
        self._hover: str | None = None

    def show(self, parts: list[tuple[str, str, str, str]]) -> None:
        """Each part is (view or "", number, tint, word)."""
        if parts != self.parts:
            self.parts = parts
            self.refresh(layout=True)

    def lines(self, width: int) -> list[Text]:
        rows, self._hits = [self.bar()], []
        for view, number, tint, word in self.parts:
            hot = bool(view) and view == self._hover
            text = Text(number, self.tone(tint), end="")
            text.append(" " + word, self.tone("accent" if hot else "muted"))
            row = rows[-1]
            if row.cell_len > 2 and row.cell_len + 3 + text.cell_len > width - 2:
                row = self.bar()
                rows.append(row)
            elif row.cell_len > 2:
                row.append("   ")
            if view:
                self._hits.append((len(rows) - 1, row.cell_len, row.cell_len + text.cell_len, view))
            row.append_text(text)
        return [r.append(" " * max(0, width - r.cell_len)) for r in rows]

    def _hit(self, event: events.MouseEvent) -> str | None:
        offset = event.get_content_offset(self)
        if offset is None:
            return None
        return next(
            (v for y, x0, x1, v in self._hits if offset.y == y and x0 <= offset.x < x1), None
        )

    def _set_hover(self, view: str | None) -> None:
        if view != self._hover:
            self._hover = view
            self.tooltip = COUNT_TIPS.get(view or "")
            self.set_class(view is not None, "-link")
            self.refresh()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self._set_hover(self._hit(event))

    def on_leave(self, event: events.Leave) -> None:
        self._set_hover(None)

    def on_click(self, event: events.Click) -> None:
        if (view := self._hit(event)) is not None:
            event.stop()
            app_of(self).set_state(view=view)


class More(Act):
    """Shows or hides the other sections. Folded, it names them in two lines at most."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.open = False
        self.names: list[str] = []

    def show(self, open: bool, names: list[str]) -> None:
        if (open, names) != (self.open, self.names):
            self.open, self.names = open, names
            self._tip(self.size.width)
            self.refresh(layout=True)

    def fit(self, width: int) -> list[str]:
        """The names on two lines at most. Names that do not fit become `…`."""
        room = max(1, width - 7)
        glued = [n.replace(" ", GLUE) for n in self.names]
        for n in range(len(glued), 0, -1):
            text = ", ".join(glued[:n]) + ("" if n == len(glued) else ", …")
            rows = [r.plain.replace(GLUE, " ") for r in Text(text).wrap(self.app.console, room)]
            if len(rows) <= 2:
                return rows
        return [_cut(Text(", ".join(self.names)), room).plain]

    def lines(self, width: int) -> list[Text]:
        if self.open:
            row = self.bar().append("Show less", self.tone("muted"))
            return [row.append(" " * max(0, width - row.cell_len))]
        out = []
        for i, line in enumerate(self.fit(width) or ["More"]):
            row = self.bar().append(line, self.tone("faint"))
            if i == 0:
                row.append(" " * max(1, width - 3 - row.cell_len)).append("›", self.tone("faint"))
            out.append(row.append(" " * max(0, width - row.cell_len)))
        return out

    def _tip(self, width: int) -> None:
        cut = not self.open and width and any("…" in line for line in self.fit(width))
        self.tooltip = ", ".join(self.names) if cut else None

    def on_resize(self, event: events.Resize) -> None:
        self._tip(event.size.width)


class PaneHead(Act):
    """`▾ LABEL`. Folded: `▸ LABEL` and, at the right, the summary or the cue that needs you."""

    def lines(self, width: int) -> list[Text]:
        return super().lines(width)[:1]


class Choice(Act):
    """A setting with a few values side by side. Left and right change it; a click picks one."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "shift(-1)", "Previous", show=False),
        Binding("right", "shift(1)", "Next", show=False),
    ]

    def __init__(
        self,
        label: str,
        setting: str,
        options: Sequence[tuple[str, str]],
        *,
        tips: dict[str, str] | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__((), id=id)
        self.label = label
        self.setting = setting
        self.options = list(options)
        self.tips = tips or {}
        self._hits: list[tuple[int, int, int, str]] = []
        self._hover: str | None = None

    @property
    def value(self) -> str:
        return str(getattr(app_of(self).state, self.setting))

    def pick(self, value: str) -> None:
        app_of(self).set_state(**{self.setting: value})
        self.refresh()

    def action_shift(self, step: int) -> None:
        ids = [v for v, _ in self.options]
        i = ids.index(self.value) if self.value in ids else 0
        self.pick(ids[(i + step) % len(ids)])

    async def press(self) -> None:
        self.action_shift(1)

    def option(self, value: str, label: str) -> Text:
        if value == self.value:
            return Text(f" {label} ", self.tone("active"), end="")
        return Text(f" {label} ", self.tone("text" if value == self._hover else "muted"), end="")

    def trailer(self) -> Text:
        return Text(end="")

    def lines(self, width: int) -> list[Text]:
        """The label, then the options in the value column; options that do not fit wrap
        to the next line in the same column."""
        start, end = 2 + LABEL_W, max(2 + LABEL_W + 1, width - 2)
        rows = [self.bar().append(self.label.ljust(LABEL_W), self.tone("muted"))]
        self._hits = []
        parts = [(v, self.option(v, t)) for v, t in self.options] + [("", self.trailer())]
        for value, text in parts:
            row = rows[-1]
            if row.cell_len > start and row.cell_len + text.cell_len > end:
                row = self.bar().append(" " * LABEL_W)
                rows.append(row)
            if value:
                x = row.cell_len
                self._hits.append((len(rows) - 1, x, x + text.cell_len, value))
            row.append_text(text)
        return [r.append(" " * max(0, width - r.cell_len)) for r in rows]

    def _hit(self, event: events.MouseEvent) -> str | None:
        offset = event.get_content_offset(self)
        if offset is None:
            return None
        return next(
            (v for y, x0, x1, v in self._hits if offset.y == y and x0 <= offset.x < x1), None
        )

    def on_mouse_move(self, event: events.MouseMove) -> None:
        hit = self._hit(event)
        if hit != self._hover:
            self._hover = hit
            self.tooltip = self.tips.get(hit or "")
            self.refresh()

    def on_leave(self, event: events.Leave) -> None:
        if self._hover is not None:
            self._hover = None
            self.refresh()

    async def on_click(self, event: events.Click) -> None:
        # Textual also runs Act.on_click; prevent_default stops it from pressing again.
        event.stop()
        event.prevent_default()
        hit = self._hit(event)
        if hit is None:
            await self.press()
        else:
            self.pick(hit)


class Swatches(Choice):
    """The palettes as dots in their accent colors; the name of the current one follows."""

    def option(self, value: str, label: str) -> Text:
        shade = "dark" if self.app.current_theme.dark else "light"
        accent = theme.THEMES[theme.name(value, shade)].variables["atlas-accent"]
        base = self.tone("active") if value == self.value else Style()
        return Text(" ● ", Style(bgcolor=base.bgcolor, color=accent), end="")

    def trailer(self) -> Text:
        return Text(f"  {dict(self.options).get(self.value, '')}", self.tone("text"), end="")


class Check(Act):
    """A setting that is on or off: its label at the left, its switch at the right."""

    def __init__(
        self, label: str, setting: str, *, tip: str | None = None, id: str | None = None
    ) -> None:
        super().__init__((), tip=tip, id=id)
        self.label = label
        self.setting = setting

    @property
    def on(self) -> bool:
        return bool(getattr(app_of(self).state, self.setting))

    async def press(self) -> None:
        app_of(self).set_state(**{self.setting: not self.on})
        self.refresh()

    def lines(self, width: int) -> list[Text]:
        knob = charts.switch(self.on, self.palette())
        row = self.bar().append_text(_cut(Text(self.label, self.tone("text")), width - 9))
        row.append(" " * max(1, width - 2 - row.cell_len - knob.cell_len)).append_text(knob)
        return [row.append("  ")]


class PanelCheck(Check):
    """Details panel: on while the panel shows. It works for the docked panel and the drawer."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__("Details panel", "detail_open", id=id)

    @property
    def on(self) -> bool:
        return app_of(self).detail_visible

    async def press(self) -> None:
        app = app_of(self)
        app.show_detail(not self.on)
        if not app.detail_visible:
            app.main.query_one("#list").focus()
        self.refresh()


class SideChart(charts.BarChart, can_focus=True):
    """A bar chart that the keyboard moves through. A click, enter, or space picks a row."""

    DEFAULT_CSS = """
    SideChart { width: 1fr; }
    SideChart > .sidechart--cursor { background: $atlas-selection; }
    SideChart > .sidechart--mark { color: $atlas-text; }
    SideChart > .sidechart--slash { color: $atlas-faint; }
    SideChart.-cost > .barchart--bar { color: $atlas-muted; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "sidechart--cursor",
        "sidechart--mark",
        "sidechart--slash",
    }
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up,k", "move(-1)", "Up", show=False),
        Binding("down,j", "move(1)", "Down", show=False),
        Binding("enter,space", "pick", "Pick", show=False),
    ]

    def __init__(
        self,
        rows: Sequence[tuple[str, float]],
        texts: Sequence[str],
        picks: Sequence[Callable[[], object]],
        *,
        fmt: Callable[[float], str] = lambda v: f"{v:,.0f}",
        tips: Sequence[str] = (),
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.texts = list(texts)
        self.picks = list(picks)
        self.tips = list(tips)
        self.cursor = 0
        super().__init__(rows, fmt=fmt, id=id, classes=classes)

    def _columns(self, width: int) -> tuple[int, int, int]:
        inner = width - 4
        num_w = max((cell_len(t) for t in self.texts), default=0)
        longest = max((cell_len(n) for n, _ in self.rows), default=0)
        label_w = min(longest, max(8, inner - num_w - 4 - 8))
        bar_w = inner - label_w - num_w - 4
        if bar_w < 4:
            bar_w, label_w = 0, max(0, inner - num_w - 1)
        return label_w, bar_w, num_w

    def render(self) -> Text:
        style = self.get_component_rich_style
        if not self.rows:
            return Text("  " + self.empty, style("barchart--empty", partial=True), end="")
        label_w, bar_w, num_w = self._columns(self.size.width)
        label_s = style("barchart--label", partial=True)
        bar_s = style("barchart--bar", partial=True)
        value_s = style("barchart--value", partial=True)
        slash = style("sidechart--slash", partial=True)
        peak = max((v for _, v in self.rows), default=0)
        lines = []
        for i, (label, value) in enumerate(self.rows):
            here = self.has_focus and i == self.cursor
            line = Text("▌ " if here else "  ", style("sidechart--mark", partial=True), end="")
            name = Text(label, label_s, end="")
            if label.startswith("/"):
                name.stylize(slash, 0, 1)
            name = _cut(name, label_w)
            line.append_text(name).append(" " * (label_w - name.cell_len))
            if bar_w:
                fraction = value / peak if peak > 0 else 0
                line.append("  ").append_text(charts._line(fraction, bar_w, bar_s, None))
                line.append("  ")
            else:
                line.append(" ")
            line.append(self.texts[i].rjust(num_w), value_s).append("  ")
            if here:
                line.stylize(style("sidechart--cursor", partial=True))
            elif i == self._pressed:
                line.stylize(style("barchart--pressed", partial=True))
            elif i == self._hover:
                line.stylize(style("barchart--hover", partial=True))
            lines.append(line)
        return Text("\n", end="").join(lines)

    def _set_hover(self, row: int | None) -> None:
        super()._set_hover(row)
        if row is not None and row < len(self.tips):
            self.tooltip = self.tips[row]

    def on_focus(self, event: events.Focus) -> None:
        self.refresh()

    def on_blur(self, event: events.Blur) -> None:
        self.refresh()

    def action_move(self, step: int) -> None:
        i = self.cursor + step
        if not 0 <= i < len(self.rows):
            raise SkipAction()
        self.cursor = i
        self.refresh()

    async def action_pick(self) -> None:
        await self._pick(self.cursor)

    async def on_bar_chart_selected(self, event: charts.BarChart.Selected) -> None:
        event.stop()
        self.cursor = event.index
        await self._pick(event.index)

    async def _pick(self, index: int) -> None:
        if 0 <= index < len(self.picks):
            result = self.picks[index]()
            if inspect.isawaitable(result):
                await result


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------


@dataclass
class Body:
    """What one section shows. A new `spec` builds the widgets again with `build`."""

    spec: tuple
    build: Callable[[], list[Widget]]
    summary: str = ""
    cue: Cue = None
    hidden: bool = False


class Pane(Vertical):
    """One foldable section: its head row, then its body."""

    DEFAULT_CSS = """
    Pane { height: auto; margin: 1 0; }
    Pane > .pane-body { height: auto; }
    Pane.-folded { margin: 0; }
    Pane.-folded > .pane-body { display: none; }
    Pane.-hidden { display: none; }
    """

    def __init__(self, key: str, title: str) -> None:
        super().__init__(id="side-" + key.replace(".", "-"), classes="-folded")
        self.key = key
        self.title = title
        self.open = False
        self._spec: tuple | None = None
        self._reveal = False

    def compose(self) -> ComposeResult:
        yield PaneHead(do=self.toggle, id=f"{self.id}-head")
        yield Vertical(classes="pane-body", id=f"{self.id}-body")

    @property
    def head(self) -> PaneHead:
        return self.query_one(PaneHead)

    @property
    def body(self) -> Vertical:
        return self.query_one(".pane-body", Vertical)

    def toggle(self) -> None:
        app = app_of(self)
        self._reveal = not self.open
        app.set_state(folded=with_section(app.state.folded, self.key, not self.open))

    def show_head(self, summary: str, cue: Cue) -> None:
        segs: list[Seg] = [("▾ " if self.open else "▸ ", "muted"), (self.title.upper(), "muted")]
        right: list[Seg] = []
        if not self.open and cue:
            glyph = GLYPHS.get(cue[0])
            right = [(f"{glyph} {cue[1]}" if glyph else cue[1], cue[0])]
        elif not self.open and summary:
            right = [(summary, "faint")]
        self.head.set(segs, right)

    async def fill(self, body: Body, open: bool) -> None:
        self.set_class(body.hidden, "-hidden")
        self.open = open
        self.set_class(not open, "-folded")
        self.show_head(body.summary, body.cue)
        if open and body.spec != self._spec:
            await self._mount(body)
        if open and self._reveal:
            self._reveal = False
            self.call_after_refresh(self.scroll_visible, animate=False)

    async def _mount(self, body: Body) -> None:
        self._spec = body.spec
        holder = self.body
        focused = self.screen.focused
        inside = focused is not None and holder in focused.ancestors
        fid = focused.id if inside and focused is not None else None
        cursor = focused.cursor if isinstance(focused, SideChart) else 0
        with self.app.batch_update():
            await holder.remove_children()
            await holder.mount_all(body.build())
            if inside:
                found = list(holder.query(f"#{fid}")) if fid else []
                target: Widget = found[0] if found else self.head
                if isinstance(target, SideChart):
                    target.cursor = min(cursor, max(0, len(target.rows) - 1))
                self.query_ancestor(SidePanel)._restored = target
                target.focus(scroll_visible=False)


# --------------------------------------------------------------------------
# the panel
# --------------------------------------------------------------------------


class SidePanel(VerticalScroll, can_focus=False):
    """The inventory: counts, things that need you, and a row that shows the other sections."""

    # Unscoped, so `.-narrow SidePanel` can match the app's class. Each rule names SidePanel.
    SCOPED_CSS = False
    DEFAULT_CSS = """
    SidePanel {
        height: 1fr;
        padding: 1 0;
        background: $atlas-surface-1;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
        scrollbar-background: $atlas-surface-1;
        scrollbar-background-hover: $atlas-surface-1;
        scrollbar-background-active: $atlas-surface-1;
        scrollbar-color: $atlas-border-strong;
        scrollbar-color-hover: $atlas-muted;
        scrollbar-color-active: $atlas-text;
        scrollbar-corner-color: $atlas-surface-1;
    }
    SidePanel > #side-title { margin-bottom: 1; }
    SidePanel > #side-stats { height: auto; margin-bottom: 1; }
    SidePanel > #side-more { margin: 1 0; }
    SidePanel.-less > #side-more { margin: 1 0 0 0; }
    SidePanel.-less > .side-rest { display: none; }
    SidePanel .side-chips { height: 1; padding: 0 2; margin-top: 1; }
    SidePanel .side-tiles { height: 2; padding: 0 1; }
    SidePanel .side-heat { margin: 0 2; }
    SidePanel .side-gap { margin-top: 1; }
    SidePanel > #side-keys { margin-top: 1; }
    .-narrow SidePanel { border-left: solid $atlas-border-strong; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up,k", "step(-1)", "Up", show=False),
        Binding("down,j", "step(1)", "Down", show=False),
    ]

    def __init__(
        self,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(*children, name=name, id=id, classes=classes, disabled=disabled)
        self._dirty = True
        self._lock = asyncio.Lock()
        self._profiles: list[dict] | None = None
        self._prof_error: str | None = None
        self._health_open = False
        self._draw_due = False
        self._restored: Widget | None = None

    def compose(self) -> ComposeResult:
        yield Line(id="side-title")
        with Vertical(id="side-stats"):
            yield Counts(id="side-counts")
            yield Brief(id="side-facts")
        yield Pane(*PANES[0])
        yield More(do=self._toggle_more, id="side-more")
        for key, title in PANES[1:]:
            yield Pane(key, title).add_class("side-rest")
        yield Act(
            [("?", "accent"), ("  All keyboard shortcuts", "text")],
            do=lambda: self.app.run_action("help"),
            id="side-keys",
            classes="side-rest",
        )

    async def on_mount(self) -> None:
        self.app.screen_change_signal.subscribe(self, self._on_screen)
        self._load_profiles()
        await self.draw()

    # Events

    def on_data_changed(self, event: DataChanged) -> None:
        if not self._draw_due:
            self._draw_due = True
            self._draw_later()

    @work(group="side-data")
    async def _draw_later(self) -> None:
        await asyncio.sleep(DATA_DELAY)
        self._draw_due = False
        await self.draw()

    async def on_state_changed(self, event: StateChanged) -> None:
        fields = event.fields
        if fields & DISPLAY_FIELDS:
            for row in self.query(Choice):
                row.refresh()
            for check in self.query(Check):
                check.refresh()
        if fields & (DATA_FIELDS | SHOW_FIELDS) or (self._dirty and self.shown):
            await self.draw()
        elif fields & {"palette", "mode"}:
            await self.draw(only=DISPLAY)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        # Scroll first and without animation, so Textual's own focus scroll has nothing to do.
        if event.widget is self._restored:
            self._restored = None
        else:
            self.scroll_to_widget(event.widget, animate=False)

    def _on_screen(self, screen: Screen) -> None:
        if len(self.app.screen_stack) == 1:
            self._load_profiles()

    async def on_resize(self, event: events.Resize) -> None:
        await self.draw()

    @property
    def shown(self) -> bool:
        app = app_of(self)
        return app.state.selected is None and app.detail_visible

    # Loads

    @work(exclusive=True, group="side-profiles")
    async def _load_profiles(self) -> None:
        app = app_of(self)
        try:
            result = await app.fetch(app.atlas.profiles)
        except Exception as e:
            self._prof_error = str(e) or type(e).__name__
        else:
            self._profiles = list(result.get("profiles") or [])
            self._prof_error = None
        await self.draw()

    # Drawing

    async def draw(self, only: str | None = None) -> None:
        """Bring each part up to date. While hidden, wait until the panel shows."""
        if not self.is_attached:
            return
        if not self.shown:
            self._dirty = True
            return
        async with self._lock:
            self._dirty = self._dirty and only is not None
            app = app_of(self)
            ins = app.data.insights
            st = app.state.view_state()
            more = section_open(app.state.folded, MORE, False)
            if only is None:
                self._draw_top(ins, st)
                self._draw_more(more, ins)
            tall = app.size.height >= SHORT
            for pane in self.query(Pane):
                if only in (None, pane.key) and (more or pane.key == ATTN):
                    body = self._body(pane.key, ins, st)
                    default = tall and pane.key in DEFAULT_OPEN
                    await pane.fill(body, section_open(app.state.folded, pane.key, default))
            # After the fill, so the sections show with their bodies in place.
            self.set_class(not more, "-less")

    def _draw_top(self, ins: views.Insights | None, st: views.ViewState) -> None:
        app = app_of(self)
        self.query_one("#side-title", Line).set([("Inventory", "strong")])
        inv = views.inventory(ins, st.harness) if ins else {}
        known = app.data.updates is not None and ins is not None and ins.writable
        parts = []
        for key, one, many, tint in COUNTS:
            value = inv.get(key) if key != "updates" or known else None
            if value is None:
                parts.append(("", "–", "faint", many))
            else:
                word = one if value == 1 else many
                parts.append((key if value else "", f"{value:,}", tint if value else "text", word))
        self.query_one("#side-counts", Counts).show(parts)
        self.query_one("#side-facts", Brief).show(facts(inv))

    def _draw_more(self, more: bool, ins: views.Insights | None) -> None:
        self.query_one("#side-more", More).show(more, more_names(ins is None or ins.writable))

    def _toggle_more(self) -> None:
        app = app_of(self)
        more = section_open(app.state.folded, MORE, False)
        app.set_state(folded=with_section(app.state.folded, MORE, not more))

    def _body(self, key: str, ins: views.Insights | None, st: views.ViewState) -> Body:
        if ins is None:
            failed = "scan" in app_of(self).data.errors
            text = "Could not scan the skills." if failed else "Reading your skills…"
            return Body(("wait", text), lambda: [Line([(text, "muted")])], summary="–")
        make = {
            ATTN: self._attention,
            "inv.use": self._usage,
            "inv.cost": self._cost,
            "inv.ovl": self._overlap,
            "inv.sec": self._security,
            "inv.prof": self._profiles_body,
            "inv.set": self._skill_set,
            DISPLAY: self._display,
        }[key]
        return make(ins, st)

    # Needs attention

    def _attention(self, ins: views.Insights, st: views.ViewState) -> Body:
        items = views.attention(ins, st)
        cue = views.attention_cue(items)
        problems = (ins.scan.get("health") or {}).get("problems") or []
        home = ins.scan.get("home") or ""
        spec = ("attn", tuple(tuple(i.values()) for i in items), self._health_open, len(problems))

        def build() -> list[Widget]:
            if not items:
                return [Line([(ALL_CLEAR, "text")], glyph=("✓", "on"), id="side-a-ok")]
            out: list[Widget] = []
            for item in items:
                out.append(self._attn_row(item))
                if item["key"] == "a-store" and self._health_open:
                    out.extend(self._health_rows(problems, home))
            return out

        flag = (cue["tone"], cue["text"]) if cue else None
        return Body(spec, build, summary="Nothing to do", cue=flag)

    def _attn_row(self, item: views.Item) -> Entry:
        action = item["action"]
        press: Callable[[], object] = partial(self._show_view, action)
        if action == "restore":
            press = self._restore
        elif not action:
            press = self._toggle_health
        return Entry(
            [(item["text"], "text")],
            glyph=(GLYPHS[item["tone"]], item["tone"]),
            right=[("›", "faint")],
            tip=item["detail"],
            do=press,
            id=f"side-{item['key']}",
        )

    def _health_rows(self, problems: list[dict], home: str) -> list[Widget]:
        rows: list[Widget] = []
        for i, p in enumerate(problems):
            level = "danger" if p.get("level") == "error" else "warn"
            segs: list[Seg] = [(p.get("message", ""), "text")]
            if p.get("hint"):
                segs.append(("\n" + p["hint"], "muted"))
            if str(p.get("path", "")).startswith("/"):
                segs.append(("\n" + views.tilde(p["path"], home), "faint"))
            rows.append(Line(segs, glyph=(GLYPHS[level], level), id=f"side-health-{i}"))
        return rows

    async def _toggle_health(self) -> None:
        self._health_open = not self._health_open
        await self.draw(only=ATTN)

    # Usage

    def _usage(self, ins: views.Insights, st: views.ViewState) -> Body:
        app = app_of(self)
        usage = app.data.usage or {}
        error = app.data.errors.get("usage") or usage.get("error")
        if usage.get("status") == "error" and not error:
            error = "the usage index stopped"
        hidden = not ins.writable
        if error:
            text = f"Could not read usage: {str(error).rstrip('.')}."

            def failed() -> list[Widget]:
                retry = Act(
                    [("Try again", "accent")],
                    do=lambda: app.reload(["usage"]),
                    id="side-use-retry",
                )
                return [Line([(text, "text")], glyph=("✗", "danger")), retry]

            cue = ("danger", "Could not read usage")
            return Body(("use-error", text), failed, cue=cue, hidden=hidden)
        if not views.use_ready(ins):
            done, total = ([*(usage.get("progress") or []), 0, 0])[:2]
            count = f"{done:,} of {total:,}" if total else ""

            def waiting() -> list[Widget]:
                fraction = done / total if total else None
                fill = Drawn(lambda c: charts.progress(fraction, 24, c), classes="side-gap")
                text = [("Reading your agent sessions… ", "muted"), (count, "text")]
                return [Line(text), fill]

            wait = ("use-wait", done, total)
            return Body(wait, waiting, summary="Reading sessions…", hidden=hidden)
        lv = views.loaded_skills(ins, st.harness)
        days = views.sum_days(ins, lv)
        inv = views.inventory(ins, st.harness)
        rows = tuple(
            (f"/{s.get('invoke') or s['name']}", views.uses(ins, s), s["path"])
            for s in views.top_used(ins, lv)
        )
        short = app.size.height < SHORT
        spec = ("use", tuple(sorted(days.items())), rows, inv["unused"], short, ins.now.date())

        def build() -> list[Widget]:
            out: list[Widget] = []
            if short:
                weeks = views.weekly(days, views.WEEKS, ins.now)
                out.append(Drawn(lambda c: charts.spark(weeks, views.WEEKS, c)))
                out.append(Line([(views.heatmap(days, ins.now)["summary"], "muted")]))
            else:
                heat = charts.Heatmap(days, today=ins.now.date(), id="side-heat")
                out.append(heat.add_class("side-heat"))
            if rows:
                chart = SideChart(
                    [(label, n) for label, n, _ in rows],
                    [f"{n:,}" for _, n, _ in rows],
                    [self._selector(path) for _, _, path in rows],
                    tips=[f"Show {label}" for label, _, _ in rows],
                    id="side-top",
                )
                out.append(chart.add_class("side-gap"))
            if inv["unused"]:
                text = (
                    f"{views.plural(inv['unused'], 'skill')} not used in {views.UNUSED_DAYS} days."
                )
                unused = Act(
                    [(text, "muted"), (" Show" + NBSP + "them", "link")],
                    do=lambda: self._show_view("unused"),
                    id="side-use-unused",
                )
                out.append(unused.add_class("side-gap"))
            return out

        summary = views.uses_text(inv["uses"]) if inv["uses"] else "No uses yet"
        return Body(spec, build, summary=summary, hidden=hidden)

    # Context cost

    def _cost(self, ins: views.Insights, st: views.ViewState) -> Body:
        cost = views.context_cost(ins, st.harness)
        if st.harness == "all":
            return self._cost_all(cost)
        label = app_of(self).data.harnesses.get(st.harness, {}).get("label", st.harness)
        n = cost["count"]
        rows = tuple(
            (f"/{s.get('invoke') or s['name']}", s.get("tokens_listed") or 0, s["path"])
            for s in cost["top"]
        )

        def build() -> list[Widget]:
            note = Line([(COST_NOTE, "faint")], classes="side-gap")
            if not n:
                text = f"No skills are on in {label}, so skills add no tokens to a session."
                return [Line([(text, "text")]), note]
            are = "is" if n == 1 else "are"
            lead = f"in every session, from {views.plural(n, 'skill')} that {are} on"
            chart = SideChart(
                [(name, t) for name, t, _ in rows],
                [views.approx(t) for _, t, _ in rows],
                [self._selector(path) for _, _, path in rows],
                fmt=lambda v: views.approx(int(v)),
                tips=[f"Show {name}" for name, _, _ in rows],
                id="side-cost-top",
                classes="-cost side-gap",
            )
            total = (f"{views.approx(cost['total'])} tokens", "strong")
            return [Line([total, ("\n" + lead, "muted")]), chart, note]

        spec = ("cost", label, cost["total"], n, rows)
        return Body(spec, build, summary=cost["summary"])

    def _cost_all(self, cost: dict) -> Body:
        per = cost["per_harness"]

        def build() -> list[Widget]:
            note = Line([(COST_NOTE, "faint")], classes="side-gap")
            if not per:
                text = "No skills are on, so skills add no tokens to a session."
                return [Line([(text, "text")]), note]
            chart = SideChart(
                [(p["label"], p["total"]) for p in per],
                [f"{views.approx(p['total'])} · {p['count']} on" for p in per],
                [self._harness_picker(p["id"]) for p in per],
                fmt=lambda v: views.approx(int(v)),
                tips=[f"Show {p['label']}" for p in per],
                id="side-cost-per",
                classes="-cost side-gap",
            )
            pick = Line([("Pick a harness to see the skills that cost the most.", "muted")])
            lead = Line([("Tokens each harness adds to every session", "muted")])
            return [lead, chart, pick.add_class("side-gap"), note]

        spec = ("cost-all", tuple(tuple(p.values()) for p in per))
        return Body(spec, build, summary=cost["summary"])

    # Overlap and security

    def _overlap(self, ins: views.Insights, st: views.ViewState) -> Body:
        n = views.overlap_counts(ins, st.harness, views.loaded_skills(ins, st.harness))
        similar, diverged = n["similar"], n["diverged"]
        summary = (
            f"{similar} similar · {diverged} diverged" if similar or diverged else "No overlap"
        )
        cue = ("warn", views.plural(diverged, "diverged name")) if diverged else None

        def tile(count: int, view: str, word: str, tone: str) -> Tile:
            return Tile(
                [(str(count), tone if count else "text"), ("\n" + word, "muted")],
                do=lambda: self._show_view(view),
                tip="Show only these skills" if count else f"No {word}",
                disabled=not count,
                id=f"side-ovl-{view}",
            )

        def build() -> list[Widget]:
            pairs = "similar pair" if similar == 1 else "similar pairs"
            names = "diverged name" if diverged == 1 else "diverged names"
            return [
                Horizontal(
                    tile(similar, "similar", pairs, "text"),
                    tile(diverged, "diverged", names, "warn"),
                    classes="side-tiles",
                )
            ]

        return Body(("ovl", similar, diverged), build, summary=summary, cue=cue)

    def _security(self, ins: views.Insights, st: views.ViewState) -> Body:
        n = views.security_counts(ins, st)
        high, medium, code = n["high"], n["medium"], n["code"]
        parts = [
            f"{high} to review" if high else "",
            f"{medium} with medium findings" if medium else "",
            f"{code} run code",
        ]
        text = " · ".join(p for p in parts if p) + "."
        brief = [
            "" if high or medium else "No high risks",
            f"{medium} medium" if medium else "",
            f"{code} run code" if code else "",
        ]
        cue = ("danger", f"{views.plural(high, 'skill')} to review") if high else None

        def build() -> list[Widget]:
            first: Widget = Line([(text, "text")])
            if high:
                first = Act(
                    [(text, "text"), (" Show" + NBSP + "them", "link")],
                    do=lambda: self._show_view("review"),
                    id="side-sec-review",
                )
            return [first, Line([(views.SEC_NOTE, "faint")], classes="side-gap")]

        summary = " · ".join(p for p in brief if p)
        return Body(("sec", high, medium, code), build, summary=summary, cue=cue)

    # Profiles

    def _profiles_body(self, ins: views.Insights, st: views.ViewState) -> Body:
        app = app_of(self)
        can_save = st.harness == "all" or views.switchable(ins, st.harness)
        label = app.data.harnesses.get(st.harness, {}).get("label", st.harness)
        listing, error = self._profiles, self._prof_error
        if error:
            summary = "Could not read"
        elif listing is None:
            summary = "Loading…"
        else:
            summary = views.plural(len(listing), "profile") if listing else "No profiles"
        rows = tuple((p.get("name", ""), self._profile_meta(p)) for p in listing or [])

        def build() -> list[Widget]:
            out: list[Widget] = []
            if error:
                text = f"Could not read the profiles. {error}"
                out.append(Line([(text, "text")], glyph=("✗", "danger")))
                retry = Act([("Try again", "accent")], do=self._load_profiles, id="side-prof-retry")
                out.append(retry)
            elif listing is None:
                out.append(Line([("Loading profiles…", "muted")]))
            elif not rows:
                out.append(Line([(NO_PROFILES, "muted")]))
            for i, (name, meta) in enumerate(rows):
                out.append(
                    Act(
                        [(name, "text"), ("\n" + meta, "muted")],
                        right=[("Apply…", "link")],
                        keep_right=True,
                        do=self._applier(name),
                        id=f"side-prof-{i}",
                    )
                )
            save: PanelRow
            if can_save:
                save = Act(
                    [("Save current as profile…", "text")],
                    do=lambda: call_feature(app, "screens.profiles", "save_profile"),
                    id="side-prof-save",
                )
            else:
                text = (
                    f"{label} has no on/off switch for skills. "
                    "Pick another harness to save a profile."
                )
                save = Line([(text, "muted")])
            out.append(save.add_class("side-gap"))
            manage = Act(
                [("Rename or delete profiles…", "text")],
                do=lambda: call_feature(app, "screens.profiles", "open_profiles"),
                id="side-prof-manage",
            )
            return [*out, manage]

        spec = ("prof", error, listing is None, rows, can_save, label)
        return Body(spec, build, summary=summary, hidden=not ins.writable)

    def _profile_meta(self, p: dict) -> str:
        ids = list(p.get("harnesses") or {})
        hs = app_of(self).data.harnesses
        where = (
            hs.get(ids[0], {}).get("label", ids[0]) if len(ids) == 1 else f"{len(ids)} harnesses"
        )
        return f"{p.get('on', 0)} on · {p.get('off', 0)} off · {where}"

    def _applier(self, name: str) -> Callable[[], object]:
        return lambda: call_feature(app_of(self), "screens.profiles", "apply_profile", name)

    # Skill set

    def _skill_set(self, ins: views.Insights, st: views.ViewState) -> Body:
        app = app_of(self)
        missing = ins.missing

        def build() -> list[Widget]:
            chips: list[Widget] = [
                Chip(
                    [("Export", "text")],
                    do=lambda: call_feature(app, "screens.transfer", "open_export"),
                    id="side-set-export",
                ),
                Chip(
                    [("Copy", "text")],
                    do=lambda: call_feature(app, "screens.transfer", "copy_manifest"),
                    tip="Copy the skill set to the clipboard",
                    id="side-set-copy",
                ),
                Chip(
                    [("Import…", "text")],
                    do=lambda: call_feature(app, "screens.transfer", "open_import"),
                    id="side-set-import",
                ),
            ]
            out = [Line([(SET_LEAD, "muted")]), Horizontal(*chips, classes="side-chips")]
            if missing:
                label = [(f"Restore {missing} missing", "text")]
                restore = Chip(label, do=self._restore, id="side-set-restore")
                out.append(Horizontal(restore, classes="side-chips"))
            return [*out, Line([(IMPORT_NOTE, "faint")], classes="side-gap")]

        hidden = not ins.writable
        return Body(("set", missing), build, summary="Export or import", hidden=hidden)

    # Display

    def _display(self, ins: views.Insights, st: views.ViewState) -> Body:
        ui = app_of(self).state
        names = {p: p.capitalize() for p in theme.PALETTES}
        modes = [m for m in ("system", "light", "dark") if m in theme.MODES]

        def build() -> list[Widget]:
            rows: list[Widget] = [
                Choice("Theme", "mode", [(m, MODE_LABELS[m]) for m in modes], id="side-disp-mode"),
                Swatches(
                    "Palette", "palette", list(names.items()), tips=names, id="side-disp-palette"
                ),
                Choice(
                    "Group by",
                    "group_by",
                    [(g, GROUP_LABELS[g]) for g in GROUP_LABELS],
                    id="side-disp-group",
                ),
                Choice(
                    "Sort",
                    "sort",
                    [(s, SORT_LABELS.get(s, s.capitalize())) for s in views.SORTS],
                    tips={"cost": "Most tokens in every session first"},
                    id="side-disp-sort",
                ),
            ]
            sizes = [(s, SIZE_LABELS[s]) for s in state.GROUP_SIZES]
            rows.append(Choice("Collections", "group_size", sizes, id="side-disp-size"))
            motions = [(m, MOTION_LABELS[m]) for m in state.MOTIONS]
            rows.append(Choice("Motion", "motion", motions, id="side-disp-motion"))
            for i, (setting, label) in enumerate(CHECKS):
                tip = CHECK_TIPS.get(setting)
                check = Check(label, setting, tip=tip, id="side-disp-" + setting.replace("_", "-"))
                rows.append(check.add_class("side-gap") if i == 0 else check)
            return [*rows, PanelCheck(id="side-disp-panel")]

        summary = f"{names.get(ui.palette, '')} · {MODE_LABELS.get(ui.mode, '')}"
        # The web's dot on the Display button: skills that hide by default are in the list.
        marker = {
            (True, False): "Project skills on",
            (False, True): "Old versions on",
            (True, True): "Project, old versions on",
        }.get((ui.show_project, ui.show_stale))
        cue = ("text", marker) if marker else None
        return Body(("disp", tuple(modes)), build, summary=summary, cue=cue)

    # Actions

    def _show_view(self, view: str) -> None:
        app_of(self).set_state(view=view)

    def _selector(self, path: str) -> Callable[[], object]:
        def select() -> None:
            app = app_of(self)
            self.post_message(SkillSelected(path, open=True))
            self.call_after_refresh(lambda: app.main.query_one("#list").focus())

        return select

    def _harness_picker(self, harness: str) -> Callable[[], object]:
        return lambda: app_of(self).set_state(harness=harness)

    async def _restore(self) -> None:
        await call_feature(app_of(self), "screens.transfer", "open_restore")

    def action_step(self, step: int) -> None:
        """Move the focus to the next or previous control in the panel."""
        chain = [w for w in self.screen.focus_chain if self in w.ancestors]
        if not chain:
            return
        focused = self.screen.focused
        if focused in chain:
            i = chain.index(focused) + step
            if not 0 <= i < len(chain):
                return
            target = chain[i]
        else:
            target = chain[0 if step > 0 else -1]
        if isinstance(target, SideChart):
            target.cursor = 0 if step > 0 else max(0, len(target.rows) - 1)
        target.focus(scroll_visible=False)
        target.scroll_visible(animate=False)

    async def reveal(self, key: str) -> None:
        """Open a section and the rows it sits behind, focus its head, and scroll it to the top."""
        app = app_of(self)
        folded = with_section(app.state.folded, key, True)
        app.set_state(folded=with_section(folded, MORE, True) if key != ATTN else folded)
        await self.draw()
        pane = self.query_one("#side-" + key.replace(".", "-"), Pane)

        def focus() -> None:
            pane.head.focus(scroll_visible=False)
            self.scroll_to_widget(pane, animate=False, top=True)

        self.call_after_refresh(focus)


async def open_display(app: AtlasApp) -> None:
    """Show the side panel and focus its Display section."""
    if app.state.selected is not None or app.state.selected_key is not None:
        app.set_state(selected=None, selected_key=None)
    app.show_detail(True)
    await app.main.query_one(SidePanel).reveal(DISPLAY)
