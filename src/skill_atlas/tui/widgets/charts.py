"""Small charts and status marks: pure Rich renderers for list rows, and two chart widgets.

A renderer can put a tooltip in a cell's style meta; read it back with `tip_of(event.style)`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from functools import lru_cache
from typing import ClassVar, Literal

from rich.style import Style
from rich.text import Text
from textual import events
from textual.actions import SkipAction
from textual.binding import Binding, BindingType
from textual.geometry import Size
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from ...core import views

Colors = Mapping[str, str]
SwitchState = Literal["on", "off", "mixed"]
TagKind = Literal[
    "update", "new", "edited", "similar", "diverged", "issues", "error", "failed", "risk", "updated"
]

TIP = "tip"
SPARK = "▂▃▄▅▆▇"
BASELINE = "▁"
EIGHTHS = "▏▎▍▌▋▊▉█"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SWITCH = {"on": "━━●", "off": "○━━", "mixed": "━◐━", "moving": "━●━", "loading": "━━━"}
KNOBS = "●○◐"
LINE, LINE_HALF, LINE_TRACK = "━", "╸", "─"
CELL, HOVER_CELL = "■", "□"
TAGS: dict[str, tuple[str, str, str]] = {
    "update": ("↑", "update", "atlas-accent"),
    "new": ("+", "new", "atlas-accent"),
    "edited": ("±", "edited", "atlas-warn"),
    "similar": ("≈", "similar", "atlas-warn"),
    "diverged": ("≠", "diverged", "atlas-warn"),
    "issues": ("!", "issues", "atlas-warn"),
    "error": ("✗", "error", "atlas-danger"),
    "failed": ("✗", "failed", "atlas-danger"),
    "risk": ("✗", "high risk", "atlas-danger"),
    "updated": ("✓", "updated", "atlas-on"),
}


@lru_cache(maxsize=256)
def _style(color: str) -> Style:
    return Style(color=color)


def _fg(colors: Colors, key: str) -> Style:
    color = colors.get(key)
    return _style(color) if color else Style()


def _tipped(style: Style, tip: str | None) -> Style:
    return style + Style(meta={TIP: tip}) if tip else style


def tip_of(style: Style) -> str | None:
    """The tooltip a renderer put on the cell with this style, if any."""
    tip = style.meta.get(TIP)
    return tip if isinstance(tip, str) else None


def week_tip(first_day: date, uses: int) -> str:
    """`Week of Oct 6 · 4 uses`."""
    count = views.uses_text(uses) if uses else "no uses"
    return f"Week of {first_day:%b} {first_day.day} · {count}"


def day_tip(day: date, uses: int) -> str:
    """`Wed, Oct 21 · 3 uses`, as the web heatmap says it."""
    count = views.uses_text(uses) if uses else "no uses"
    return f"{day:%a, %b} {day.day} · {count}"


def spark(
    series: Sequence[float],
    width: int,
    colors: Colors,
    *,
    count: int | None = None,
    count_width: int = 2,
    dim: bool = False,
    today: date | None = None,
) -> Text:
    """Weekly uses as block bars, newest on the right; a week with no use is a faint `▁`.

    `count` adds a space and the count, right-aligned. With `today`, each bar gets a week
    tooltip; the last week ends on `today`, as the web's `weekly()` counts.
    """
    fill = _fg(colors, "atlas-faint" if dim else "atlas-spark")
    base = _fg(colors, "atlas-faint")
    values = list(series)[-width:] if width > 0 else []
    peak = max(values, default=0)
    text = Text(" " * (width - len(values)), no_wrap=True, end="")
    for i, value in enumerate(values):
        if value <= 0 or peak <= 0:
            glyph, style = BASELINE, base
        else:
            glyph, style = SPARK[min(len(SPARK), math.ceil(len(SPARK) * value / peak)) - 1], fill
        if today is not None:
            first = today - timedelta(days=7 * (len(values) - 1 - i) + 6)
            style = _tipped(style, week_tip(first, int(value)))
        text.append(glyph, style)
    if count is not None:
        label = views.short(count) if count else ""
        text.append(" ").append(label.rjust(count_width), _fg(colors, "atlas-muted"))
    return text


def switch(
    state: SwitchState | bool,
    colors: Colors,
    *,
    disabled: bool = False,
    loading: bool = False,
    tip: str | None = None,
) -> Text:
    """A three-cell switch: on `━━●`, off `○━━`, mixed `━◐━`. The knob shows the state.

    Disabled is all faint with the knob left; loading is a `━━━` skeleton. The tooltip
    defaults to `Turn on` or `Turn off`.
    """
    key = ("on" if state else "off") if isinstance(state, bool) else state
    if loading:
        return Text(SWITCH["loading"], _fg(colors, "atlas-surface-3"), no_wrap=True, end="")
    if disabled:
        return Text(SWITCH["off"], _tipped(_fg(colors, "atlas-faint"), tip), no_wrap=True, end="")
    tip = tip or ("Turn off" if key == "on" else "Turn on")
    on = _tipped(_fg(colors, "atlas-on"), tip)
    off = _tipped(_fg(colors, "atlas-off"), tip)
    knob = {"on": on, "off": _tipped(_fg(colors, "atlas-muted"), tip), "mixed": on}[key]
    track = on if key == "on" else off
    text = Text(no_wrap=True, end="")
    for glyph in SWITCH[key]:
        text.append(glyph, knob if glyph in KNOBS else track)
    return text


def bar(
    value: float,
    max: float,
    width: int,
    colors: Colors,
    *,
    color: str = "atlas-accent",
) -> Text:
    """A bar `width` cells long, drawn to an eighth of a cell; `color` names the fill token."""
    fill = _fg(colors, color)
    eighths = 0
    if max > 0 and value > 0 and width > 0:
        eighths = min(width * 8, round(width * 8 * value / max) or 1)
    full, part = divmod(eighths, 8)
    text = Text(EIGHTHS[-1] * full, fill, no_wrap=True, end="")
    if part:
        text.append(EIGHTHS[part - 1], fill)
    return text.append(" " * (width - text.cell_len))


def progress(
    fraction: float | None,
    width: int,
    colors: Colors,
    *,
    frame: int = 0,
) -> Text:
    """Job progress: `━` in accent on a `─` track, to half a cell.

    `None` slides a segment along the track; `frame` is its step.
    """
    fill = _fg(colors, "atlas-accent")
    track = _fg(colors, "atlas-border")
    if width <= 0:
        return Text(end="")
    if fraction is None:
        size = min(width, max(3, width // 4))
        start = frame % (width + size) - size
        text = Text(no_wrap=True, end="")
        for i in range(width):
            lit = start <= i < start + size
            text.append(LINE if lit else LINE_TRACK, fill if lit else track)
        return text
    return _line(fraction, width, fill, track)


def _line(fraction: float, width: int, fill: Style, track: Style | None) -> Text:
    halves = round(min(1.0, max(0.0, fraction)) * width * 2)
    if fraction > 0 and not halves:
        halves = 1
    full, half = divmod(halves, 2)
    text = Text(LINE * full, fill, no_wrap=True, end="")
    if half:
        text.append(LINE_HALF, fill)
    rest = width - full - half
    return text.append((LINE_TRACK if track else " ") * rest, track)


def meter(
    fraction: float, width: int, colors: Colors, *, color: str = "atlas-spark", track: bool = True
) -> Text:
    """A thin `━` meter to half a cell; `track` draws the rest as a `─` in `atlas-border`."""
    rest = _fg(colors, "atlas-border") if track else None
    return _line(fraction, width, _fg(colors, color), rest)


def tag(
    kind: TagKind,
    colors: Colors,
    *,
    label: str | None = None,
    color: str | None = None,
    compact: bool = False,
    tip: str | None = None,
) -> Text:
    """A status tag such as `↑ update` or `± edited`.

    `compact` keeps only the glyph, and the full tag becomes its tooltip unless `tip` is given.
    """
    glyph, word, token = TAGS[kind]
    full = f"{glyph} {label or word}"
    if compact:
        tip = tip or full
    style = _tipped(_fg(colors, color or token), tip)
    return Text(glyph if compact else full, style, no_wrap=True, end="")


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    return text if len(text) <= width else text[: width - 1] + "…"


HEAT_LABEL = 4


def heat_grid(width: int, weeks: int = 26) -> tuple[int, int, int]:
    """(label width, cells per week, weeks shown). A narrow grid drops the gaps, then the day
    names, and only then weeks."""
    for label, step in ((HEAT_LABEL, 2), (HEAT_LABEL, 1), (0, 1)):
        if label + weeks * step - (step - 1) <= width:
            return label, step, weeks
    return 0, 1, max(1, min(weeks, width))


def _heat_level(n: int, peak: int) -> int:
    if n <= 0 or peak <= 0:
        return 0
    return max(1, min(4, math.ceil(4 * math.log1p(n) / math.log1p(peak))))


class Heatmap(Widget, can_focus=True):
    """Daily uses as 7 weekday rows by N weeks, newest on the right; N fits the width.

    Hover, or the arrow keys while it has focus, show a day in the caption line.
    """

    DEFAULT_CSS = """
    Heatmap { height: auto; }
    Heatmap > .heatmap--l0 { color: $atlas-heat-0; }
    Heatmap > .heatmap--l1 { color: $atlas-heat-1; }
    Heatmap > .heatmap--l2 { color: $atlas-heat-2; }
    Heatmap > .heatmap--l3 { color: $atlas-heat-3; }
    Heatmap > .heatmap--l4 { color: $atlas-heat-4; }
    Heatmap > .heatmap--label { color: $atlas-faint; }
    Heatmap > .heatmap--caption { color: $atlas-muted; }
    Heatmap > .heatmap--hover { color: $atlas-text; }
    Heatmap > .heatmap--cursor { color: $atlas-text; background: $atlas-selection; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        *(f"heatmap--l{i}" for i in range(5)),
        "heatmap--label",
        "heatmap--caption",
        "heatmap--hover",
        "heatmap--cursor",
    }
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "cursor(-7)", "Previous week", show=False),
        Binding("right", "cursor(7)", "Next week", show=False),
        Binding("up", "cursor(-1)", "Previous day", show=False),
        Binding("down", "cursor(1)", "Next day", show=False),
    ]
    ALLOW_SELECT = False
    LABEL_WIDTH = HEAT_LABEL
    HEIGHT = 9

    days: reactive[Mapping[str, int]] = reactive(dict, layout=True)
    caption: reactive[str | None] = reactive(None, layout=True)

    def __init__(
        self,
        days: Mapping[str, int] | None = None,
        *,
        weeks: int = 26,
        today: date | None = None,
        caption: str | None = None,
        note: str = "",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """`note` follows the caption when there is room: `in saved sessions`."""
        super().__init__(name=name, id=id, classes=classes)
        self.weeks = weeks
        self.today = today
        self.note = note
        self._hover: date | None = None
        self._cursor: date | None = None
        self.set_reactive(Heatmap.days, dict(days or {}))
        self.set_reactive(Heatmap.caption, caption)

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return self.HEIGHT - 1 + len(self._foot_plan(width)[0])

    @property
    def shown_weeks(self) -> int:
        """How many weeks fit the current width."""
        return heat_grid(self.size.width, self.weeks)[2]

    def _today(self) -> date:
        return self.today or date.today()

    def _start(self, weeks: int) -> date:
        today = self._today()
        return today - timedelta(days=(today.weekday() + 1) % 7 + (weeks - 1) * 7)

    def day_at(self, x: int, y: int) -> date | None:
        """The day drawn at content offset (x, y), if any."""
        label_w, step, weeks = heat_grid(self.size.width, self.weeks)
        col, row = x - label_w, y - 1
        if not (0 <= row < 7 and col >= 0 and col % step == 0 and col // step < weeks):
            return None
        day = self._start(weeks) + timedelta(days=7 * (col // step) + row)
        return day if day <= self._today() else None

    def _counts(self, weeks: int) -> dict[date, int]:
        start, today = self._start(weeks), self._today()
        span = (start + timedelta(days=i) for i in range((today - start).days + 1))
        return {day: self.days.get(day.isoformat(), 0) for day in span}

    def _base(self, weeks: int) -> str:
        if self.caption is not None:
            return self.caption
        counts = list(self._counts(weeks).values())
        total, active = sum(counts), sum(1 for n in counts if n)
        if not total:
            return f"No uses in the last {weeks} weeks"
        days = "1 day" if active == 1 else f"{active:,} days"
        return f"{views.uses_text(total)} on {days}"

    def _readout(self) -> date | None:
        if self._hover is not None:
            return self._hover
        return self._cursor if self.has_focus else None

    @staticmethod
    def _legend_cells(worded: bool) -> int:
        return 9 + (10 if worded else 0)

    def _foot_plan(self, width: int) -> tuple[list[str], bool]:
        """The caption lines and whether the legend has its words. The note goes before the
        legend words; when nothing fits, the legend gets its own line. The caption is never cut."""
        weeks = heat_grid(width, self.weeks)[2]
        base = self._base(weeks)
        full = f"{base} {self.note}" if self.note and self.caption is None else base
        for text, worded in ((full, True), (base, True), (base, False)):
            if len(text) + 2 + self._legend_cells(worded) <= width:
                return [text], worded
        return [full if len(full) <= width else base, ""], self._legend_cells(True) <= width

    def render(self) -> Text:
        width = self.size.width
        label_w, step, weeks = heat_grid(width, self.weeks)
        start, today = self._start(weeks), self._today()
        style = self.get_component_rich_style
        levels = [style(f"heatmap--l{i}", partial=True) for i in range(5)]
        faint = style("heatmap--label", partial=True)
        muted = style("heatmap--caption", partial=True)
        counts = self._counts(weeks)
        peak = max(counts.values(), default=0)
        cursor = self._cursor if self.has_focus else None

        months = Text(no_wrap=True, end="")
        for w in range(1, weeks):
            first = start + timedelta(days=7 * w)
            x = label_w + step * w
            clear = not months.cell_len or x > months.cell_len
            if first.day <= 7 and clear and x + 3 <= width:
                months.append(" " * (x - months.cell_len)).append(f"{first:%b}", faint)
        lines = [months]

        for dow in range(7):
            line = Text(no_wrap=True, end="")
            if label_w:
                name = ("", "Mon", "", "Wed", "", "Fri", "")[dow]
                line.append(name.ljust(label_w), faint)
            for w in range(weeks):
                day = start + timedelta(days=7 * w + dow)
                if w and step == 2:
                    line.append(" ")
                if day > today:
                    line.append(" ")
                elif day == cursor:
                    line.append(HOVER_CELL, style("heatmap--cursor", partial=True))
                elif day == self._hover:
                    line.append(HOVER_CELL, style("heatmap--hover", partial=True))
                else:
                    line.append(CELL, levels[_heat_level(counts[day], peak)])
            lines.append(line)
        lines += self._foot(width, levels, faint, muted)
        return Text("\n", no_wrap=True, end="").join(lines)

    def _foot(self, width: int, levels: list[Style], faint: Style, muted: Style) -> list[Text]:
        plan, worded = self._foot_plan(width)
        legend = Text(no_wrap=True, end="")
        for i, level in enumerate(levels):
            legend.append(CELL, level)
            if i < len(levels) - 1:
                legend.append(" ")
        words = Text.assemble(("less", faint), " ", legend, " ", ("more", faint), end="")
        day = self._readout()
        if len(plan) == 2:
            text = day_tip(day, self.days.get(day.isoformat(), 0)) if day else plan[0]
            return [Text(_truncate(text, width), muted, end=""), words if worded else legend]
        text = day_tip(day, self.days.get(day.isoformat(), 0)) if day else plan[0]
        right = next(
            (
                r
                for r in ((words if worded else legend), legend)
                if len(text) + 2 + r.cell_len <= width
            ),
            None,
        )
        room = width - 2 - right.cell_len if right else width
        line = Text(_truncate(text, room), muted, no_wrap=True, end="")
        if right:
            line.append(" " * (width - line.cell_len - right.cell_len)).append_text(right)
        return [line]

    def action_cursor(self, step: int) -> None:
        weeks = heat_grid(self.size.width, self.weeks)[2]
        start, today = self._start(weeks), self._today()
        day = self._cursor or today
        to = day + timedelta(days=step)
        dow = (day.weekday() + 1) % 7
        if abs(step) == 1 and not 0 <= dow + step < 7:
            raise SkipAction()
        if to > today:
            if step != 7 or (today - day).days < (today.weekday() + 1) % 7 + 1:
                raise SkipAction()
            to = today
        if to < start:
            raise SkipAction()
        self._cursor = to
        self.refresh(layout=True)

    def on_focus(self) -> None:
        weeks = heat_grid(self.size.width, self.weeks)[2]
        if self._cursor is None or not self._start(weeks) <= self._cursor <= self._today():
            self._cursor = self._today()
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        day = self.day_at(offset.x, offset.y) if offset else None
        if day is not None:
            self._cursor = day
            self.refresh()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        offset = event.get_content_offset(self)
        self._set_hover(self.day_at(offset.x, offset.y) if offset else None)

    def on_leave(self, event: events.Leave) -> None:
        self._set_hover(None)

    def _set_hover(self, day: date | None) -> None:
        if day == self._hover:
            return
        self._hover = day
        self.tooltip = day_tip(day, self.days.get(day.isoformat(), 0)) if day else None
        self.refresh()


class BarChart(Widget):
    """Rows of label, bar, and right-aligned number; long labels end in `…`.

    A click on a row posts `Selected`. A row with a cut label shows it whole in a tooltip.
    """

    DEFAULT_CSS = """
    BarChart { height: auto; }
    BarChart > .barchart--label { color: $atlas-text; }
    BarChart > .barchart--bar { color: $atlas-spark; }
    BarChart > .barchart--value { color: $atlas-muted; }
    BarChart > .barchart--empty { color: $atlas-faint; }
    BarChart > .barchart--hover { background: $atlas-surface-2; }
    BarChart > .barchart--pressed { background: $atlas-surface-3; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "barchart--label",
        "barchart--bar",
        "barchart--value",
        "barchart--empty",
        "barchart--hover",
        "barchart--pressed",
    }
    ALLOW_SELECT = False

    rows: reactive[Sequence[tuple[str, float]]] = reactive(tuple, layout=True)

    class Selected(Message):
        """The user clicked a row."""

        def __init__(self, chart: BarChart, index: int, label: str) -> None:
            super().__init__()
            self.chart = chart
            self.index = index
            self.label = label

        @property
        def control(self) -> BarChart:
            return self.chart

    def __init__(
        self,
        rows: Sequence[tuple[str, float]] = (),
        *,
        fmt: Callable[[float], str] = lambda v: f"{v:,.0f}",
        empty: str = "Nothing to show yet.",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.fmt = fmt
        self.empty = empty
        self._hover: int | None = None
        self._pressed: int | None = None
        self.set_reactive(BarChart.rows, tuple(rows))

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return max(1, len(self.rows))

    def _columns(self, width: int) -> tuple[int, int, int]:
        num_w = max((len(self.fmt(v)) for _, v in self.rows), default=0)
        longest = max((len(n) for n, _ in self.rows), default=0)
        label_w = min(longest, max(8, width - num_w - 4 - 8))
        bar_w = width - label_w - num_w - 4
        if bar_w < 4:
            bar_w, label_w = 0, max(0, width - num_w - 1)
        return label_w, bar_w, num_w

    def watch_rows(self) -> None:
        self._hover = self._pressed = None
        self.tooltip = None

    def render(self) -> Text:
        style = self.get_component_rich_style
        if not self.rows:
            return Text(self.empty, style("barchart--empty", partial=True), end="")
        label_w, bar_w, num_w = self._columns(self.size.width)
        label_s = style("barchart--label", partial=True)
        bar_s = style("barchart--bar", partial=True)
        value_s = style("barchart--value", partial=True)
        peak = max((v for _, v in self.rows), default=0)
        lines = []
        for i, (label, value) in enumerate(self.rows):
            line = Text(_truncate(label, label_w).ljust(label_w), label_s, no_wrap=True, end="")
            if bar_w:
                fraction = value / peak if peak > 0 else 0
                line.append("  ").append_text(_line(fraction, bar_w, bar_s, None)).append("  ")
            else:
                line.append(" ")
            line.append(self.fmt(value).rjust(num_w), value_s)
            if i == self._pressed:
                line.stylize(style("barchart--pressed", partial=True))
            elif i == self._hover:
                line.stylize(style("barchart--hover", partial=True))
            lines.append(line)
        return Text("\n", end="").join(lines)

    def _row_at(self, event: events.MouseEvent) -> int | None:
        offset = event.get_content_offset(self)
        if offset is None or not 0 <= offset.y < len(self.rows):
            return None
        return offset.y

    def _set_hover(self, row: int | None) -> None:
        if row == self._hover:
            return
        self._hover = row
        tip = None
        if row is not None:
            label, value = self.rows[row]
            if len(label) > self._columns(self.size.width)[0]:
                tip = f"{label} · {self.fmt(value)}"
        self.tooltip = tip
        self.refresh()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self._set_hover(self._row_at(event))

    def on_leave(self, event: events.Leave) -> None:
        self._pressed = None
        self._set_hover(None)
        self.refresh()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._pressed = self._row_at(event)
        self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._pressed is not None:
            self._pressed = None
            self.refresh()

    def on_click(self, event: events.Click) -> None:
        row = self._row_at(event)
        if row is not None:
            self.post_message(self.Selected(self, row, self.rows[row][0]))
