"""See changes and Compare: a file list and a line-API diff with folded unchanged lines."""

from __future__ import annotations

import asyncio
import bisect
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeVar

from rich.cells import cell_len, chop_cells
from rich.color import Color
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.cache import LRUCache
from textual.containers import Horizontal, Vertical
from textual.geometry import Region, Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Static

from ...core import views
from .. import theme
from ..messages import DataChanged, JobChanged
from ..widgets import app_of
from . import AtlasModal, CloseCell, HintButton

if TYPE_CHECKING:
    from ..app import AtlasApp

T = TypeVar("T")
Severity = Literal["information", "warning", "error"]
WAIT_AFTER, WAIT_MIN = 0.3, 0.5
STACK_BELOW = 100
MAX_WIDTH = 140
HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
STATUSES = ("added", "changed", "removed")
STATUS_COLOR = {"added": "atlas-add", "removed": "atlas-del", "changed": "atlas-muted"}
EDITED = "± You changed this skill after install. The removed lines include your changes."


def kb(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    return f"{n / 1024:.{1 if n < 10240 else 0}f} KB"


def error_text(e: BaseException) -> str:
    return (str(e) or type(e).__name__).rstrip(".")


def toast(app: AtlasApp, text: str | Text, severity: Severity = "information") -> None:
    from .. import jobs

    jobs.toast(app, text, severity=severity)


def busy(app: AtlasApp) -> bool:
    """True while an update or install job runs."""
    from .. import jobs

    return jobs.running(app)


def skill_for(app: AtlasApp, name: str | None) -> dict | None:
    """The record with this lock name, or the selected skill when name is None."""
    if name is None:
        return app.data.skill(app.state.selected)
    return next((s for s in app.data.skills if views.lock_name(s) == name), None)


def slash(s: dict) -> str:
    return "/" + str(s.get("invoke") or s.get("name") or "")


def summary(files: list[dict], added: int, removed: int, colors: dict[str, str]) -> Text:
    """`2 changed · 1 added`, then the line counts. One file shows its path in place of a count."""
    muted, faint = Style(color=colors["atlas-muted"]), Style(color=colors["atlas-faint"])
    out = Text(no_wrap=True, overflow="ellipsis")
    if len(files) == 1:
        out.append(files[0]["path"], Style(color=colors["atlas-text"]))
        if files[0].get("status") != "changed":
            out.append(" · ", faint)
            out.append(str(files[0].get("status", "")), muted)
    for st in STATUSES if len(files) > 1 else ():
        n = sum(1 for f in files if f.get("status") == st)
        if n:
            if out:
                out.append(" · ", faint)
            out.append(f"{n} {st}", muted)
    if out:
        out.append("   ")
    out.append(f"+{added}", Style(color=colors["atlas-add"]))
    out.append(" ")
    out.append(f"−{removed}", Style(color=colors["atlas-del"]))
    out.append(" lines", muted)
    return out


# ---------------------------------------------------------------- diff lines


@dataclass(frozen=True)
class Line:
    """One row of a diff. A fold stands for the unchanged old lines first..last.

    kind: ctx, add, del, fold, note (muted, no gutter), msg, or error (a whole-view message).
    """

    kind: str
    text: str = ""
    old: int | None = None
    new: int | None = None
    first: int = 0
    last: int = 0
    shift: int = 0  # new line number minus old, inside a fold

    @property
    def size(self) -> int:
        return self.last - self.first + 1


def ops_of(entry: dict) -> list[tuple[str, str]]:
    """(op, text) for each line of a file from /api/diff. The op of a hunk header is `@`."""
    return [("@", s) if s.startswith("@@") else (s[:1], s[1:]) for s in entry.get("diff") or []]


def lines_of(
    ops: Iterable[tuple[str, str]], old_text: list[str] | None = None, *, complete: bool = True
) -> list[Line]:
    """Numbered lines. Gaps between hunks become folds; so does the end, when old_text is known."""
    out: list[Line] = []
    old = new = 1
    seen = 0
    for op, text in ops:
        if op == "@":
            m = HUNK.match(text)
            if m is None:
                continue
            a, b = int(m[1]), 1 if m[2] is None else int(m[2])
            c, d = int(m[3]), 1 if m[4] is None else int(m[4])
            old, new = (a if b else a + 1), (c if d else c + 1)
            if old - 1 > seen:
                out.append(Line("fold", first=seen + 1, last=old - 1, shift=new - old))
            seen = old - 1
        elif op == "+":
            out.append(Line("add", text, new=new))
            new += 1
        elif op == "-":
            out.append(Line("del", text, old=old))
            seen, old = old, old + 1
        elif op == " ":
            out.append(Line("ctx", text, old=old, new=new))
            seen, old, new = old, old + 1, new + 1
    if complete and old_text is not None and len(old_text) > seen:
        out.append(Line("fold", first=seen + 1, last=len(old_text), shift=new - old))
    return out


def fits(lines: list[Line], old_text: list[str]) -> bool:
    """True when old_text is the old side of these lines, so its folds can unfold."""
    n = len(old_text)
    return all(
        x.old <= n and old_text[x.old - 1] == x.text for x in lines if x.old is not None
    ) and all(x.last <= n for x in lines if x.kind == "fold")


def unfold(lines: list[Line], i: int, old_text: list[str]) -> list[Line]:
    f = lines[i]
    span = range(f.first, f.last + 1)
    shown = [Line("ctx", old_text[n - 1], old=n, new=n + f.shift) for n in span]
    return [*lines[:i], *shown, *lines[i + 1 :]]


def wrap(text: str, width: int) -> list[str]:
    """Lines of at most width cells, cut after a space when one is in the second half."""
    out: list[str] = []
    while cell_len(text) > width:
        chunk = chop_cells(text, width)[0]
        cut = chunk.rfind(" ") + 1
        if cut <= len(chunk) // 2:
            cut = len(chunk)
        out.append(chunk[:cut])
        text = text[cut:]
    out.append(text)
    return out


def _clean(text: str) -> str:
    return "".join(c if c.isprintable() else " " for c in text.expandtabs(4))


@lru_cache(maxsize=256)
def _style(fg: Color | str | None, bg: Color | str | None) -> Style:
    return Style(color=fg, bgcolor=bg)


# ---------------------------------------------------------------- rows


class Rows(ScrollView, can_focus=True):
    """A line-API list with a cursor, hover, and clicks. An item can wrap to more rows.

    Subclasses give `count` and `draw`; the base caches each drawn strip.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j,down", "move(1)", "Move down", show=False),
        Binding("k,up", "move(-1)", "Move up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("home", "go(0)", "First", show=False),
        Binding("end", "go(-1)", "Last", show=False),
        Binding("enter", "activate", "Open", show=False),
    ]
    DEFAULT_CSS = """
    Rows {
        height: 1fr;
        overflow-x: hidden;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
        scrollbar-gutter: stable;
        background: $atlas-surface-1;
        scrollbar-background: $atlas-surface-1;
        scrollbar-background-hover: $atlas-surface-1;
        scrollbar-background-active: $atlas-surface-1;
    }
    """

    class Moved(Message):
        """The cursor moved to a new item."""

        def __init__(self, rows: Rows, index: int) -> None:
            super().__init__()
            self.rows = rows
            self.index = index

        @property
        def control(self) -> Rows:
            return self.rows

    class Activated(Message):
        """Enter on an item, or a click on it."""

        def __init__(self, rows: Rows, index: int, mouse: bool) -> None:
            super().__init__()
            self.rows = rows
            self.index = index
            self.mouse = mouse

        @property
        def control(self) -> Rows:
            return self.rows

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.cursor = 0
        self.hover: int | None = None
        self._starts = [0]
        self._width = 0
        self._cache: LRUCache[tuple, Strip] = LRUCache(4096)

    # What a subclass gives.

    @property
    def count(self) -> int:
        return 0

    def height_of(self, i: int, width: int) -> int:
        return 1

    def draw(self, i: int, sub: int, width: int, *, cursor: bool, hover: bool) -> Strip:
        raise NotImplementedError

    def hoverable(self, i: int) -> bool:
        return True

    def tip(self, i: int) -> str | None:
        return None

    # Layout

    def on_mount(self) -> None:
        self.watch(self.app, "theme", self.reflow, init=False)
        self.reflow()

    def on_resize(self, event: events.Resize) -> None:
        if self.scrollable_content_region.width != self._width:
            self.reflow()

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return self._starts[-1]

    def reflow(self) -> None:
        """Measure the items again after new data, a resize, or a theme change."""
        width = max(1, self.scrollable_content_region.width)
        starts = [0]
        for i in range(self.count):
            starts.append(starts[-1] + self.height_of(i, width))
        self._starts, self._width = starts, width
        self._cache.clear()
        self.cursor = max(0, min(self.cursor, self.count - 1))
        if self.hover is not None and self.hover >= self.count:
            self.hover = None
        self.virtual_size = Size(width, starts[-1])
        self.refresh(layout=True)

    def palette(self) -> dict[str, str]:
        return theme.colors(self.app)

    def render_line(self, y: int) -> Strip:
        row = y + round(self.scroll_y)
        width = self._width
        if not 0 <= row < self._starts[-1]:
            return Strip.blank(width, self.rich_style)
        i = bisect.bisect_right(self._starts, row) - 1
        sub = row - self._starts[i]
        cursor, hover = i == self.cursor, i == self.hover
        key = (i, sub, width, cursor, cursor and self.has_focus, hover)
        strip = self._cache.get(key)
        if strip is None:
            strip = self.draw(i, sub, width, cursor=cursor, hover=hover)
            self._cache.set(key, strip)
        return strip

    def refresh_item(self, i: int | None) -> None:
        if i is None or not 0 <= i < self.count:
            return
        top = self._starts[i] - round(self.scroll_y)
        self.refresh(Region(0, top, self.size.width, self._starts[i + 1] - self._starts[i]))

    # Cursor

    def go(self, i: int, *, reveal: bool = True) -> None:
        if not self.count:
            return
        i = i % self.count if i < 0 else min(i, self.count - 1)
        old, self.cursor = self.cursor, i
        self.refresh_item(old)
        self.refresh_item(i)
        if reveal:
            self.reveal(i)
        if i != old:
            self.post_message(self.Moved(self, i))

    def reveal(self, i: int) -> None:
        top, bottom = self._starts[i], self._starts[i + 1]
        height = self.scrollable_content_region.height
        y = round(self.scroll_y)
        if top < y:
            self.scroll_to(y=top, animate=False)
        elif bottom > y + height:
            self.scroll_to(y=min(top, bottom - height), animate=False)

    def action_move(self, step: int) -> None:
        self.go(self.cursor + step)

    def action_go(self, i: int) -> None:
        self.go(i)

    def action_page(self, step: int) -> None:
        if not self.count:
            return
        row = self._starts[self.cursor] + step * max(1, self.scrollable_content_region.height - 1)
        row = max(0, min(row, self._starts[-1] - 1))
        self.go(bisect.bisect_right(self._starts, row) - 1)

    def action_activate(self) -> None:
        if self.count:
            self.activate(self.cursor, mouse=False)

    def activate(self, i: int, *, mouse: bool) -> None:
        self.post_message(self.Activated(self, i, mouse))

    def on_focus(self) -> None:
        self.refresh_item(self.cursor)

    def on_blur(self) -> None:
        self.refresh_item(self.cursor)

    # Mouse

    def index_at(self, event: events.MouseEvent) -> int | None:
        offset = event.get_content_offset(self)
        if offset is None or offset.x >= self._width:
            return None
        row = offset.y + round(self.scroll_y)
        if not 0 <= row < self._starts[-1]:
            return None
        return bisect.bisect_right(self._starts, row) - 1

    def set_hover(self, i: int | None) -> None:
        if i is not None and not self.hoverable(i):
            i = None
        if i != self.hover:
            old, self.hover = self.hover, i
            self.refresh_item(old)
            self.refresh_item(i)
            self.tooltip = self.tip(i) if i is not None else None

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self.set_hover(self.index_at(event))

    def on_leave(self, event: events.Leave) -> None:
        self.set_hover(None)

    def on_click(self, event: events.Click) -> None:
        i = self.index_at(event)
        if i is None:
            return
        event.stop()
        self.focus()
        self.go(i)
        self.activate(i, mouse=True)


class FileList(Rows):
    """The changed files: path, line counts, and the status word. The cursor picks the file."""

    DEFAULT_CSS = """
    FileList { height: 1fr; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.files: list[dict] = []
        self._widths = (0, 0)

    @property
    def count(self) -> int:
        return len(self.files)

    def set_files(self, files: list[dict]) -> None:
        self.files = files
        self.cursor = 0
        self._widths = (
            max((len(f"+{f.get('added', 0)}") for f in files if not f.get("binary")), default=0),
            max((len(f"−{f.get('removed', 0)}") for f in files if not f.get("binary")), default=0),
        )
        self.reflow()

    def needed(self) -> int:
        """The width that shows every path whole: bar, path, counts, status, scrollbar."""
        wa, wd = self._widths
        longest = max((cell_len(f["path"]) for f in self.files), default=8)
        return 2 + longest + 2 + wa + 1 + wd + 2 + 7 + 1 + 1

    def tip(self, i: int) -> str | None:
        path = self.files[i]["path"]
        return path if cell_len(path) > self._path_width(self._width) else None

    def _path_width(self, width: int) -> int:
        wa, wd = self._widths
        return max(4, width - 2 - (2 + wa + 1 + wd) - (2 + 7) - 1)

    def draw(self, i: int, sub: int, width: int, *, cursor: bool, hover: bool) -> Strip:
        c = self.palette()
        f = self.files[i]
        bar = cursor and self.has_focus
        bg = (
            c["atlas-selection"]
            if bar
            else c["atlas-surface-3"]
            if cursor
            else c["atlas-surface-2"]
            if hover
            else c["atlas-surface-1"]
        )
        wa, wd = self._widths
        pw = self._path_width(width)
        path = f["path"]
        if cell_len(path) > pw:
            path = "…" + path[-(pw - 1) :]
        segs = [
            Segment("▌ " if bar else "  ", _style(c["atlas-text"], bg)),
            Segment(path.ljust(pw), _style(c["atlas-text"], bg)),
            Segment("  ", _style(None, bg)),
        ]
        if f.get("binary"):
            segs.append(Segment(" " * (wa + 1 + wd), _style(None, bg)))
        else:
            segs += [
                Segment(f"+{f.get('added', 0)}".rjust(wa), _style(c["atlas-add"], bg)),
                Segment(" ", _style(None, bg)),
                Segment(f"−{f.get('removed', 0)}".rjust(wd), _style(c["atlas-del"], bg)),
            ]
        status = str(f.get("status", ""))
        segs += [
            Segment("  ", _style(None, bg)),
            Segment(status.ljust(7), _style(c[STATUS_COLOR.get(status, "atlas-muted")], bg)),
        ]
        return Strip(segs).adjust_cell_length(width, _style(None, bg))


class DiffView(Rows):
    """The line diff of one file: old and new line numbers, the add and remove marks, and folds.

    Enter or a click on a `▸ N unchanged lines` row shows those lines, when the old text is known.
    """

    DEFAULT_CSS = """
    DiffView {
        background: $background;
        scrollbar-background: $background;
        scrollbar-background-hover: $background;
        scrollbar-background-active: $background;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.lines: list[Line] = []
        self.text: list[str] | None = None
        self._digits = 3
        self._chunks: dict[tuple[int, int], list[str]] = {}

    @property
    def count(self) -> int:
        return len(self.lines)

    def show(self, lines: list[Line], text: list[str] | None = None) -> None:
        """Show these lines from the top. text is the old file, which lets folds unfold."""
        self.lines, self.text = lines, text
        ends = [
            x.last + x.shift if x.kind == "fold" else max(x.old or 0, x.new or 0) for x in lines
        ]
        top = max(ends, default=0)
        self._digits = max(3, len(str(top)))
        self.cursor = 0
        self.scroll_to(y=0, animate=False)
        self.reflow()

    def message(self, text: str, *, error: bool = False) -> None:
        self.show([Line("error" if error else "msg", text)])

    def reflow(self) -> None:
        self._chunks.clear()
        super().reflow()

    @property
    def gutter_width(self) -> int:
        return 2 * self._digits + 5

    def chunks(self, i: int, width: int) -> list[str]:
        key = (i, width)
        if key not in self._chunks:
            x = self.lines[i]
            if x.kind in ("msg", "error", "note"):
                room = max(8, width - 4)
                text = f"✗ {x.text}" if x.kind == "error" else x.text
            else:
                room = max(8, width - self.gutter_width - 1)
                fold = x.kind == "fold"
                text = views.plural(x.size, "unchanged line") if fold else _clean(x.text)
            self._chunks[key] = wrap(text, room)
        return self._chunks[key]

    def height_of(self, i: int, width: int) -> int:
        return len(self.chunks(i, width))

    def unfoldable(self, i: int) -> bool:
        return self.text is not None and self.lines[i].kind == "fold"

    def hoverable(self, i: int) -> bool:
        return self.unfoldable(i)

    def tip(self, i: int) -> str | None:
        return f"Show the {views.plural(self.lines[i].size, 'unchanged line')}"

    def activate(self, i: int, *, mouse: bool) -> None:
        if self.text is None or not self.unfoldable(i):
            return
        self.lines = unfold(self.lines, i, self.text)
        self.set_hover(None)
        self.reflow()
        self.go(i, reveal=not mouse)

    def draw(self, i: int, sub: int, width: int, *, cursor: bool, hover: bool) -> Strip:
        c = self.palette()
        x = self.lines[i]
        chunk = self.chunks(i, width)[sub]
        base = self.rich_style.bgcolor
        bar = cursor and self.has_focus
        if x.kind in ("msg", "error", "note"):
            fg = c["atlas-danger"] if x.kind == "error" else c["atlas-muted"]
            return Strip([Segment("  " + chunk, _style(fg, base))]).adjust_cell_length(
                width, _style(None, base)
            )
        bg: Color | str | None = {
            "add": c["atlas-add-bg"],
            "del": c["atlas-del-bg"],
            "fold": c["atlas-surface-3"] if hover else c["atlas-surface-2"],
        }.get(x.kind, base)
        if bar:
            bg = c["atlas-selection"]
        first = sub == 0
        w = self._digits
        old = f"{x.old:>{w}}" if first and x.old is not None else " " * w
        new = f"{x.new:>{w}}" if first and x.new is not None else " " * w
        if x.kind == "fold":
            mark, mark_fg = ("▸", c["atlas-muted"]) if self.text is not None else (" ", None)
            text_fg = c["atlas-text" if hover else "atlas-muted" if self.text else "atlas-faint"]
        else:
            mark, mark_fg = {
                "add": ("+", c["atlas-add"]),
                "del": ("−", c["atlas-del"]),
            }.get(x.kind, (" ", None))
            text_fg = c["atlas-muted"] if x.kind == "ctx" else c["atlas-text"]
        segs = [
            Segment("▌" if bar else " ", _style(c["atlas-text"], bg)),
            Segment(f"{old} {new} ", _style(c["atlas-faint"], bg)),
            Segment(mark if first else " ", _style(mark_fg, bg)),
            Segment(" ", _style(None, bg)),
            Segment(chunk, _style(text_fg, bg)),
        ]
        return Strip(segs).adjust_cell_length(width, _style(None, bg))


# ---------------------------------------------------------------- the pane


class DiffPane(Horizontal):
    """The changed files at the left (on top when narrow) and the selected file's diff.

    The file list shows for two or more files; with one, the caption names it.
    """

    DEFAULT_CSS = """
    DiffPane { height: 1fr; }
    DiffPane > #df-side { width: 36; height: 1fr; margin-right: 2; display: none; }
    DiffPane.-files > #df-side { display: block; }
    DiffPane .label { height: 1; color: $atlas-muted; }
    DiffPane #df-caption { height: 1; color: $atlas-muted; }
    DiffPane #df-caption { text-wrap: nowrap; text-overflow: ellipsis; }
    DiffPane > #df-main { width: 1fr; height: 1fr; }
    DiffPane.-stacked { layout: vertical; }
    DiffPane.-stacked > #df-side { width: 1fr; height: auto; margin: 0 0 1 0; }
    DiffPane.-stacked FileList { height: auto; max-height: 4; }
    """

    def __init__(self, *, files: bool = True, id: str | None = None) -> None:
        super().__init__(id=id)
        self._with_files = files
        self.files: list[dict] = []
        self.texts: dict[str, list[str]] = {}
        self._lines: dict[str, list[Line]] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="df-side"):
            yield Static("FILES", classes="label")
            yield FileList(id="df-files")
        with Vertical(id="df-main"):
            yield Static(id="df-caption")
            yield DiffView(id="df-diff")

    @property
    def view(self) -> DiffView:
        return self.query_one(DiffView)

    @property
    def file_list(self) -> FileList:
        return self.query_one(FileList)

    def message(self, text: str, *, error: bool = False) -> None:
        """Replace the diff with one message; the file list empties."""
        self._set_files([])
        self.view.message(text, error=error)

    def show_files(self, files: list[dict]) -> None:
        self._set_files(files)
        self._lines.clear()
        self.select(0)

    def add_text(self, path: str, text: list[str]) -> None:
        """The old text of one file, so its folds can unfold."""
        self.texts[path] = text
        self._lines.pop(path, None)
        if self.files and self.files[self.current]["path"] == path:
            self.select(self.current)

    @property
    def current(self) -> int:
        return self.file_list.cursor if self.has_files else 0

    @property
    def has_files(self) -> bool:
        return self._with_files and len(self.files) > 1

    def _set_files(self, files: list[dict]) -> None:
        self.files = files
        self.file_list.set_files(files)
        self.set_class(self.has_files, "-files")
        self.query_one("#df-caption").display = self.has_files
        self.side_width()

    def side_width(self) -> None:
        if not self.has_files or self.has_class("-stacked"):
            return
        room = round(0.4 * self.size.width) or 36
        self.query_one("#df-side").styles.width = max(24, min(self.file_list.needed(), room))

    def on_resize(self, event: events.Resize) -> None:
        self.side_width()

    def select(self, i: int) -> None:
        if not self.files:
            return
        f = self.files[i]
        caption = Text(f["path"], no_wrap=True, overflow="ellipsis")
        self.query_one("#df-caption", Static).update(caption)
        path = f["path"]
        if path not in self._lines:
            self._lines[path] = self.lines_for(f)
        text = self.texts.get(path) if f.get("status") == "changed" else None
        self.view.show(self._lines[path], text if self._fits(path) else None)

    def _fits(self, path: str) -> bool:
        text = self.texts.get(path)
        return text is not None and fits(self._lines[path], text)

    def lines_for(self, f: dict) -> list[Line]:
        if f.get("binary"):
            sizes = (
                f"{kb(f.get('old_size', 0))} to {kb(f.get('new_size', 0))}"
                if f.get("status") == "changed"
                else kb(f.get("old_size") or f.get("new_size") or 0)
            )
            return [Line("msg", f"Binary file, {sizes}.")]
        if not f.get("diff"):
            return [Line("msg", "Not shown. The diff is too long.")]
        text = self.texts.get(f["path"]) if f.get("status") == "changed" else None
        lines = lines_of(ops_of(f), text, complete=not f.get("truncated"))
        if text is not None and not fits(lines, text):
            lines = lines_of(ops_of(f), None, complete=not f.get("truncated"))
        if f.get("truncated"):
            lines.append(Line("note", f"Shows the first {len(f['diff'])} lines only."))
        return lines

    def show_compare(self, d: dict, text: list[str] | None) -> None:
        ops = [(x.get("op", " "), x.get("text", "")) for x in d.get("lines") or []]
        lines = lines_of(ops, text, complete=not d.get("truncated"))
        if text is not None and not fits(lines, text):
            text, lines = None, lines_of(ops, None, complete=not d.get("truncated"))
        if d.get("truncated"):
            lines.append(Line("note", "The diff is too long to show in full."))
        self.view.show(lines, text)

    def step(self, delta: int) -> None:
        if self.has_files:
            self.file_list.go((self.file_list.cursor + delta) % len(self.files))

    @on(Rows.Moved, "FileList")
    def _file_moved(self, event: Rows.Moved) -> None:
        event.stop()
        self.select(event.index)

    @on(Rows.Activated, "FileList")
    def _file_opened(self, event: Rows.Activated) -> None:
        event.stop()
        if not event.mouse:
            self.view.focus()


# ---------------------------------------------------------------- dialogs


class DiffDialog(AtlasModal[Any]):
    """The frame the diff, compare, and history dialogs share: title, ✕, a pane, and actions."""

    AUTO_FOCUS = "DiffView"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "close", "Close", show=False),
        Binding("left_square_bracket", "file(-1)", "Previous file", show=False),
        Binding("right_square_bracket", "file(1)", "Next file", show=False),
    ]
    DEFAULT_CSS = """
    DiffDialog { padding: 1 2; }
    DiffDialog > #df-dialog {
        width: 100%;
        height: 100%;
        max-width: 140;
        padding: 1 2;
        background: $atlas-surface-1;
        border: round $atlas-border-strong;
    }
    DiffDialog.-short { padding: 0 1; }
    DiffDialog.-short > #df-dialog { padding: 0 2; }
    DiffDialog.-short DiffPane { margin-top: 0; }
    DiffDialog.-short DiffPane.-stacked FileList { max-height: 3; }
    DiffDialog #df-head { height: 1; }
    DiffDialog #df-title { width: 1fr; text-style: bold; color: $atlas-text; }
    DiffDialog #df-title, DiffDialog .path, DiffDialog #df-head > #df-summary {
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    DiffDialog #df-head > #df-summary { width: auto; max-width: 60%; margin: 0 2; }
    DiffDialog .lead { height: auto; color: $atlas-muted; }
    DiffDialog .path { height: 1; color: $atlas-muted; }
    DiffDialog #df-summary { height: 1; }
    DiffDialog #df-warn { display: none; height: auto; margin-top: 1; padding: 0 1; }
    DiffDialog #df-warn { background: $atlas-warn-tint; color: $atlas-warn; }
    DiffDialog #df-warn.-on { display: block; }
    DiffDialog DiffPane { margin-top: 1; }
    DiffDialog #df-actions { height: 1; margin-top: 1; align-horizontal: right; }
    DiffDialog #df-actions > HintButton { margin-left: 2; }
    DiffDialog #df-again { display: none; }
    DiffDialog.-failed #df-again { display: block; }
    """

    def wide(self) -> bool:
        return min(self.app.size.width - 4, MAX_WIDTH) >= STACK_BELOW

    def on_mount(self) -> None:
        self._sync_stack()

    def on_resize(self, event: events.Resize) -> None:
        self._sync_stack()

    def _sync_stack(self) -> None:
        self.set_class(self.app.size.height < 30, "-short")
        for pane in self.query(DiffPane):
            pane.set_class(not self.wide(), "-stacked")
            if not self.wide():
                pane.query_one("#df-side").styles.clear_rule("width")
            else:
                pane.side_width()

    def action_file(self, step: int) -> None:
        self.query_one(DiffPane).step(step)

    async def wait_for(self, text: str, fn: Callable[..., T], *args: Any) -> T:
        """Run fn on a thread. After WAIT_AFTER, show text; once shown, keep it WAIT_MIN."""
        shown: list[float] = []

        def show() -> None:
            shown.append(time.monotonic())
            self.waiting(text)

        timer = self.set_timer(WAIT_AFTER, show)
        try:
            result = await app_of(self).fetch(fn, *args)
        finally:
            timer.stop()
        if shown:
            await asyncio.sleep(max(0.0, WAIT_MIN - (time.monotonic() - shown[0])))
        return result

    def waiting(self, text: str) -> None:
        self.query_one(DiffPane).message(text)

    def palette(self) -> dict[str, str]:
        return theme.colors(self.app)


class DiffScreen(DiffDialog):
    """Changes in /name: what an update changes, from your copy to the latest version upstream."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("u", "update", "Update", show=False),
        Binding("t", "again", "Try again", show=False),
    ]

    def __init__(self, lock: str, skill: dict) -> None:
        super().__init__()
        self.lock_key = lock
        self.skill = skill
        self.result: dict | None = None
        self.repo = str((skill.get("origin") or {}).get("source") or "")

    def compose(self) -> ComposeResult:
        with Vertical(id="df-dialog"):
            with Horizontal(id="df-head"):
                yield Static(f"Changes in {slash(self.skill)}", id="df-title")
                yield Static(id="df-summary")
                yield CloseCell()
            yield Static(f"From your copy to the latest version on {self.repo}.", classes="lead")
            yield Static(EDITED, id="df-warn")
            yield DiffPane(id="df-pane")
            with Horizontal(id="df-actions"):
                yield HintButton("esc", "Close", "close")
                yield HintButton("t", "Try again", "again", id="df-again")
                yield HintButton("u", "Update", "update", variant="primary", id="df-update")

    def on_mount(self) -> None:
        super().on_mount()
        self.sync_actions()
        self.load()

    @work(exclusive=True, group="diff")
    async def load(self) -> None:
        app = app_of(self)
        pane = self.query_one(DiffPane)
        self.set_class(False, "-failed")
        try:
            d = await self.wait_for(f"Downloading {self.repo}…", app.atlas.diff, self.lock_key)
        except Exception as e:
            fix = "Check your network, then press t to try again."
            pane.message(f"Could not get the changes: {error_text(e)}. {fix}", error=True)
            self.set_class(True, "-failed")
            self.sync_actions()
            return
        self.result = d
        files = d.get("files") or []
        if files:
            self.query_one("#df-summary", Static).update(
                summary(files, d.get("added", 0), d.get("removed", 0), self.palette())
            )
            pane.show_files(files)
            if pane.has_files and self.focused in (None, pane.view):
                pane.file_list.focus()
        else:
            pane.message("The files are the same. Only the version record is different.")
        self.sync_actions()
        if any(f["path"] == "SKILL.md" and f.get("status") == "changed" for f in files):
            try:
                text = await app.fetch(app.atlas.skill_text, self.skill["path"])
            except Exception:
                return
            pane.add_text("SKILL.md", text.splitlines())

    def edited(self) -> bool:
        if self.result is not None:
            return bool(self.result.get("local_edits"))
        return bool(self.skill.get("local_edits"))

    def sync_actions(self) -> None:
        app = app_of(self)
        ins = app.data.insights
        s = app.data.skill(self.skill.get("path")) or self.skill
        hint = self.query_one("#df-update", HintButton)
        hint.display = ins is not None and views.is_outdated(ins, s) and not busy(app)
        hint.disabled = self.result is None
        edited = self.edited()
        hint.relabel("Replace my edits" if edited else "Update")
        hint.set_class(edited, "-warn")
        hint.set_class(not edited, "-primary")
        self.query_one("#df-warn").set_class(edited, "-on")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "update":
            hint = self.query_one("#df-update", HintButton)
            return hint.display and not hint.disabled
        if action == "again":
            return self.has_class("-failed")
        return True

    def action_again(self) -> None:
        if self.has_class("-failed"):
            self.load()

    def action_update(self) -> None:
        if self.check_action("update", ()):
            self.dismiss("update")

    def on_job_changed(self, event: JobChanged) -> None:
        self.sync_actions()

    def on_data_changed(self, event: DataChanged) -> None:
        self.sync_actions()


