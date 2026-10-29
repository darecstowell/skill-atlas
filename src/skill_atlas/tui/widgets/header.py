"""The top row: the brand, the harness chip, and the update status."""

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

NARROW = 100
GAP = 2
CHIP_MIN = 12  # cells the harness chip keeps; the cluster gets the rest
MENU_W = 72
LOGO, BRAND = " ╱ ", " Skill Atlas"
ALL = "All harnesses"
MENU = (" ▾", "$atlas-muted")
SPIN = 0.08
SHOW_AFTER, SHOW_FOR, JUST_CHECKED = 0.3, 0.5, 1.4
# How the cluster gets shorter: (piece, form). Each step picks a shorter form or drops the piece.
STEPS = (("check", 1), ("warn", 1), ("updates", 1))
PIECES = ("check", "warn", "updates", "job")
TEXT, ACCENT = "$atlas-text", "$atlas-accent"
TICK = ("✓ ", "$atlas-on")
DIGITS = re.compile(r"\d+")
CHECK_AGAIN = "run('jobs:check_again')"

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


def _hint(tip: str, action: str) -> str:
    """The tooltip plus the key that does the same, from keys.KEYS: `Check again · ctrl+r`."""
    key = next((k.show for k in keys.KEYS if k.action == action and k.show), "")
    return f"{tip} · {key}" if key else tip


def _cells(c: Content | None) -> int:
    return 0 if c is None else c.cell_length + 2


def _width(pieces: dict[str, Forms], pick: dict[str, int]) -> int:
    """Cells the cluster takes with these forms, with one cell before each piece."""
    cells = [_cells(pieces[p][pick[p]]) for p in pieces if pieces[p][pick[p]] is not None]
    return sum(cells) + len(cells)


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


