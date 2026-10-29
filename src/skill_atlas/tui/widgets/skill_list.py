"""The grouped skill list: sections, groups, skills, and available skills in one line-API widget."""

from __future__ import annotations

import importlib
import inspect
import re
import textwrap
import time
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from types import ModuleType
from typing import Any, ClassVar

from rich.cells import cell_len
from rich.color import Color
from rich.console import Console
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import BindingType
from textual.cache import LRUCache
from textual.geometry import Region, Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.theme import Theme
from textual.timer import Timer

from ...core import views
from .. import keys, theme
from ..messages import DataChanged, ItemSelected, JobChanged, SkillSelected, StateChanged
from . import app_of, charts

PKG = __package__.rpartition(".")[0]
STOPS = frozenset({"group", "skill", "avail"})
HOVERS = STOPS | {"group-sub"}
REBUILD = frozenset(
    {
        "harness",
        "view",
        "group_by",
        "sort",
        "show_project",
        "show_stale",
        "collapsed",
        "compact",
        "group_size",
    }
)
QUERY_DELAY = 0.1
NAME_MIN, NAME_MAX, DESC_MIN, DESC_ROOMY = 14, 32, 16, 36
NAME_SHARE = 0.8
SPARK_W = views.SPARK_WEEKS
STATUS_W, STATUS_WIDE = 12, 24
DOTS_MAX = 5
SPIN_SECONDS = 0.08
FLASH_SECONDS, FLASH_STEPS = 0.7, 14
NOTE = "You have every skill from this repo. New ones will show here."
EMPTY_ACTIONS = {
    "clear": ("esc", "Clear search"),
    "show_project": ("", "Show project skills"),
    "recheck": ("enter", "Check again"),
    "view_all": ("enter", "Show all skills"),
    "retry": ("enter", "Try again"),
}
RANKS = ("edited", "error", "risk", "warn", "div", "similar")
ACTIONS = frozenset(
    {"update", "install", "install-new", "install-all", "dismiss", "menu", "foldall"}
)


@dataclass(eq=False)
class Row:
    """One line. `key` is what selection or folding uses; `head` is its group header's index."""

    kind: str
    key: str = ""
    item: dict = field(default_factory=dict)
    gid: str = ""
    head: int = -1
    repo: str = ""
    uses: int = 0
    ver: int = 0
    memo: Any = None


@dataclass
class Status:
    """The one status a row shows (design §6), or the action it offers."""

    glyph: str = ""
    word: str = ""
    color: str = "atlas-muted"
    word_color: str = ""
    tip: str = ""
    zone: str = ""
    spin: bool = False
    wide: bool = False


@dataclass
class Cells:
    """What a skill or an available row shows, derived once per data change."""

    name: str
    desc: str = ""
    desc_color: str = "atlas-muted"
    loading: bool = False
    off: bool = False
    switch: str = ""
    switch_tip: str = ""
    dots: list[tuple[bool, str]] = field(default_factory=list)
    series: list[int] | None = None
    uses: int = 0
    use_tip: str = ""
    status: Status = field(default_factory=Status)
    more: list[Status] = field(default_factory=list)
    fresh: bool = False


@dataclass(frozen=True)
class Cols:
    """Column positions for one width. A dropped column has width 0."""

    width: int
    sw: int
    sw_w: int
    chev: int
    name: int
    name_w: int
    desc: int
    desc_w: int
    spark: int
    spark_w: int
    count: int
    count_w: int
    status: int
    status_w: int
    menu: int

    @property
    def right(self) -> int:
        """Where the spark, count, and status block starts."""
        return self.spark if self.spark_w else self.count if self.count_w else self.status


@dataclass
class Ctx:
    bg: str
    hover: str | None
    pressed: str | None
    cursor: bool


@lru_cache(maxsize=512)
def _style(fg: str | None = None, bg: str | None = None, bold: bool = False) -> Style:
    return Style(color=fg, bgcolor=bg, bold=bold or None)


@lru_cache(maxsize=4096)
def _zone(zone: str, tip: str = "") -> Style:
    meta = {"zone": zone, charts.TIP: tip} if tip else {"zone": zone}
    return Style(meta=meta)


@lru_cache(maxsize=64)
def _ident(hue: int, dark: bool) -> tuple[str, str]:
    """The web's avatar colors for a source hue: `--id-bg` and `--id-fg`."""
    return theme.identity(hue, dark)


def _cut(text: str, width: int) -> str:
    """Text cut to `width` cells, ending in `…` when it is longer."""
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    out, used = [], 0
    for ch in text:
        used += cell_len(ch)
        if used > width - 1:
            break
        out.append(ch)
    return "".join(out).rstrip(" ,.;:-") + "…"


def _blend(a: str, b: str, t: float) -> str:
    ca, cb = Color.parse(a).get_truecolor(), Color.parse(b).get_truecolor()
    r, g, bl = (round(x + (y - x) * t) for x, y in zip(ca, cb, strict=True))
    return f"#{r:02x}{g:02x}{bl:02x}"


class Line:
    """A line under construction: text placed at known cell positions."""

    __slots__ = ("text", "x")

    def __init__(self, style: Style) -> None:
        self.text = Text(style=style, no_wrap=True, end="")
        self.x = 0

    def at(self, x: int) -> Line:
        if x > self.x:
            self.text.append(" " * (x - self.x))
            self.x = x
        return self

    def add(self, s: str, style: Style | None = None) -> Line:
        if s:
            self.text.append(s, style)
            self.x += cell_len(s)
        return self

    def add_text(self, t: Text, zone: Style | None = None) -> Line:
        start = len(self.text)
        self.text.append_text(t)
        if zone is not None:
            self.text.stylize(zone, start, len(self.text))
        self.x += t.cell_len
        return self

    def strip(self, console: Console, width: int, base: Style) -> Strip:
        # Rich drops the base style of a text with no spans; the NO_COLOR filter needs one.
        text = self.text
        segments = list(text.render(console)) if text.spans else [Segment(text.plain, base)]
        return Strip(segments).adjust_cell_length(width, base)


