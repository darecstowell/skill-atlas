"""The top row: the brand, one tab per harness, and the update status."""

from __future__ import annotations

import inspect
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar

from rich.cells import cell_len
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.geometry import Offset
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ...core import views
from .. import keys
from ..messages import DataChanged, JobChanged, LoadStarted, StateChanged
from ..screens import AtlasModal, CloseCell
from . import app_of
from .charts import SPINNER

if TYPE_CHECKING:
    from ..app import AtlasApp

NARROW, WIDE = 100, 160
GAP = 2
SLOT = (44, 60)  # cells kept for the update cluster, below and from WIDE columns
TAB_GUESS = 24  # the widest tab before the scan names the harnesses
LOGO, BRAND = " ╱ ", " Skill Atlas"
ALL = "All harnesses"
SPIN = 0.08
SHOW_AFTER, SHOW_FOR, JUST_CHECKED = 0.3, 0.5, 1.4
# How the cluster gets shorter: (piece, form). Each step picks a shorter form or drops the piece.
STEPS = (
    ("new", 1),
    ("warn", 1),
    ("new", 2),
    ("check", 1),
    ("warn", 2),
    ("count", 1),
    ("warn", 3),
    ("count", 2),
)
PIECES = ("new", "count", "warn", "all", "check", "job")
TEXT, ACCENT = "$atlas-text", "$atlas-accent"
TICK = ("✓ ", "$atlas-on")
DIGITS = re.compile(r"\d+")

Forms = list[Content | None]


def label_of(app: AtlasApp, harness: str) -> str:
    if harness == "all":
        return ALL
    h = app.data.harnesses.get(harness) or {}
    return h.get("label") or h.get("name") or harness


def meta_of(app: AtlasApp, harness: str) -> str:
    """The web's meta notes for a harness, joined: `writes ~/.claude/settings.json`."""
    ins = app.data.insights
    return "; ".join(views.header_meta(ins, harness)) if ins and harness else ""


def _digits(text: str) -> Content:
    """Numbers in text color on the cell's muted color, as the web's `<b>` in the cluster."""
    out = Content(text)
    for m in DIGITS.finditer(text):
        out = out.stylize(TEXT, m.start(), m.end())
    return out


def _hint(tip: str, job: str) -> str:
    """The tooltip plus the key that does the same, from keys.KEYS: `Check again (ctrl+r)`."""
    key = next((k.show for k in keys.KEYS if k.action == f"run('jobs:{job}')"), "")
    return f"{tip} ({key})" if key else tip


def _cells(c: Content | None) -> int:
    return 0 if c is None else c.cell_length + 2


def _width(pieces: dict[str, Forms], pick: dict[str, int]) -> int:
    """Cells the cluster takes with these forms, with one cell between pieces."""
    cells = [_cells(pieces[p][pick[p]]) for p in pieces if pieces[p][pick[p]] is not None]
    return sum(cells) + max(0, len(cells) - 1)