class AtlasHeader(Vertical):
    """The brand, the harness chip, and the update cluster in one row; a band when stale."""

    DEFAULT_CSS = """
    AtlasHeader { height: auto; }
    AtlasHeader > #bar { height: 1; padding: 0 1; background: $atlas-surface-1; }
    AtlasHeader #brand { width: auto; margin-right: 2; }
    AtlasHeader #left { width: 1fr; height: 1; }
    AtlasHeader #skeleton { width: 22; height: 1; background: $atlas-surface-2; }
    AtlasHeader #harness { background: $atlas-surface-3; color: $atlas-text; }
    AtlasHeader #harness:hover { background-tint: $atlas-text 8%; }
    AtlasHeader #harness.-pressed { background-tint: $atlas-text 16%; }
    AtlasHeader #harness.-idle { background: transparent; background-tint: $foreground 0%; }
    AtlasHeader #cluster { height: 1; margin-left: 1; align-horizontal: right; }
    AtlasHeader #cluster > Cell { margin-left: 1; }
    AtlasHeader #warn { color: $atlas-warn; }
    AtlasHeader > #stale {
        display: none; height: 1; padding: 0 1; text-align: center;
        background: $atlas-warn-tint; color: $atlas-warn;
    }
    """

    def __init__(
        self, *, name: str | None = None, id: str | None = None, classes: str | None = None
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
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
            with Horizontal(id="left"):
                yield Static(id="skeleton")
                yield Cell(run=self._open_menu, id="harness")
            with Horizontal(id="cluster"):
                yield Cell(run=self._check_again, id="check")
                yield Cell(run=self._show_errors, id="warn")
                yield Cell(run=lambda: app_of(self).set_state(view="updates"), id="updates")
                yield Cell(id="job", classes="-idle")
        yield Static(id="stale", markup=False)

    def on_mount(self) -> None:
        from .. import jobs

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
        if event.fields & {"harness", "view", "marked"}:
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
        """Where the harness menu opens: under the harness chip."""
        return self.piece("harness")

    # Drawing

    def draw(self) -> None:
        app = app_of(self)
        cols = app.size.width
        brand = Content.styled(LOGO, f"$atlas-on-accent on {ACCENT}")
        if cols >= NARROW:
            brand += Content.styled(BRAND, f"bold {TEXT}")
        self.query_one("#brand", Static).update(brand)
        room = max(0, cols - 2 - brand.cell_length - GAP - 1)
        name, tail = self._sync_chip()
        chip_w = 0 if name is None else cell_len(name) + tail.cell_length + 2
        pieces = self._cluster()
        width = self._fit_cluster(pieces, room - chip_w)
        if self._settled:
            self._held = width
        slot = max(0, min(max(width, self._held or 0), room - min(chip_w, CHIP_MIN)))
        self.query_one("#cluster").styles.width = slot
        if name is not None:
            fit = max(1, room - slot - tail.cell_length - 2)
            self.piece("harness").update(Content(name).truncate(fit, ellipsis=True) + tail)
        stale = bool(((app.data.scan or {}).get("server") or {}).get("stale"))
        band = self.query_one("#stale", Static)
        band.display = stale
        if stale:
            band.update("! Skill Atlas changed on disk. Quit and start it again.")
        self._sync_spinner()

    def _sync_chip(self) -> tuple[str | None, Content]:
        """The active harness's name (None hides the chip) and the menu glyph when it has one."""
        app = app_of(self)
        ins = app.data.insights
        ids = views.harness_choices(ins) if ins else []
        loading = app.data.scan is None and "scan" not in app.data.errors
        self.query_one("#skeleton").display = loading
        chip = self.piece("harness")
        chip.display = bool(ids)
        if not ids:
            return None, Content("")
        h = app.state.harness
        many = len(ids) > 1
        chip.set_class(not many, "-idle")
        meta = meta_of(app, h)
        tip = [meta[:1].upper() + meta[1:]] if meta else []
        if many:
            tip.append(_hint("Switch harness", "harness(-1)"))
        chip.tooltip = "\n".join(tip) or None
        return label_of(app, h), Content.assemble(MENU) if many else Content("")

    def _fit_cluster(self, pieces: dict[str, Forms], room: int) -> int:
        """Pick the longest forms that fit in room, show them, and return their width."""
        pick = dict.fromkeys(pieces, 0)
        for name, form in STEPS:
            if _width(pieces, pick) <= room:
                break
            if name in pieces and form < len(pieces[name]):
                pick[name] = form
        for name in PIECES:
            cell = self.piece(name)
            content = pieces[name][pick[name]] if name in pieces else None
            cell.display = content is not None
            if content is not None:
                cell.update(content)
        return _width(pieces, pick)

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
        outdated = app.data.counts(app.state.view_state())["updates"]
        done = Content.assemble(TICK, "Up to date")
        if time.monotonic() < self._just_until:
            out["check"] = [Content.assemble(TICK, "Checked just now"), None if outdated else done]
        elif not outdated:
            out["check"] = [done]
        check.tooltip = _hint("Check again", CHECK_AGAIN)
        errors = upd.get("errors") or {}
        if errors:
            n = len(errors)
            out["warn"] = [Content(f"! {n} not checked"), Content(f"! {n}")]
            lines = [f"Could not check {views.plural(n, 'source')}", *errors.values()]
            self.piece("warn").tooltip = "\n".join(lines)
        if outdated and app.state.view != "updates" and not app.state.marked:
            from .viewstrip import digit

            arrow = ("↑ ", ACCENT)
            out["updates"] = [
                Content.assemble(arrow, _digits(views.plural(outdated, "update"))),
                Content.assemble(arrow, _digits(str(outdated))),
            ]
            tip, key = f"Show the {views.plural(outdated, 'skill')} with updates", digit("updates")
            self.piece("updates").tooltip = f"{tip} · {key}" if key else tip
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
        open_harness_menu(app_of(self), self.piece("harness"))

    async def _check_again(self) -> None:
        if not self.checking:
            await app_of(self).action_run("jobs:check_again")


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
    cap = min(MENU_W, app.size.width - 2)
    prompts = []
    for h in ids:
        note = (views.header_meta(ins, h) or [""])[-1] if ins else ""
        prompt = Content.assemble((labels[h].ljust(pad), TEXT), (note, "$atlas-muted"))
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