class SkillList(ScrollView, can_focus=True):
    """Every section, group, and row of the current view. Only the visible lines render."""

    class ResultsChanged(Message):
        """The number of skills and available skills that the view and search show."""

        def __init__(self, n: int) -> None:
            super().__init__()
            self.n = n

    BINDINGS: ClassVar[list[BindingType]] = keys.bindings("list")
    DEFAULT_CSS = """
    SkillList {
        width: 1fr;
        height: 1fr;
        background: $background;
        overflow-x: hidden;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
        scrollbar-background: $background;
        scrollbar-background-hover: $background;
        scrollbar-background-active: $background;
        scrollbar-color: $atlas-border-strong;
        scrollbar-color-hover: $atlas-muted;
        scrollbar-color-active: $atlas-text;
    }
    SkillList:focus { border: none; background-tint: transparent; }
    """

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.rows: list[Row] = []
        self.cursor = -1
        self.mode = "skeleton"  # rows, skeleton, or empty
        self.empty: views.Empty | None = None
        self._ins: views.Insights | None = None
        self._harness = "all"
        self._terms: list[str] = []
        self._stops: list[int] = []
        self._index: dict[str, int] = {}
        self._by_name: dict[str, list[int]] = {}
        self._name_len = NAME_MIN
        self._count_w = 2
        self._sw_w = 3
        self._compact = False
        self._writable = True
        self._today = date.today()
        self._layouts: dict[int, Cols] = {}
        self._cache: LRUCache[tuple, Strip] = LRUCache(1024)
        self._colors: dict[str, str] | None = None
        self._dark = True
        self._hover: tuple[int, str] | None = None
        self._pressed: tuple[int, str] | None = None
        self._anchor: str | None = None
        self._job: dict | None = None
        self._tracked: set[str] = set()
        self._frame = 0
        self._spin_timer: Timer | None = None
        self._flashes: dict[str, float] = {}
        self._flash_timer: Timer | None = None
        self._descs: dict[str, dict] = {}
        self._loading_descs: set[str] = set()
        self._query_timer: Timer | None = None
        self._view = "all"
        self._pick = 0
        self._large = False
        self.results = 0

    # Lifecycle

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self._on_theme)
        self._spin_timer = self.set_interval(SPIN_SECONDS, self._spin, pause=True)
        self._flash_timer = self.set_interval(FLASH_SECONDS / FLASH_STEPS, self._fade, pause=True)
        self.rebuild()

    def on_resize(self, event: events.Resize) -> None:
        self._layouts.clear()
        self._cache.clear()
        self._sync_size()
        if self.cursor >= 0:
            self._reveal(self.cursor)

    def _on_theme(self, _: Theme) -> None:
        self._colors = None
        self._cache.clear()
        self.refresh()

    def on_focus(self, event: events.Focus) -> None:
        self._refresh_row(self.cursor)

    def on_blur(self, event: events.Blur) -> None:
        self._refresh_row(self.cursor)

    def on_data_changed(self, event: DataChanged) -> None:
        self.rebuild()

    def on_state_changed(self, event: StateChanged) -> None:
        fields = event.fields
        if fields & REBUILD:
            self.rebuild()
        elif "query" in fields:
            # The search box sends every key; rebuild once after the last one in a burst.
            if self._query_timer is None:
                self._query_timer = self.set_timer(QUERY_DELAY, self.rebuild)
            else:
                self._query_timer.reset()
        elif "marked" in fields:
            self._cache.clear()
            self.refresh()
        if fields & {"selected", "selected_key"}:
            self._follow_selection()

    def on_job_changed(self, event: JobChanged) -> None:
        self._job = event.view
        items = (event.view or {}).get("items") or {}
        jobs = self._jobs()
        confirm = getattr(jobs, "confirming", lambda app: None)(self.app)
        names = set(items) | self._tracked | ({confirm} if confirm else set())
        self._load_flashes()
        names |= set(self._flashes)
        self._tracked = {n for n in names if self._job_state(n) is not None or n == confirm}
        for name in names:
            for i in self._by_name.get(name, ()):
                self._touch(i)
        running = any((it or {}).get("state") in views.RUNNING for it in items.values())
        self._run_spinner(running)

    # Building rows

    def rebuild(self) -> None:
        """Lay out the rows again from app.data and app.state. The cursor keeps its item."""
        if self._query_timer is not None:
            self._query_timer.stop()
            self._query_timer = None
        app = app_of(self)
        ins = app.data.insights
        keep: list[str] = []
        if 0 <= self.cursor < len(self.rows):
            row = self.rows[self.cursor]
            keep = [row.key, row.gid] if row.gid else [row.key]
        self._ins = ins
        self._pick = 0
        was = self.results
        self._compact = app.state.compact
        self._large = app.state.group_size == "large"
        self._layouts.clear()
        self._cache.clear()
        self._hover = self._pressed = None
        self.rows, self.empty = [], None
        if ins is None:
            error = app.data.errors.get("scan")
            self.mode = "empty" if error else "skeleton"
            if error:
                body = f"{error.rstrip('.')}. Check that the skill folders exist, then try again."
                self.empty = views.Empty(
                    title="Could not scan the skills", body=body, actions=["retry"]
                )
        else:
            self._writable = ins.writable
            ins.descs.update(self._descs)
            st = app.state.view_state()
            self._harness = st.harness
            self._view = st.view
            self._terms = [t for t in st.q.lower().split() if len(t) > 1]
            self._today = ins.now.astimezone().date() if ins.now.tzinfo else ins.now.date()
            self.empty = self._no_harness(ins)
            if self.empty is None:
                self._flatten(ins, views.sections(ins, st, app.state.collapsed))
            self.mode = "rows" if self.rows else "empty"
            if not self.rows and self.empty is None:
                self.empty = views.empty_state(ins, st)
        if ins is None or self.empty is not None:
            self.results = 0
        if self.results != was:
            self.post_message(self.ResultsChanged(self.results))
        self._stops = [i for i, r in enumerate(self.rows) if r.kind in STOPS]
        self._index = {self.rows[i].key: i for i in self._stops}
        self._by_name = {}
        for i in self._stops:
            name = self._name_of(self.rows[i])
            if name:
                self._by_name.setdefault(name, []).append(i)
        sel = app.state.selected or app.state.selected_key
        found = (self._index.get(k) for k in (sel, *keep) if k)
        first = self._stops[0] if self._stops else -1
        self.cursor = next((i for i in found if i is not None), first)
        self._load_flashes()
        self._sync_size()
        self.refresh()
        if self.cursor >= 0:
            self._reveal(self.cursor)
        self._want_descs()
        if sel and ins is not None and sel not in self._index:
            # Keys act on app.current(); a hidden row must never be its answer.
            app.set_state(selected=None, selected_key=None)

    @staticmethod
    def _no_harness(ins: views.Insights) -> views.Empty | None:
        if ins.scan.get("harnesses"):
            return None
        where = ins.scan.get("config_path") or "the config file"
        body = f"Set config_roots in {where}."
        return views.Empty(title="No agent harness found", body=body, actions=["retry"])

    def _flatten(self, ins: views.Insights, secs: list[views.Section]) -> None:
        rows, blank = self.rows, not self._compact
        known = ins.scan.get("harnesses") or {}
        names, uses, dots = [NAME_MIN], [0], 0
        found = 0
        tagged = 7 if self._view != "new" else 1
        for sec in secs:
            if rows and blank:
                rows.append(Row("blank"))
            rows.append(Row("section", sec["id"], dict(sec)))
            shown = [*sec["rows"], *(s for g in sec["groups"] for s in g["skills"])]
            found += len(shown) + sum(len(g["available"]) for g in sec["groups"])
            for s in shown:
                names.append(cell_len(s.get("invoke") or s["name"]) + 1)
                uses.append(views.uses(ins, s))
                if self._harness == "all" and s.get("scope") == "personal":
                    dots = max(dots, sum(1 for h in s.get("harnesses") or [] if h in known))
            first = True
            for g in sec["groups"]:
                total = sum(views.uses(ins, m) for m in g["members"])
                uses.append(total)
                names.extend(
                    cell_len(a["name"]) + (tagged if a.get("new") else 1) for a in g["available"]
                )
                if not sec["open"]:
                    continue
                if (blank or self._large) and not first:
                    rows.append(Row("blank"))
                first = False
                gid, repo, head = g["id"], g["key"], len(rows)
                item = dict(g)
                rows.append(Row("group", gid, item, gid, head, uses=total))
                if self._large:
                    rows.append(Row("group-sub", gid, item, gid, head))
                if not g["open"]:
                    continue
                rows.extend(Row("skill", s["path"], s, gid, head) for s in g["skills"])
                if g["available"]:
                    rows.append(Row("avail-head", f"av:{repo}", dict(g), gid, head, repo))
                    if g["available_open"]:
                        rows.extend(
                            Row("avail", f"a:{repo}:{a['path']}", a, gid, head, repo)
                            for a in g["available"]
                        )
                if g["available_note"]:
                    rows.append(Row("note", "", dict(g), gid, head, repo))
            if sec["open"]:
                rows.extend(Row("skill", s["path"], s) for s in sec["rows"])
        # One long name must not take the description's room from every row.
        names.sort()
        self._name_len = names[int(NAME_SHARE * (len(names) - 1))]
        self._count_w = max([2, *(len(views.short(n)) for n in uses if n)])
        self._sw_w = max(3, min(dots, DOTS_MAX))
        self.results = found

    @staticmethod
    def _name_of(row: Row) -> str | None:
        """The name jobs use for the row: the folder name, or the available skill's name."""
        if row.kind == "avail":
            return row.item.get("name")
        if row.kind == "skill" and row.item.get("scope") == "personal":
            return row.item.get("dir_name") or row.item.get("name")
        return None

    def _sync_size(self) -> None:
        rows = len(self.rows) if self.mode == "rows" else self.scrollable_content_region.height
        self.virtual_size = Size(0, rows)

    # Jobs

    def _jobs(self) -> ModuleType | None:
        try:
            return importlib.import_module(f"{PKG}.jobs")
        except ModuleNotFoundError:
            return None

    def _job_state(self, name: str | None) -> str | None:
        state_of = getattr(self._jobs(), "state_of", None)
        return state_of(self.app, name) if name and state_of else None

    def _job_status(self, name: str | None, verb: str) -> Status | None:
        job = self._job_state(name)
        ing, ed = ("installing", "installed") if verb == "install" else ("updating", "updated")
        if job == "queued":
            return Status(word="queued", tip="Waiting for its turn")
        if job in views.RUNNING:
            return Status(word=ing, color="atlas-accent", word_color="atlas-muted", spin=True)
        if job == "done":
            return self._tag_status("updated", ed, ed.capitalize())
        if job == "failed":
            error = getattr(self._jobs(), "error_of", lambda app, n: "")(self.app, name)
            tip = f"Retry. It failed: {error}" if error else "Retry"
            return self._tag_status("failed", tip=tip, zone="update")
        return None

    # Derived cells

    def _memo(self, row: Row) -> Any:
        if row.memo is None:
            if row.kind == "skill":
                row.memo = self._skill_cells(row.item)
            elif row.kind == "avail":
                row.memo = self._avail_cells(row)
            elif row.kind == "group":
                row.memo = self._group_status(row.item)
        return row.memo

    def _skill_cells(self, s: dict) -> Cells:
        ins, h = self._ins, self._harness
        assert ins is not None
        label = s.get("invoke") or s["name"]
        sw = views.switch_state(ins, h, s)
        cells = Cells(
            name=label,
            desc=views.clean_desc(s.get("description")),
            off=views.row_state(ins, h, s) == "off",
            series=views.spark_series(ins, s),
            uses=views.uses(ins, s),
        )
        cells.status, cells.more = self._skill_status(s, views.tags(ins, h, s))
        if cells.off:
            cells.desc_color = "atlas-faint"
        if cells.uses:
            last = views.last_used(ins, s)
            when = f" · last {views.ago(last, ins.now)}" if last else ""
            cells.use_tip = f"{views.plural(cells.uses, 'use')}{when}"
        if s.get("scope") != "personal" or not self._writable:
            return cells
        if h == "all":
            known = ins.scan.get("harnesses") or {}
            for hid in s.get("harnesses") or []:
                if hid in known:
                    on = views.switch_state(ins, hid, s)["on"]
                    tip = f"{known[hid].get('label') or hid}: {'on' if on else 'off'}"
                    cells.dots.append((on, tip))
        elif sw["toggle"]:
            cells.switch = "on" if sw["on"] else "off"
            cells.switch_tip = f"{label}: turn {'off' if sw['on'] else 'on'}"
        return cells

    def _skill_status(self, s: dict, tags: list[views.Tag]) -> tuple[Status, list[Status]]:
        """The first status (design §6 priority), then the other tags for the web's 2 and +N."""
        ins = self._ins
        assert ins is not None
        label = s.get("invoke") or s["name"]
        lock = views.lock_name(s)
        verb = "install" if (self._job or {}).get("kind") == "install" else "update"
        status = self._job_status(lock, verb)
        confirm = getattr(self._jobs(), "confirming", lambda app: None)(self.app)
        if status is None and lock and confirm == lock:
            tip = "Press u again, or click here, to replace your edits. esc cancels."
            status = Status(
                "±", "Replace my edits", "atlas-warn", tip=tip, zone="update", wide=True
            )
        if status is None and views.is_outdated(ins, s):
            zone = "update" if self._writable else ""
            tip = f"Update /{label}" if zone else "An update is available"
            status = self._tag_status("update", tip=tip, zone=zone)
        rest = sorted((t for t in tags if t["kind"] != "update"), key=self._order)
        more = [self._from_tag(t) for t in rest]
        if status is None:
            status = more.pop(0) if more else Status()
        return status, more

    @classmethod
    def _order(cls, tag: views.Tag) -> int:
        rank = cls._rank(tag)
        return RANKS.index(rank) if rank in RANKS else len(RANKS)

    @staticmethod
    def _rank(tag: views.Tag) -> str:
        if tag["kind"] == "issue":
            return "error" if tag["level"] == "error" else "warn"
        if tag["kind"] == "plain" and tag["text"] == "similar":
            return "similar"
        return tag["kind"]

    def _from_tag(self, tag: views.Tag) -> Status:
        rank = self._rank(tag)
        if rank not in RANKS:
            return Status(word=tag["text"], color="atlas-faint", tip=tag["title"] or tag["text"])
        if rank in ("error", "warn"):
            n = int(tag["text"].split()[0])
            kind = "error" if rank == "error" else "issues"
            return self._tag_status(kind, views.plural(n, "issue"), tag["title"])
        kind = {"edited": "edited", "risk": "risk", "div": "diverged"}.get(rank, "similar")
        return self._tag_status(kind, tip=tag["title"])

    @staticmethod
    def _tag_status(kind: str, word: str = "", tip: str = "", zone: str = "") -> Status:
        glyph, default, color = charts.TAGS[kind]
        word = word or default
        return Status(glyph, word, color, tip=tip or f"{glyph} {word}", zone=zone)

    def _avail_cells(self, row: Row) -> Cells:
        a = row.item
        cells = Cells(name=a["name"], fresh=bool(a.get("new")))
        info = self._descs.get(row.repo)
        if info is None:
            cells.loading = True
        elif "error" in info:
            cells.desc = f"Description unavailable: {info['error']}"
            cells.desc_color = "atlas-faint"
        else:
            found = (info.get("skills") or {}).get(a.get("path")) or {}
            cells.desc = views.clean_desc(found.get("description")) or "No description"
        status = self._job_status(a.get("name"), "install")
        if status is not None and status.zone:
            status.zone = "install"
        taken = a.get("taken")
        if status is None and taken:
            if taken == "moved":
                tip = "This repo moved the folder of a skill you have. Update or relink it."
                status = Status(word="installed under an old path", tip=tip)
            else:
                tip = f"A skill named {a['name']} is already installed"
                status = Status(word="name in use", tip=tip)
        if status is None and self._writable:
            tip = f"Install /{a['name']}"
            status = Status("i", "Install", "atlas-accent", "atlas-text", tip, "install")
        cells.status = status or Status()
        return cells

    def _group_status(self, g: dict) -> Status | None:
        ins = self._ins
        if ins is None or not self._writable:
            return None
        outdated = [m for m in g["members"] if views.is_outdated(ins, m)]
        if not outdated:
            return None
        states = [self._job_state(views.lock_name(m)) for m in outdated]
        if any(s in views.RUNNING for s in states):
            done = sum(1 for s in states if s == "done")
            busy = sum(1 for s in states if s is not None)
            return Status(word=f"{done} of {busy}", color="atlas-accent", spin=True)
        failed = sum(1 for s in states if s == "failed")
        if failed:
            return self._tag_status(
                "failed", f"{failed} failed", "Try the failed ones again", "update"
            )
        n = len(outdated)
        tip = f"Update {views.plural(n, 'skill')} from {g['label']}"
        return Status("u", f"Update {n}", "atlas-accent", "atlas-text", tip, "update")

    # Layout

    def _palette(self) -> dict[str, str]:
        if self._colors is None:
            app = app_of(self)
            colors = theme.colors(app)
            colors["background"] = app.current_theme.background or colors["atlas-surface-1"]
            self._colors = colors
            self._dark = app.current_theme.dark
        return self._colors

    def _fg(self, token: str, bg: str | None = None, bold: bool = False) -> Style:
        return _style(self._palette().get(token), bg, bold)

    def _cols(self, width: int) -> Cols:
        cols = self._layouts.get(width)
        if cols is None:
            cols = self._layouts[width] = self._layout(width)
        return cols

    def _layout(self, width: int) -> Cols:
        """Columns for one width. Drop order (design §2): spark, count, status word, description."""
        sw_w = self._sw_w
        name_x = 3 + sw_w + 4
        name_w = max(NAME_MIN, min(self._name_len, NAME_MAX, int(width * 0.4)))
        spark, count, status_w = (0 if self._compact else SPARK_W), self._count_w, STATUS_WIDE

        def room() -> int:
            right = (spark + 2 if spark else 0) + (count + 1 if count else 0) + status_w + 2
            return width - name_x - name_w - 2 - right - 3

        if room() < DESC_ROOMY:
            status_w = STATUS_W
        if room() < DESC_MIN:
            spark = 0
        if room() < DESC_MIN:
            count = 0
        if room() < DESC_MIN:
            status_w = 1
        desc_w = room() if room() >= DESC_MIN else 0
        if not desc_w and room() + 2 >= STATUS_W - 1:
            status_w = STATUS_W
        if not desc_w and room() + 2 < 0:
            name_w = max(4, name_w + room() + 2)
        status = width - 3 - status_w
        count_x = status - 2 - count if count else status
        spark_x = (count_x - 1 if count else status - 2) - spark
        return Cols(
            width=width,
            sw=3,
            sw_w=sw_w,
            chev=3 + sw_w + 1,
            name=name_x,
            name_w=name_w,
            desc=name_x + name_w + 2,
            desc_w=desc_w,
            spark=spark_x,
            spark_w=spark,
            count=count_x,
            count_w=count,
            status=status,
            status_w=status_w,
            menu=width - 2,
        )

    def _pin(self, top: int) -> int:
        """The row that line 0 shows: the header of the top row's group while its rows scroll."""
        if 0 < top < len(self.rows):
            head = self.rows[top].head
            if 0 <= head < top:
                return head
        return top

    def _row_at(self, y: int) -> int | None:
        top = int(self.scroll_offset.y)
        i = self._pin(top) if y == 0 else top + y
        return i if 0 <= i < len(self.rows) else None

    # Rendering

    def render_line(self, y: int) -> Strip:
        width = self.scrollable_content_region.width
        base = _style(None, self._palette()["background"])
        if self.mode == "skeleton":
            return self._skeleton_line(y, width, base)
        if self.mode == "empty":
            return self._empty_line(y, width, base)
        i = self._row_at(y)
        return Strip.blank(width, base) if i is None else self._line(i, width)

    def _line(self, i: int, width: int) -> Strip:
        row = self.rows[i]
        memo = self._memo(row)
        status = memo.status if isinstance(memo, Cells) else memo
        frame = self._frame if isinstance(status, Status) and status.spin else 0
        o = self._owner(i)
        hover = self._hover[1] if self._hover and self._hover[0] == o else None
        pressed = self._pressed[1] if self._pressed and self._pressed[0] == o else None
        flash = self._flash_step(row)
        cursor = o == self.cursor
        key = (i, row.ver, width, cursor, cursor and self.has_focus, hover, pressed, frame, flash)
        strip = self._cache.get(key)
        if strip is None:
            strip = self._cache[key] = self._draw(i, row, width, hover, pressed, flash)
        return strip

    def _owner(self, i: int) -> int:
        """The row that a line acts for: a large group's second line acts for its header."""
        return self.rows[i].head if self.rows[i].kind == "group-sub" else i

    def _sub(self, i: int) -> int | None:
        k = i + 1
        return k if k < len(self.rows) and self.rows[k].kind == "group-sub" else None

    def _row_bg(self, i: int, row: Row, hover: str | None, flash: int) -> str:
        c = self._palette()
        if self._owner(i) == self.cursor:
            bg = c["atlas-selection"] if self.has_focus else c["atlas-surface-2"]
        elif row.kind == "skill" and row.key in app_of(self).state.marked:
            bg = c["atlas-mark"]
        elif hover is not None and row.kind in HOVERS:
            bg = c["atlas-surface-1"]
        else:
            bg = c["background"]
        if flash < FLASH_STEPS:
            t = 1 - (1 - flash / FLASH_STEPS) ** 3
            bg = _blend(c["atlas-accent-tint"], bg, t)
        return bg

    def _draw(
        self, i: int, row: Row, width: int, hover: str | None, pressed: str | None, flash: int
    ) -> Strip:
        ctx = Ctx(self._row_bg(i, row, hover, flash), hover, pressed, self._owner(i) == self.cursor)
        base = _style(None, ctx.bg)
        line = Line(base)
        if ctx.cursor and self.has_focus:
            line.add("▌", self._fg("atlas-text", ctx.bg))
        draw = {
            "section": self._draw_section,
            "group": self._draw_group,
            "group-sub": self._draw_group_sub,
            "skill": self._draw_skill,
            "avail-head": self._draw_avail_head,
            "avail": self._draw_avail,
            "note": self._draw_note,
        }.get(row.kind)
        if draw is not None:
            draw(line, row, self._cols(width), ctx)
        return line.strip(self.app.console, width, base)

    def _zone_bg(self, zone: str, ctx: Ctx) -> str:
        if ctx.pressed == zone:
            return self._palette()["atlas-surface-3"]
        if ctx.hover == zone:
            return self._palette()["atlas-surface-2"]
        return ctx.bg

    def _action(
        self, line: Line, x: int, text: str, color: str, zone: str, tip: str, ctx: Ctx
    ) -> None:
        """A clickable word with one cell of hover padding on each side."""
        bg = self._zone_bg(zone, ctx) if zone else ctx.bg
        z = _zone(zone or "status", tip)
        pad = _style(None, bg) + z
        line.at(max(line.x, x - 1)).add(" ", pad).add(text, self._fg(color, bg) + z).add(" ", pad)

    def _text(
        self, line: Line, text: str, width: int, color: str, bg: str, bold: bool = False
    ) -> None:
        """Text cut to width, with the search terms on the accent tint."""
        cut = _cut(text, width)
        style = self._fg(color, bg, bold)
        low = cut.lower()
        lit = [False] * len(cut)
        for term in self._terms:
            for m in re.finditer(re.escape(term), low):
                lit[m.start() : m.end()] = [True] * (m.end() - m.start())
        if not any(lit):
            line.add(cut, style)
            return
        hl = self._fg(color, self._palette()["atlas-accent-tint"], bold)
        start = 0
        for k in range(1, len(cut) + 1):
            if k == len(cut) or lit[k] != lit[start]:
                line.add(cut[start:k], hl if lit[start] else style)
                start = k

    def _mark(self, line: Line, row: Row, ctx: Ctx) -> None:
        if not self._writable:
            return
        marked = app_of(self).state.marked
        if row.kind == "group":
            paths = [s["path"] for s in row.item["skills"]]
            n = sum(1 for p in paths if p in marked)
            glyph = "◆" if paths and n == len(paths) else "◈" if n else "◇"
            tip = f"Mark all {len(paths)} in {row.item['label']}"
        else:
            n = int(row.key in marked)
            glyph = "◆" if n else "◇"
            tip = f"Mark /{row.item.get('invoke') or row.item['name']}"
        if not n and not marked and ctx.hover is None:
            glyph = " "
        z = _zone("mark", tip)
        if line.x:
            line.text.stylize(z, 0, 1)
        else:
            line.add(" ", z)
        line.at(1).add(glyph, self._fg("atlas-accent" if n else "atlas-faint", ctx.bg) + z)
        line.add(" ", z)

    def _status(
        self,
        line: Line,
        cols: Cols,
        status: Status | None,
        ctx: Ctx,
        more: list[Status] | None = None,
    ) -> None:
        if status is None or not (status.glyph or status.word):
            return
        glyph, word = status.glyph, status.word
        if status.spin:
            if self.app.animation_level == "full":
                glyph = charts.SPINNER[self._frame % len(charts.SPINNER)]
            else:
                word = f"{word}…"
        width = cols.status_w
        if status.wide and width > 1:
            width = max(width, cols.status + width - cols.right)
        text = glyph if width == 1 else _cut(f"{glyph} {word}" if glyph else word, width)
        if not text:
            return
        bg = self._zone_bg(status.zone, ctx) if status.zone else ctx.bg
        z = _zone(status.zone or "status", status.tip)
        x = cols.status + cols.status_w - cell_len(text) if status.wide else cols.status
        if status.zone:
            line.at(x - 1).add(" ", _style(None, bg) + z)
        line.at(x)
        stop = x + cell_len(text)
        if glyph and text.startswith(glyph):
            line.add(glyph, self._fg(status.color, bg) + z)
            text = text[len(glyph) :]
        line.add(text, self._fg(status.word_color or status.color, bg) + z)
        if status.zone:
            line.add(" ", _style(None, bg) + z)
        if more and width > 1 and not status.wide:
            self._more(line, cols, more, stop, ctx)

    def _more(self, line: Line, cols: Cols, more: list[Status], x: int, ctx: Ctx) -> None:
        """After the first status: a second tag if it fits, then +N for the rest (web parity)."""
        end = cols.status + cols.status_w
        extra = [f"{t.glyph} {t.word}" if t.glyph else t.word for t in more]
        shown = 0
        rest = len(extra) - 1
        need = 2 + cell_len(extra[0]) + (len(f" +{rest}") if rest else 0)
        if x + need <= end:
            tag, shown = more[0], 1
            z = _zone("status", tag.tip)
            line.at(x + 2)
            if tag.glyph:
                line.add(tag.glyph, self._fg(tag.color, ctx.bg) + z).add(" ", z)
            line.add(tag.word, self._fg(tag.word_color or tag.color, ctx.bg) + z)
            x = line.x
        hidden = extra[shown:]
        plus = f"+{len(hidden)}"
        if hidden and x + 1 + len(plus) <= end:
            tip = f"Also: {', '.join(hidden)}. The panel shows each one."
            line.at(x + 1).add(plus, self._fg("atlas-faint", ctx.bg) + _zone("status", tip))

    def _menu(self, line: Line, cols: Cols, ctx: Ctx) -> None:
        """The ⋯ cell shows on the cursor row and the hovered row; its zone is always there."""
        bg = self._zone_bg("menu", ctx)
        z = _zone("menu", "More actions")
        glyph = "⋯" if ctx.cursor or ctx.hover is not None else " "
        line.at(cols.menu - 1).add(" ", _style(None, bg) + z)
        line.add(glyph, self._fg("atlas-muted", bg) + z).add(" ", _style(None, bg) + z)

    def _count(self, line: Line, cols: Cols, uses: int, tip: str, ctx: Ctx) -> None:
        if not cols.count_w or self._ins is None:
            return
        if not views.use_ready(self._ins):
            line.at(cols.count).add("–".rjust(cols.count_w), self._fg("atlas-faint", ctx.bg))
        elif uses:
            text = views.short(uses).rjust(cols.count_w)
            line.at(cols.count).add(text, self._fg("atlas-muted", ctx.bg) + _zone("count", tip))

    def _draw_section(self, line: Line, row: Row, cols: Cols, ctx: Ctx) -> None:
        sec = row.item
        fold = _zone("fold", f"Show or hide {sec['title']}")
        muted = self._fg("atlas-muted", ctx.bg) + fold
        line.at(2).add(" ", fold).add("▾" if sec["open"] else "▸", muted).add(" ", fold)
        line.add(sec["title"].upper(), muted).add(" ", fold).add(sec["count"], muted)
        line.add(" ", fold)
        ids = sec["group_ids"]
        if len(ids) > 1 and not app_of(self).state.view_state().q:
            collapsed = app_of(self).state.collapsed
            label = "Expand all" if all(g in collapsed for g in ids) else "Collapse all"
            x = cols.width - 2 - len(label)
            if x > line.x + 2:
                self._action(line, x, label, "atlas-muted", "foldall", "", ctx)

    def _draw_group(self, line: Line, row: Row, cols: Cols, ctx: Ctx) -> None:
        g, bg = row.item, ctx.bg
        self._mark(line, row, ctx)
        switch = self._group_switch(g)
        if switch is not None:
            sw = charts.switch(switch[0], self._palette(), tip=switch[1])
            line.at(cols.sw).add_text(sw, _zone("switch"))
        fold = _zone("fold", f"Show or hide {g['label']}")
        line.at(cols.chev - 1).add(" ", fold)
        line.add("▾" if g["open"] else "▸", self._fg("atlas-muted", bg) + fold)
        mono = "~" if g["label"] == views.NO_SOURCE else views.monogram(g["label"]).upper()
        ibg, ifg = _ident(g["hue"], self._dark)
        line.add(mono, _style(ifg, ibg) + fold)
        end = cols.desc + cols.desc_w if cols.desc_w else cols.right - 2
        line.at(cols.name)
        self._text(line, g["label"], end - cols.name, "atlas-text", bg, bold=True)
        fresh = f"+{g['fresh']} new" if g["fresh"] and self._view != "new" else ""
        if fresh and line.x + 1 + len(fresh) <= end:
            tip = f"{views.plural(g['fresh'], 'skill')} added since you last looked"
            line.add(" ").add(fresh, self._fg("atlas-accent", bg) + _zone("status", tip))
        if not self._large:
            self._meta(line, g, end, bg, "  ")
        if cols.spark_w and g["spark"]:
            spark = charts.spark(g["spark"], cols.spark_w, self._palette(), today=self._today)
            line.at(cols.spark).add_text(spark)
        self._count(line, cols, row.uses, views.plural(row.uses, "use"), ctx)
        self._status(line, cols, self._memo(row), ctx)
        self._menu(line, cols, ctx)

    def _meta(self, line: Line, g: dict, end: int, bg: str, lead: str) -> None:
        """The group's sub line (source, counts): whole parts while they fit."""
        muted, faint = self._fg("atlas-muted", bg), self._fg("atlas-faint", bg)
        for k, part in enumerate(g["meta"].split(" · ") if g["meta"] else []):
            gap = " · " if k else lead
            if line.x + len(gap) + cell_len(part) > end:
                break
            line.add(gap, faint if k else None).add(part, muted)

    def _draw_group_sub(self, line: Line, row: Row, cols: Cols, ctx: Ctx) -> None:
        g = row.item
        fold = _zone("fold", f"Show or hide {g['label']}")
        ibg, _ = _ident(g["hue"], self._dark)
        line.at(cols.chev - 1).add("  ", fold).add(" ", _style(None, ibg) + fold)
        line.at(cols.name)
        self._meta(line, g, cols.menu - 2, ctx.bg, "")

    def _group_switch(self, g: dict) -> tuple[charts.SwitchState, str] | None:
        ins = self._ins
        if ins is None or not g["switch"] or not self._writable:
            return None
        if g["kind"] == "plg":
            lv = next((s for s in g["skills"] if s.get("status") != "stale"), None)
            if lv is None or views.switch_state(ins, self._harness, lv)["toggle"] != "plugin":
                return None
            on = g["checked"] == "true"
            return ("on" if on else "off"), f"Plugin {g['label']}: turn {'off' if on else 'on'}"
        checked = g["checked"]
        state: charts.SwitchState = (
            "on" if checked == "true" else "off" if checked == "false" else "mixed"
        )
        verb = "off" if checked == "true" else "on"
        return state, f"All {g['total']} skills from {g['label']}: turn {verb}"

    def _draw_skill(self, line: Line, row: Row, cols: Cols, ctx: Ctx) -> None:
        cells: Cells = self._memo(row)
        c, bg = self._palette(), ctx.bg
        self._mark(line, row, ctx)
        if cells.switch:
            sw = charts.switch(cells.switch == "on", c, tip=cells.switch_tip)
            line.at(cols.sw).add_text(sw, _zone("switch")).add(" ", _zone("switch"))
        elif cells.dots:
            z = _zone("dots", "\n".join(tip for _, tip in cells.dots))
            line.at(cols.sw)
            for on, _ in cells.dots[: cols.sw_w]:
                line.add("●" if on else "○", self._fg("atlas-on" if on else "atlas-off", bg) + z)
        line.at(cols.name).add("/", self._fg("atlas-faint", bg))
        self._text(
            line, cells.name, cols.name_w - 1, "atlas-muted" if cells.off else "atlas-text", bg
        )
        if cols.desc_w:
            line.at(cols.desc)
            if cells.desc:
                color = "atlas-faint" if self._compact else cells.desc_color
                self._text(line, cells.desc, cols.desc_w, color, bg)
            else:
                line.add("No description", self._fg("atlas-faint", bg))
        if not cells.status.wide:
            if cols.spark_w and cells.series:
                spark = charts.spark(
                    cells.series, cols.spark_w, c, dim=cells.off, today=self._today
                )
                line.at(cols.spark).add_text(spark)
            self._count(line, cols, cells.uses, cells.use_tip, ctx)
        self._status(line, cols, cells.status, ctx, cells.more)
        self._menu(line, cols, ctx)

    def _draw_avail_head(self, line: Line, row: Row, cols: Cols, ctx: Ctx) -> None:
        g = row.item
        title = f"Available from {row.repo}"
        fold = _zone("fold", f"Show or hide {title}")
        muted = self._fg("atlas-muted", ctx.bg) + fold
        line.at(cols.chev - 1).add(" ", fold).add("▾" if g["available_open"] else "▸", muted)
        shown, total = len(g["available"]), g["available_total"]
        count = str(total) if shown == total else f"{shown} of {total}"
        acts = self._avail_actions(g)
        right = cols.status + cols.status_w + 1

        def start() -> int:
            return right - sum(len(a[0]) + 2 for a in acts) - 2 * max(0, len(acts) - 1)

        while acts and start() < cols.name + 16:
            acts.pop()
        x = start() if acts else cols.width
        room = x - 2 - cols.name - len(count) - 1
        line.at(cols.name).add(title if cell_len(title) <= room else "Available", muted)
        line.add(" ", fold)
        line.add(count, muted).add(" ", fold)
        for text, color, zone, tip in acts:
            self._action(line, x + 1, text, color, zone, tip, ctx)
            x = line.x + 2

    def _avail_actions(self, g: dict) -> list[tuple[str, str, str, str]]:
        if not self._writable:
            return []
        repo = g["key"]
        if any(self._job_state(a.get("name")) in views.RUNNING for a in g["available"]):
            return [("Installing…", "atlas-muted", "", "")]
        n = g["fresh_installable"]
        if n:
            dismiss = "Clear the new tags. They stay under Available."
            return [
                (f"Install {n} new", "atlas-accent", "install-new", f"Install them from {repo}"),
                ("Dismiss", "atlas-muted", "dismiss", dismiss),
            ]
        n = g["installable"]
        if n > 1:
            return [(f"Install all {n}", "atlas-muted", "install-all", f"Install each from {repo}")]
        return []

    def _draw_avail(self, line: Line, row: Row, cols: Cols, ctx: Ctx) -> None:
        cells: Cells = self._memo(row)
        bg = ctx.bg
        line.at(cols.name).add("/", self._fg("atlas-faint", bg))
        fresh = cells.fresh and self._view != "new"
        self._text(line, cells.name, cols.name_w - 1 - (6 if fresh else 0), "atlas-text", bg)
        if fresh:
            tip = _zone("status", "New since you last looked")
            line.add(" ").add("+ new", self._fg("atlas-accent", bg) + tip)
        if cols.desc_w:
            line.at(cols.desc)
            if cells.loading:
                share = 0.4 + (sum(map(ord, row.key)) % 31) / 100
                bar = self._fg("atlas-surface-3", bg) + _zone("status", "Loading…")
                line.add("━" * max(4, int(cols.desc_w * share)), bar)
            else:
                self._text(line, cells.desc, cols.desc_w, cells.desc_color, bg)
        self._status(line, cols, cells.status, ctx)

    def _draw_note(self, line: Line, row: Row, cols: Cols, ctx: Ctx) -> None:
        line.at(cols.name).add(
            _cut(NOTE, cols.width - cols.name - 2), self._fg("atlas-muted", ctx.bg)
        )

    def _skeleton_line(self, y: int, width: int, base: Style) -> Strip:
        cols = self._cols(width)
        bar = self._fg("atlas-surface-3", self._palette()["background"])
        line = Line(base)
        if y % 8 == 1:
            line.at(cols.name).add("━" * min(14 + (y * 5) % 9, cols.name_w + 4), bar)
        elif y % 8:
            line.at(cols.sw).add(charts.SWITCH["loading"], bar)
            line.at(cols.name).add("━" * min(10 + (y * 7) % 11, cols.name_w - 2), bar)
            if cols.desc_w:
                share = 0.4 + ((y * 13) % 31) / 100
                line.at(cols.desc).add("━" * max(4, int(cols.desc_w * share)), bar)
        return line.strip(self.app.console, width, base)

    def _empty_lines(self, width: int) -> list[list[tuple[str, Style | None]]]:
        empty = self.empty
        if empty is None:
            return []
        bg = self._palette()["background"]
        out: list[list[tuple[str, Style | None]]] = [
            [(_cut(empty["title"], width - 2), self._fg("atlas-text", bg, bold=True))],
            [],
        ]
        muted = self._fg("atlas-muted", bg)
        out += [
            [(part, muted)] for part in textwrap.wrap(empty["body"], max(20, min(60, width - 4)))
        ]
        hints: list[tuple[str, Style | None]] = []
        for k, action in enumerate(empty["actions"]):
            key, label = EMPTY_ACTIONS[action]
            on = k == self._pick
            # enter runs the highlighted action; left and right move the highlight.
            key = "enter" if on else "" if key == "enter" else key
            abg = self._palette()["atlas-selection"] if on else bg
            z = _zone(f"empty:{action}", label)
            if k:
                hints.append(("  ", None))
            if key:
                hints.append((f" {key} ", self._fg("atlas-accent", abg) + z))
            else:
                hints.append((" ", _style(None, abg) + z))
            hints.append((f"{label} ", self._fg("atlas-text", abg) + z))
        if hints:
            out += [[], hints]
        return out

    def _empty_line(self, y: int, width: int, base: Style) -> Strip:
        lines = self._empty_lines(width)
        top = max(0, (self.scrollable_content_region.height - len(lines)) // 3)
        k = y - top
        if not 0 <= k < len(lines) or not lines[k]:
            return Strip.blank(width, base)
        parts = lines[k]
        line = Line(base).at(max(0, (width - sum(cell_len(t) for t, _ in parts)) // 2))
        for text, style in parts:
            line.add(text, style)
        return line.strip(self.app.console, width, base)

    # Cursor and selection

    def _refresh_row(self, i: int) -> None:
        if not 0 <= i < len(self.rows):
            return
        width = self.size.width
        top = int(self.scroll_offset.y)
        if top <= i:
            sub = self._sub(i)
            self.refresh(Region(0, i - top, width, 2 if sub else 1))
        if i == self._pin(top) and self.rows[i].kind == "group":
            self.refresh(Region(0, 0, width, 1))

    def refresh_visible(self) -> None:
        """Redraw the rows from the current data, before the full rebuild that follows."""
        for row in self.rows:
            row.memo = None
        self._cache.clear()
        self.refresh()

    def _touch(self, i: int) -> None:
        for k in {i, self.rows[i].head} - {-1}:
            row = self.rows[k]
            row.memo = None
            row.ver += 1
            self._refresh_row(k)

    def _set_cursor(self, i: int) -> None:
        old, self.cursor = self.cursor, i
        if old != i:
            self._refresh_row(old)
            self._refresh_row(i)
        self._reveal(i)

    def _reveal(self, i: int) -> None:
        height = self.scrollable_content_region.height
        if height <= 0 or not 0 <= i < len(self.rows):
            return
        top = int(self.scroll_offset.y)
        head = self.rows[i].head
        room = 1 if 0 <= head < i else 0
        last = self._sub(i) or i
        if self._stops and i == self._stops[0]:
            target = 0
        elif i < top + room:
            target = max(0, i - room)
        elif last >= top + height:
            target = last - height + 1
        else:
            return
        self.scroll_to(y=target, animate=False)

    def _select(self, i: int, *, open: bool = False, now: bool = False) -> None:
        """Move the cursor to row i and select its item. `now` sets app.state before returning."""
        self._set_cursor(i)
        row = self.rows[i]
        skill = row.kind == "skill"
        if now:
            app = app_of(self)
            app.set_state(
                selected=row.key if skill else None, selected_key=None if skill else row.key
            )
        elif skill:
            self.post_message(SkillSelected(row.key, open=open))
        else:
            self.post_message(ItemSelected(row.key, open=open))

    def _follow_selection(self) -> None:
        state = app_of(self).state
        i = self._index.get(state.selected or state.selected_key or "")
        if i is not None and i != self.cursor:
            self._set_cursor(i)

    def _step(self, delta: int) -> None:
        stops = self._stops
        if not stops:
            return
        if self.cursor < 0:
            k = 0 if delta > 0 else len(stops) - 1
        elif delta > 0:
            k = min(len(stops) - 1, bisect_right(stops, self.cursor) + delta - 1)
        else:
            k = max(0, bisect_left(stops, self.cursor) + delta)
        self._select(stops[k])

    def _jump(self, rows: int) -> None:
        stops = self._stops
        if not stops:
            return
        target = max(0, min(len(self.rows) - 1, self.cursor + rows))
        if rows > 0:
            k = min(bisect_left(stops, target), len(stops) - 1)
        else:
            k = max(0, bisect_right(stops, target) - 1)
        self._select(stops[k])

    def action_cursor_down(self) -> None:
        self._step(1)

    def action_cursor_up(self) -> None:
        self._step(-1)

    def action_page_down(self) -> None:
        self._jump(max(1, self.scrollable_content_region.height - 1))

    def action_page_up(self) -> None:
        self._jump(-max(1, self.scrollable_content_region.height - 1))

    def action_first(self) -> None:
        if self._stops:
            self._select(self._stops[0])

    def action_last(self) -> None:
        if self._stops:
            self._select(self._stops[-1])

    async def action_select(self) -> None:
        if self.mode == "empty":
            actions = self.empty["actions"] if self.empty else []
            if actions:
                await self._empty_action(actions[min(self._pick, len(actions) - 1)])
        elif 0 <= self.cursor < len(self.rows):
            self._select(self.cursor, open=True)

    def _move_pick(self, delta: int) -> None:
        n = len(self.empty["actions"]) if self.empty else 0
        if n:
            self._pick = max(0, min(n - 1, self._pick + delta))
            self.refresh()

    def action_fold(self) -> None:
        """Fold the group at the cursor; from a row inside it, move to its header."""
        if self.mode == "empty":
            self._move_pick(-1)
        if not 0 <= self.cursor < len(self.rows):
            return
        row = self.rows[self.cursor]
        if row.kind == "group":
            if row.item["open"]:
                self._fold(row)
        elif row.head >= 0:
            self._select(row.head)

    def action_unfold(self) -> None:
        if self.mode == "empty":
            self._move_pick(1)
        elif 0 <= self.cursor < len(self.rows):
            row = self.rows[self.cursor]
            if row.kind == "group" and not row.item["open"]:
                self._fold(row)

    def action_fold_all(self) -> None:
        self._fold_all(close=True)

    def action_unfold_all(self) -> None:
        self._fold_all(close=False)

    def _fold_all(self, *, close: bool, ids: Iterable[str] | None = None) -> None:
        app = app_of(self)
        if ids is None:
            ids = [g for r in self.rows if r.kind == "section" for g in r.item["group_ids"]]
        want = set(ids)
        collapsed = app.state.collapsed | want if close else app.state.collapsed - want
        app.set_state(collapsed=frozenset(collapsed))

    def _fold(self, row: Row) -> None:
        app = app_of(self)
        st = app.state.view_state()
        if st.q or self._ins is None:
            return
        key = row.key
        if row.kind == "avail-head":
            if st.view == "new":
                return
            # The saved flag means "not the default", as on the web.
            plain = views.ViewState(view="all", group_by=st.group_by)
            default = views.avail_open(self._ins, plain, row.repo, len(row.item["members"]))
            key = f"av:{row.repo}" if default else f"+av:{row.repo}"
        elif row.kind == "group" and st.view == "new" and key.startswith("src:"):
            return
        app.set_state(collapsed=app.state.collapsed ^ {key})

    # Marks

    def _marks(self, paths: Iterable[str], on: bool) -> None:
        if not self._writable:
            return
        app = app_of(self)
        want = set(paths)
        app.set_state(marked=app.state.marked | want if on else app.state.marked - want)

    def _mark_row(self, i: int) -> None:
        row = self.rows[i]
        marked = app_of(self).state.marked
        if row.kind == "group":
            paths = [s["path"] for s in row.item["skills"]]
            self._marks(paths, not all(p in marked for p in paths))
        elif row.kind == "skill":
            self._marks([row.key], row.key not in marked)
            self._anchor = row.key

    def _mark_range(self, i: int) -> None:
        a = self._index.get(self._anchor or "")
        if a is None:
            self._mark_row(i)
            return
        lo, hi = sorted((a, i))
        self._marks((r.key for r in self.rows[lo : hi + 1] if r.kind == "skill"), True)
        if self.rows[i].kind == "skill":
            self._anchor = self.rows[i].key

    def _extend(self, delta: int) -> None:
        if not 0 <= self.cursor < len(self.rows):
            return
        here = self.rows[self.cursor]
        self._step(delta)
        there = self.rows[self.cursor]
        paths = [r.key for r in (here, there) if r.kind == "skill"]
        self._marks(paths, True)
        if there.kind == "skill":
            self._anchor = there.key

    def action_mark(self) -> None:
        if 0 <= self.cursor < len(self.rows):
            self._mark_row(self.cursor)

    def action_extend_down(self) -> None:
        self._extend(1)

    def action_extend_up(self) -> None:
        self._extend(-1)

    def action_mark_all(self) -> None:
        self._marks((r.key for r in self.rows if r.kind == "skill"), True)

    # Mouse

    def _hit(self, event: events.MouseEvent) -> tuple[int, str] | None:
        offset = event.get_content_offset(self)
        if offset is None:
            return None
        zone = event.style.meta.get("zone") or ""
        if self.mode != "rows":
            return offset.y, zone
        i = self._row_at(offset.y)
        return None if i is None else (self._owner(i), zone)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        tip = charts.tip_of(event.style)
        if tip != self.tooltip:
            self.tooltip = tip
        if self.mode != "rows":
            return
        hit = self._hit(event)
        hover = None if hit is None else (hit[0], hit[1] if hit[1] in ACTIONS else "")
        if hover != self._hover:
            old, self._hover = self._hover, hover
            for h in (old, hover):
                if h is not None:
                    self._refresh_row(h[0])

    def on_leave(self, event: events.Leave) -> None:
        self.tooltip = None
        old, self._hover, self._pressed = self._hover, None, None
        if old is not None:
            self._refresh_row(old[0])

    def on_mouse_down(self, event: events.MouseDown) -> None:
        hit = self._hit(event)
        if self.mode == "rows" and hit is not None and hit[1] in ACTIONS:
            self._pressed = hit
            self._refresh_row(hit[0])

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._pressed is not None:
            i, self._pressed = self._pressed[0], None
            self._refresh_row(i)

    async def on_click(self, event: events.Click) -> None:
        hit = self._hit(event)
        if hit is None:
            return
        event.stop()
        y, zone = hit
        if self.mode == "empty" and zone.startswith("empty:"):
            await self._empty_action(zone.removeprefix("empty:"))
        if self.mode != "rows":
            return
        row = self.rows[y]
        if event.button == 3:
            if row.kind in STOPS:
                self._select(y, now=True)
                await self._call("commands", "open_actions", row.key)
        elif row.kind == "section":
            if zone == "foldall":
                ids = row.item["group_ids"]
                self._fold_all(
                    close=not all(g in app_of(self).state.collapsed for g in ids), ids=ids
                )
            else:
                self._fold(row)
        elif row.kind == "avail-head":
            await self._avail_head_click(row, zone)
        elif row.kind in STOPS:
            await self._row_click(y, row, zone, event)

    async def _row_click(self, y: int, row: Row, zone: str, event: events.Click) -> None:
        if zone == "mark":
            if event.shift:
                self._mark_range(y)
            else:
                self._mark_row(y)
        elif zone == "fold" and row.kind == "group":
            self._fold(row)
        elif zone == "switch":
            self._select(y, now=True)
            await self._call("jobs", "toggle")
        elif zone == "menu":
            self._select(y, now=True)
            await self._call("commands", "open_actions", row.key)
        elif zone == "update":
            self._select(y, now=True)
            await self._call("jobs", "update", self._update_names(row))
        elif zone == "install":
            self._select(y, now=True)
            await self._call("jobs", "install", row.repo, [row.item["path"]])
        elif event.chain >= 2 and row.kind in ("skill", "avail"):
            self._select(y, now=True)
            await self._call(
                "screens.reader", "open_reader", row.key if row.kind == "skill" else None
            )
        else:
            # Below 100 columns the panel is a drawer over the list: a first click only selects.
            narrow = bool(getattr(app_of(self), "narrow", False))
            self._select(y, open=not narrow or y == self.cursor)

    def _update_names(self, row: Row) -> list[str]:
        ins = self._ins
        if ins is None:
            return []
        skills = [row.item] if row.kind == "skill" else row.item["members"]
        names = (
            views.lock_name(s) for s in skills if row.kind == "skill" or views.is_outdated(ins, s)
        )
        return [n for n in names if n]

    async def _avail_head_click(self, row: Row, zone: str) -> None:
        g, repo = row.item, row.repo
        if zone == "install-new":
            paths = [a["path"] for a in g["available"] if a.get("new") and not a.get("taken")]
            await self._call("jobs", "install", repo, paths)
        elif zone == "install-all":
            paths = [a["path"] for a in g["available"] if not a.get("taken")]
            await self._call("jobs", "install", repo, paths)
        elif zone == "dismiss":
            self.run_worker(self._dismiss(repo), group="dismiss")
        elif zone in ("fold", ""):
            self._fold(row)

    async def _dismiss(self, repo: str) -> None:
        app = app_of(self)
        fresh = [a["path"] for a in app.data.available.get(repo) or [] if a.get("new")]
        if not fresh:
            return
        try:
            await app.fetch(app.atlas.dismiss, repo, fresh)
        except Exception as e:
            await self._toast(f"Could not dismiss: {str(e).rstrip('.')}.", "error")
            return
        app.set_state(collapsed=(app.state.collapsed - {f"av:{repo}"}) | {f"+av:{repo}"})
        app.reload(["updates"])
        n = views.plural(len(fresh), "new skill")
        await self._toast(f"Dismissed {n} from {repo}. They stay under Available.")

    async def _toast(self, text: str, severity: str = "information") -> None:
        toast = getattr(self._jobs(), "toast", None)
        if toast is None:
            self.app.notify(text, severity="error" if severity == "error" else "information")
            return
        result = toast(self.app, text, severity=severity)
        if inspect.isawaitable(result):
            await result

    async def _empty_action(self, action: str) -> None:
        app = app_of(self)
        if action == "clear":
            app.set_state(query="")
        elif action == "show_project":
            app.set_state(show_project=True)
        elif action == "view_all":
            app.set_state(view="all")
        elif action == "recheck":
            await self._call("jobs", "check_again")
        elif action == "retry":
            app.reload(refresh=True)

    async def _call(self, module: str, func: str, *args: object) -> None:
        """Call `func(app, *args)` from another TUI module, which may not exist yet."""
        name = f"{PKG}.{module}"
        try:
            fn = getattr(importlib.import_module(name), func, None)
        except ModuleNotFoundError as e:
            if e.name != name:
                raise
            fn = None
        if fn is None:
            self.app.notify("This does not work yet.", severity="warning")
            return
        result = fn(self.app, *args)
        if inspect.isawaitable(result):
            await result

    # Available descriptions

    def _want_descs(self) -> None:
        for row in self.rows:
            repo = row.repo
            if row.kind == "avail" and repo not in self._descs and repo not in self._loading_descs:
                self._loading_descs.add(repo)
                self.run_worker(self._load_descs(repo), group=f"descs:{repo}")

    async def _load_descs(self, repo: str) -> None:
        app = app_of(self)
        paths = [a["path"] for a in app.data.available.get(repo) or []]
        try:
            result = await app.fetch(app.atlas.available, repo, paths)
            info: dict = {"skills": result.get("skills") or {}}
        except Exception as e:
            info = {"error": str(e).rstrip(".") or type(e).__name__}
        self._loading_descs.discard(repo)
        self._descs[repo] = info
        if app.state.query.strip():
            self.rebuild()
            return
        if self._ins is not None:
            self._ins.descs[repo] = info
        for i, row in enumerate(self.rows):
            if row.kind == "avail" and row.repo == repo:
                self._touch(i)

    # Motion

    def _load_flashes(self) -> None:
        """Rows that jobs just updated or put back, from jobs.flashes, still inside the fade."""
        flashes = getattr(self._jobs(), "flashes", None)
        if flashes is None or self.app.animation_level == "none":
            self._flashes = {}
            return
        now = time.monotonic()
        live = flashes(self.app).items()
        self._flashes = {n: t for n, t in live if now - t < FLASH_SECONDS}
        if self._flashes and self._flash_timer is not None:
            self._flash_timer.resume()

    def _flash_step(self, row: Row) -> int:
        start = self._flashes.get(self._name_of(row) or "") if self._flashes else None
        if start is None:
            return FLASH_STEPS
        return min(FLASH_STEPS, int((time.monotonic() - start) / FLASH_SECONDS * FLASH_STEPS))

    def _fade(self) -> None:
        for name in self._flashes:
            for i in self._by_name.get(name, ()):
                self._refresh_row(i)
        now = time.monotonic()
        self._flashes = {n: t for n, t in self._flashes.items() if now - t < FLASH_SECONDS + 0.1}
        if not self._flashes and self._flash_timer is not None:
            self._flash_timer.pause()

    def _run_spinner(self, on: bool) -> None:
        if self._spin_timer is None:
            return
        if on and self.app.animation_level == "full":
            self._spin_timer.resume()
        else:
            self._spin_timer.pause()

    def _spin(self) -> None:
        self._frame += 1
        top = int(self.scroll_offset.y)
        for i in range(top, min(len(self.rows), top + self.scrollable_content_region.height)):
            memo = self.rows[i].memo
            status = memo.status if isinstance(memo, Cells) else memo
            if isinstance(status, Status) and status.spin:
                self._refresh_row(i)