class CompareScreen(DiffDialog):
    """Two copies of one skill: the SKILL.md diff from this copy to the other one."""

    def __init__(self, skill: dict, other: str, copy: dict | None) -> None:
        super().__init__()
        self.skill = skill
        self.other = other
        self.copy = copy or {}

    def compose(self) -> ComposeResult:
        newer = self.copy.get("newer")
        with Vertical(id="df-dialog"):
            with Horizontal(id="df-head"):
                yield Static(slash(self.skill), id="df-title")
                yield Static(id="df-summary")
                yield CloseCell()
            mine = self._path("−", "atlas-del", self.skill["path"], newer == "this")
            yield Static(mine, classes="path")
            yield Static(self._path("+", "atlas-add", self.other, newer == "other"), classes="path")
            yield DiffPane(files=False, id="df-pane")
            with Horizontal(id="df-actions"):
                yield HintButton("esc", "Close", "close")

    def _path(self, sign: str, token: str, path: str, newer: bool) -> Text:
        c = self.palette()
        out = Text(no_wrap=True, overflow="ellipsis")
        out.append(sign, Style(color=c[token]))
        out.append(" " + views.tilde(path), Style(color=c["atlas-muted"]))
        if newer:
            out.append(" · ", Style(color=c["atlas-faint"]))
            out.append("newer", Style(color=c["atlas-text"]))
        return out

    def on_mount(self) -> None:
        super().on_mount()
        self.load()

    @work(exclusive=True, group="compare")
    async def load(self) -> None:
        app = app_of(self)
        pane = self.query_one(DiffPane)
        a = self.skill["path"]
        try:
            d = await self.wait_for("Loading the diff…", app.atlas.compare, a, self.other)
        except Exception as e:
            fix = "Press ctrl+p and choose Reload to scan the skills again."
            pane.message(f"Could not compare the files: {error_text(e)}. {fix}", error=True)
            return
        if not d.get("lines"):
            pane.message(
                "The two files are the same now. Press ctrl+p and choose Reload to update the list."
            )
            return
        self.query_one("#df-summary", Static).update(
            summary([], d.get("added", 0), d.get("removed", 0), self.palette())
        )
        pane.show_compare(d, None)
        try:
            text = await app.fetch(app.atlas.skill_text, a)
        except Exception:
            return
        pane.show_compare(d, text.splitlines())