class Cell(Static):
    """A piece of the header that a left click runs. Hover and press show on its background."""

    DEFAULT_CSS = """
    Cell { width: auto; height: 1; padding: 0 1; color: $atlas-muted; }
    Cell:hover { background: $atlas-surface-2; }
    Cell.-pressed { background: $atlas-surface-3; }
    Cell.-idle, Cell.-idle:hover, Cell.-idle.-pressed { background: transparent; }
    """
    ALLOW_SELECT = False

    def __init__(
        self,
        content: Content | str = "",
        run: Callable[[], object] | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(content, id=id, classes=classes, markup=False)
        self.run = run

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 1 and self.run and not self.has_class("-idle"):
            self.add_class("-pressed")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.remove_class("-pressed")

    def on_leave(self, event: events.Leave) -> None:
        self.remove_class("-pressed")

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        if event.button != 1 or self.run is None or self.has_class("-idle"):
            return
        result = self.run()
        if inspect.isawaitable(result):
            await result


class Brand(Static):
    """The logo cell and the name. A double-click does not select it."""

    ALLOW_SELECT = False


class HarnessTab(Cell):
    """One harness. A click switches to it."""

    def __init__(self, harness: str) -> None:
        super().__init__(run=lambda: app_of(self).set_state(harness=harness), classes="tab")
        self.harness = harness


class AtlasHeader(Vertical):
    """The brand, the harness tabs, and the update cluster in one row; a band when stale."""

    DEFAULT_CSS = """
    AtlasHeader { height: auto; }
    AtlasHeader > #bar { height: 1; padding: 0 1; background: $atlas-surface-1; }
    AtlasHeader #brand { width: auto; margin-right: 2; }
    AtlasHeader #tabs { width: 1fr; height: 1; }
    AtlasHeader #skeleton { width: 22; height: 1; background: $atlas-surface-2; }
    AtlasHeader .tab:hover { color: $atlas-text; }
    AtlasHeader .tab.-active, AtlasHeader .tab.-active:hover, AtlasHeader .tab.-active.-pressed {
        background: $atlas-surface-3; color: $atlas-text;
    }
    AtlasHeader #cluster { width: 44; height: 1; margin-left: 2; align-horizontal: right; }
    AtlasHeader #cluster > Cell { margin-left: 1; }
    AtlasHeader #new { background: $atlas-accent-tint; color: $atlas-accent; }
    AtlasHeader #new:hover { background-tint: $atlas-text 8%; }
    AtlasHeader #new.-pressed { background-tint: $atlas-text 16%; }
    AtlasHeader #warn { color: $atlas-warn; }
    AtlasHeader #all { background: $atlas-accent; color: $atlas-on-accent; }
    AtlasHeader #all:hover { background-tint: $atlas-text 12%; }
    AtlasHeader #all.-pressed { background-tint: $atlas-text 22%; }
    AtlasHeader > #stale {
        display: none; height: 1; padding: 0 1; text-align: center;
        background: $atlas-warn-tint; color: $atlas-warn;
    }
    """

    def __init__(
        self, *, name: str | None = None, id: str | None = None, classes: str | None = None
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._tabs: list[HarnessTab] = []
        self._choices: tuple[tuple[str, str], ...] = ()
        self._job: dict | None = None
        self._frame = 0
        self._spinner: Timer | None = None
        self._check_timer: Timer | None = None
        self._check_since: float | None = None
        self._rechecking = False
        self._checking = False
        self._shown_at = 0.0
        self._just_until = 0.0
        self._settled = False
        self._held: int | None = None  # the settled cluster's width; checks and jobs keep it

    def compose(self) -> ComposeResult:
        with Horizontal(id="bar"):
            yield Brand(id="brand", markup=False)
            with Horizontal(id="tabs"):
                yield Static(id="skeleton")
                yield Cell(run=self._open_menu, id="more")
            with Horizontal(id="cluster"):
                yield Cell(run=lambda: app_of(self).set_state(view="new"), id="new")
                yield Cell(run=lambda: app_of(self).set_state(view="updates"), id="count")
                yield Cell(run=self._show_errors, id="warn")
                yield Cell(Content("Update all"), run=self._update_all, id="all")
                yield Cell(run=self._check_again, id="check")
                yield Cell(id="job", classes="-idle")
        yield Static(id="stale", markup=False)

    def on_mount(self) -> None:
        from .. import jobs

        self.piece("all").tooltip = _hint("Update each skill that has an update", "update_all")
        self._spinner = self.set_interval(SPIN, self._spin, pause=True)
        self._job = jobs.current(app_of(self))
        self.draw()

    def on_resize(self, event: events.Resize) -> None:
        self.draw()

    def on_load_started(self, event: LoadStarted) -> None:
        if event.part == "updates":
            self._track_check()
            self.draw()

    def on_data_changed(self, event: DataChanged) -> None:
        if "updates" in event.parts:
            self._track_check()
        self.draw()

    def on_state_changed(self, event: StateChanged) -> None:
        if event.fields & {"harness", "view"}:
            self.draw()

    def on_job_changed(self, event: JobChanged) -> None:
        self._job = event.view
        self.draw()

    def piece(self, name: str) -> Cell:
        return self.query_one(f"#{name}", Cell)

    @property
    def checking(self) -> bool:
        """An update check runs, or its indicator still shows."""
        return "updates" in app_of(self).data.loading or self._checking

    def menu_anchor(self) -> Widget:
        """Where the harness menu opens: under the `+N` cell, else under the active tab."""
        more = self.piece("more")
        if more.display:
            return more
        return next((t for t in self._tabs if t.has_class("-active")), more)

    # Drawing

    def draw(self) -> None:
        app = app_of(self)
        cols = app.size.width
        inner = max(0, cols - 2)
        self._sync_tabs()
        brand = Content.styled(LOGO, f"$atlas-on-accent on {ACCENT}")
        if cols >= NARROW:
            brand += Content.styled(BRAND, f"bold {TEXT}")
        self.query_one("#brand", Static).update(brand)
        widest = max((cell_len(label) + 2 for _, label in self._choices), default=TAB_GUESS)
        n = len(self._choices)
        more_w = _cells(self._more_text(n, n, cols)) if n > 1 else 0
        fixed = brand.cell_length + GAP + GAP
        pieces = self._cluster()
        natural = _width(pieces, dict.fromkeys(pieces, 0))
        if self._settled:
            self._held = natural
        cap = SLOT[cols >= WIDE]
        need = cap if self._held is None else max(natural, self._held)
        slot = max(0, min(cap, need, inner - fixed - widest - more_w))
        self.query_one("#cluster").styles.width = slot
        self._fit_tabs(inner - fixed - slot, cols)
        self._fit_cluster(pieces, slot)
        stale = bool(((app.data.scan or {}).get("server") or {}).get("stale"))
        band = self.query_one("#stale", Static)
        band.display = stale
        if stale:
            band.update("! Skill Atlas changed on disk. Quit and start it again.")
        self._sync_spinner()

    def _sync_tabs(self) -> None:
        app = app_of(self)
        ins = app.data.insights
        ids = views.harness_choices(ins) if ins else []
        choices = tuple((h, label_of(app, h)) for h in ids)
        loading = app.data.scan is None and "scan" not in app.data.errors
        self.query_one("#skeleton").display = loading
        if choices != self._choices:
            self._choices = choices
            for tab in self._tabs:
                tab.remove()
            self._tabs = [HarnessTab(h) for h, _ in choices]
            if self._tabs:
                self.query_one("#tabs").mount(*self._tabs, before=self.piece("more"))
        for tab, (h, label) in zip(self._tabs, choices, strict=True):
            tab.set_class(h == app.state.harness, "-active")
            tab.update(label)
            tip = meta_of(app, h)
            tab.tooltip = tip[:1].upper() + tip[1:] if tip else None

    @staticmethod
    def _more_text(n: int, of: int, cols: int, at: int | None = None) -> Content:
        """`7 more` and a faint chevron; below NARROW columns, `3 of 9` (the active tab's place)."""
        words = f"{n} more " if cols >= NARROW else f"{of if at is None else at} of {of} "
        return Content.assemble(words, ("›", "$atlas-faint"))

    def _fit_tabs(self, room: int, cols: int) -> None:
        """Show the tabs that fit, in order, plus the active one; the rest go behind `7 more`.

        Below NARROW columns only the active tab shows, then `3 of 9`, as design.md §11 says.
        """
        more, tabs = self.piece("more"), self._tabs
        labels = [label for _, label in self._choices]
        widths = [cell_len(label) + 2 for label in labels]
        if sum(widths) <= room:
            for tab in tabs:
                tab.display = True
            more.display = False
            return
        avail = room
        if cols < NARROW:
            room = 0
        more_w = _cells(self._more_text(len(tabs), len(tabs), cols))
        shown: list[int] = []
        used = 0
        for i, w in enumerate(widths):
            if used + w + more_w > room:
                break
            shown.append(i)
            used += w
        active = next((i for i, t in enumerate(tabs) if t.has_class("-active")), None)
        if active is not None and active not in shown:
            while shown and used + widths[active] + more_w > room:
                used -= widths[shown.pop()]
            shown.append(active)
            used += widths[active]
        if active is not None and used + more_w > avail:
            cut = max(1, avail - more_w - 2)
            tabs[active].update(Content(labels[active]).truncate(cut, ellipsis=True))
        for i, tab in enumerate(tabs):
            tab.display = i in shown
        at = None if active is None else active + 1
        more.update(self._more_text(len(tabs) - len(shown), len(tabs), cols, at))
        more.tooltip = f"Show all {len(tabs)} harnesses"
        more.display = True

    def _fit_cluster(self, pieces: dict[str, Forms], slot: int) -> None:
        pick = dict.fromkeys(pieces, 0)
        for name, form in STEPS:
            if _width(pieces, pick) <= slot:
                break
            if name in pieces and form < len(pieces[name]):
                pick[name] = form
        for name in PIECES:
            cell = self.piece(name)
            content = pieces[name][pick[name]] if name in pieces else None
            cell.display = content is not None
            if content is not None:
                cell.update(content)

    def _cluster(self) -> dict[str, Forms]:
        """The cluster pieces for the current state, each with its forms from long to short."""
        app = app_of(self)
        ins = app.data.insights
        self._settled = ins is not None and not ins.writable
        if ins is None or not ins.writable:
            return {}
        if self._job is not None:
            return {"job": [self._job_text()]}
        check = self.piece("check")
        check.set_class(self.checking, "-idle")
        if self._checking:
            check.tooltip = None
            return {"check": [self._spin_text(Content("Checking…"))]}
        upd = app.data.updates or {}
        if not upd.get("checked_at"):
            return {}
        self._settled = True
        out: dict[str, Forms] = {}
        fresh = views.new_total(ins)
        if fresh and app.state.view != "new":
            out["new"] = [
                Content(f"+ {views.plural(fresh, 'new skill')}"),
                Content(f"+ {fresh} new"),
                None,
            ]
            self.piece("new").tooltip = f"Show the {views.plural(fresh, 'new skill')}"
        st = app.state.view_state()
        outdated = app.data.counts(st)["updates"]
        if outdated:
            up = Content.styled("↑ ", ACCENT)
            out["count"] = [
                up + _digits(views.plural(outdated, "update")),
                up + _digits(str(outdated)),
                None,
            ]
            self.piece("count").tooltip = f"Show the {views.plural(outdated, 'update')}"
        errors = upd.get("errors") or {}
        if errors:
            n = len(errors)
            unchecked = f"{views.plural(n, 'source')} unchecked"
            out["warn"] = [Content(f"! {x}") for x in (unchecked, f"{n} unchecked", str(n))] + [
                None
            ]
            self.piece("warn").tooltip = "\n".join(errors.values())
        just = Content.assemble(TICK, "Checked just now")
        recent = time.monotonic() < self._just_until
        if outdated:
            out["all"] = [Content("Update all")]
            out["check"] = [just if recent else Content("Check again"), None]
            check.tooltip = None
        else:
            done = Content.assemble(TICK, "Up to date")
            out["check"] = [just, done] if recent else [done]
            check.tooltip = _hint("Check again", "check_again")
        return out

    def _job_text(self) -> Content:
        from .progress import headline

        job = self._job or {}
        text = _digits(headline(job))
        if not job.get("done"):
            return self._spin_text(text)
        items = (job.get("items") or {}).values()
        ok = all(i.get("state") == "done" for i in items)
        return Content.assemble(TICK if ok else ("✗ ", "$atlas-danger"), text)

    def _spin_text(self, text: Content) -> Content:
        if self.app.animation_level != "full":
            return text
        return Content.styled(SPINNER[self._frame % len(SPINNER)] + " ", ACCENT) + text

    # The spinner and the check indicator

    def _busy_piece(self) -> str | None:
        if self._job is not None:
            return None if self._job.get("done") else "job"
        return "check" if self._checking else None

    def _sync_spinner(self) -> None:
        if self._spinner is None:
            return
        if self._busy_piece() and self.app.animation_level == "full":
            self._spinner.resume()
        else:
            self._spinner.pause()

    def _spin(self) -> None:
        name = self._busy_piece()
        if name is None:
            return
        self._frame += 1
        text = self._job_text() if name == "job" else self._spin_text(Content("Checking…"))
        self.piece(name).update(text)

    def _track_check(self) -> None:
        """Show `Checking…` after 0.3 s of work, then keep it 0.5 s or more, so it never flashes."""
        app = app_of(self)
        loading = "updates" in app.data.loading
        now = time.monotonic()
        if loading and self._check_since is None:
            self._check_since = now
            self._rechecking = app.data.updates is not None
            self._stop_check_timer()
            if not self._checking:
                self._check_timer = self.set_timer(SHOW_AFTER, self._show_checking)
        elif not loading and self._check_since is not None:
            self._check_since = None
            self._stop_check_timer()
            if self._rechecking and "updates" not in app.data.errors:
                self._just_until = now + JUST_CHECKED
                self.set_timer(JUST_CHECKED + 0.05, self.draw)
            if self._checking:
                wait = self._shown_at + SHOW_FOR - now
                if wait > 0:
                    self._check_timer = self.set_timer(wait, self._hide_checking)
                else:
                    self._checking = False

    def _stop_check_timer(self) -> None:
        if self._check_timer is not None:
            self._check_timer.stop()
            self._check_timer = None

    def _show_checking(self) -> None:
        self._check_timer = None
        self._checking, self._shown_at = True, time.monotonic()
        self.draw()

    def _hide_checking(self) -> None:
        self._check_timer = None
        self._checking = False
        self.draw()

    # Actions

    def _show_errors(self) -> None:
        show_source_errors(app_of(self), self.piece("warn"))

    def _open_menu(self) -> None:
        open_harness_menu(app_of(self), self.piece("more"))

    async def _check_again(self) -> None:
        if not self.checking:
            await app_of(self).action_run("jobs:check_again")

    async def _update_all(self) -> None:
        await app_of(self).action_run("jobs:update_all")


def _below(app: AtlasApp, anchor: Widget | None, width: int) -> Offset:
    """The top-left cell for a popup of this width under the anchor, kept on the screen."""
    region = anchor.region if anchor is not None and anchor.display else None
    x, y = (region.x, region.bottom) if region else (1, 1)
    return Offset(max(0, min(x, app.size.width - width)), y)


class HarnessMenu(AtlasModal[str]):
    """Every harness, with where its switches write. Enter or a click picks one."""

    DEFAULT_CSS = """
    HarnessMenu { align: left top; }
    HarnessMenu > OptionList {
        height: auto; max-height: 20; padding: 0;
        background: $atlas-surface-1; border: round $atlas-border-strong;
        scrollbar-size-vertical: 1;
    }
    HarnessMenu > OptionList:focus {
        border: round $atlas-border-strong; background-tint: transparent;
    }
    HarnessMenu > OptionList > .option-list--option { padding: 0 1; }
    HarnessMenu > OptionList > .option-list--option-hover { background: $atlas-surface-2; }
    HarnessMenu > OptionList:focus > .option-list--option-highlighted {
        background: $atlas-selection; color: $atlas-text; text-style: none;
    }
    """

    def __init__(self, choices: list[tuple[str, Content]], current: str, at: Offset, width: int):
        super().__init__()
        self.choices, self.current, self.at, self.menu_width = choices, current, at, width

    def compose(self) -> ComposeResult:
        yield OptionList(*(Option(prompt, id=h) for h, prompt in self.choices))

    def on_mount(self) -> None:
        menu = self.query_one(OptionList)
        menu.styles.width = self.menu_width
        menu.styles.offset = (self.at.x, self.at.y)
        ids = [h for h, _ in self.choices]
        menu.highlighted = ids.index(self.current) if self.current in ids else 0
        menu.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)


def open_harness_menu(app: AtlasApp, anchor: Widget | None = None) -> None:
    """Show every harness in a menu under the header. Picking one switches to it."""
    ins = app.data.insights
    ids = views.harness_choices(ins) if ins else []
    if not ids:
        return
    labels = {h: label_of(app, h) for h in ids}
    pad = max(cell_len(label) for label in labels.values()) + 2
    cap = min(64, app.size.width - 2)
    prompts = []
    for h in ids:
        prompt = Content.assemble((labels[h].ljust(pad), TEXT), meta_of(app, h))
        prompts.append((h, prompt.truncate(cap - 4, ellipsis=True)))
    width = min(cap, max(p.cell_length for _, p in prompts) + 4)
    if anchor is None:
        anchor = app.main.query_one(AtlasHeader).menu_anchor()

    def picked(harness: str | None) -> None:
        if harness:
            app.set_state(harness=harness)

    menu = HarnessMenu(prompts, app.state.harness, _below(app, anchor, width), width)
    app.push_screen(menu, picked)


class SourceErrors(AtlasModal[bool]):
    """The sources the last check could not read, with their errors, and Check again."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "again", "Check again", show=False)]
    DEFAULT_CSS = """
    SourceErrors { align: left top; }
    SourceErrors > #box {
        height: auto; padding: 0 1 1 2;
        background: $atlas-surface-1; border: round $atlas-border-strong;
    }
    SourceErrors #top { height: 1; }
    SourceErrors #title { width: 1fr; color: $atlas-text; text-style: bold; }
    SourceErrors .err { margin-top: 1; color: $atlas-muted; }
    SourceErrors #actions { height: 1; margin-top: 1; }
    SourceErrors #again { background: $atlas-accent; color: $atlas-on-accent; }
    SourceErrors #again:hover { background-tint: $atlas-text 12%; }
    SourceErrors #again.-pressed { background-tint: $atlas-text 22%; }
    """

    def __init__(self, errors: dict[str, str], at: Offset, width: int):
        super().__init__()
        self.errors, self.at, self.box_width = errors, at, width

    def compose(self) -> ComposeResult:
        n = len(self.errors)
        with Vertical(id="box"):
            with Horizontal(id="top"):
                yield Static(f"Could not check {views.plural(n, 'source')}", id="title")
                yield CloseCell()
            for repo, error in self.errors.items():
                text = Content.assemble((repo, TEXT), "\n", error)
                yield Static(text, classes="err", markup=False)
            with Horizontal(id="actions"):
                yield Cell(Content("Check again"), run=self.action_again, id="again")

    def on_mount(self) -> None:
        box = self.query_one("#box")
        box.styles.width = self.box_width
        box.styles.offset = (self.at.x, self.at.y)

    def action_again(self) -> None:
        self.dismiss(True)


def show_source_errors(app: AtlasApp, anchor: Widget | None = None) -> None:
    """List the sources the last update check could not read. Check again from there."""
    errors = (app.data.updates or {}).get("errors") or {}
    if not errors:
        return
    width = min(64, app.size.width - 2)
    if anchor is None:
        anchor = app.main.query_one(AtlasHeader).piece("warn")

    async def done(again: bool | None) -> None:
        if again:
            await app.action_run("jobs:check_again")

    app.push_screen(SourceErrors(dict(errors), _below(app, anchor, width), width), done)