def _then_update(app: AtlasApp, lock: str) -> Callable[[Any], None]:
    def done(result: Any) -> None:
        if result == "update":
            from .. import jobs

            app.call_next(jobs.update, app, [lock], confirmed=True)

    return done


def open_diff(app: AtlasApp, name: str | None = None) -> None:
    """Show what an update changes in the tracked skill with this lock name, or the selected one."""
    s = skill_for(app, name)
    if s is None:
        toast(app, "Select a skill to see its changes.")
        return
    lock = views.lock_name(s)
    if lock is None:
        toast(app, f"Could not get the changes: {slash(s)} is not linked to a GitHub repo.")
        return
    app.push_screen(DiffScreen(lock, s), _then_update(app, lock))


def open_compare(app: AtlasApp, a: str | None = None, b: str | None = None) -> None:
    """Compare skill path a (the selected skill) with b (its first diverged copy)."""
    s = app.data.skill(a or app.state.selected)
    if s is None:
        toast(app, "Select a skill to compare its copies.")
        return
    copies = s.get("copies") or []
    other = b or (copies[0]["path"] if copies else None)
    if other is None:
        toast(app, f"{slash(s)} has no copies that differ.")
        return
    copy = next((c for c in copies if c.get("path") == other), None)
    app.push_screen(CompareScreen(s, other, copy))
