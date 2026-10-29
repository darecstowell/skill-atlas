"""The view chip with its count and menu, and the search box."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar

from rich.cells import cell_len
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.content import Content
from textual.geometry import Region
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ...core import views
from .. import keys
from ..messages import DataChanged, JobChanged, StateChanged
from ..screens import AtlasModal
from . import app_of
from .header import Cell

if TYPE_CHECKING:
    from ..app import AtlasApp
    from .skill_list import SkillList

ICON = 3  # the `/` and `✕` cells
SPACE = 2
SEARCH, SEARCH_WIDE, WIDE = 28, 34, 160
COMPACT_BELOW = 100
CHIP = 16
QUERY_ROOM = 12
PLACEHOLDER = "Search skills, sources, paths"
WAIT = "Reading your agent sessions…"
MENU = (" ▾", "$atlas-muted")
MORE = ("costly", "similar", "diverged")  # views the menu offers only when they have skills
UPDATE_ALL = "run('jobs:update_all')"
# Counts that move with each toggle, or that arrive late, keep the width of the All count,
# so the chip's ▾ holds still.
BOUND = frozenset({"all", "on", "off", "unused"})
FIRST = ("all", "on", "off", "updates", "unused")


def digit(view: str) -> str:
    """The digit key that shows the view, from the app's table; "" when it has none."""
    from ..app import DIGIT_VIEWS

    return str(DIGIT_VIEWS.index(view) + 1) if view in DIGIT_VIEWS else ""


def update_plan(app: AtlasApp) -> tuple[int, int]:
    """(skills Update all updates, outdated skills it skips for local edits), as jobs.update_all."""
    ins = app.data.insights
    if ins is None or not ins.writable:
        return 0, 0
    safe, edited = views.update_targets(
        ins, [s for s in ins.skills if views.live(app.state.harness, s)]
    )
    return len(safe), len(edited)


def _key(action: str) -> str:
    return next((k.show for k in keys.KEYS if k.action == action and k.show), "")


def _tab(view: str) -> views.Tab:
    label, title = next((lab, t) for v, lab, t in views.VIEWS if v == view)
    return views.Tab(id=view, label=label, title=title, count=None, waiting=False)


def fit_placeholder(cells: int) -> str:
    """The web placeholder, cut at a comma to fit, so it never ends mid-word."""
    text = PLACEHOLDER
    while cell_len(text) > cells and ", " in text:
        text = text.rsplit(", ", 1)[0]
    return text if cell_len(text) <= cells else ""


class ViewChip(Static):
    """The active view and its count. A click, or enter while it has focus, opens the view menu.

    It takes focus only when the strip gives it, so it is never a tab-key stop.
    """

    ALLOW_SELECT = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "step(-1)", "Show the previous view", show=False),
        Binding("right", "step(1)", "Show the next view", show=False),
        Binding("enter,space", "open", "Show every view", show=False),
        Binding("down,escape", "leave", "Go to the list", show=False),
    ]
    DEFAULT_CSS = """
    ViewChip {
        width: auto; height: 1; padding: 0 1;
        background: $atlas-surface-3; color: $atlas-text; pointer: pointer;
    }
    ViewChip:hover { background-tint: $atlas-text 8%; }
    ViewChip.-pressed { background-tint: $atlas-text 16%; }
    ViewChip:focus { background: $atlas-selection; }
    """

    def __init__(self) -> None:
        super().__init__(id="view")
        self.given = False

    def allow_focus(self) -> bool:
        return self.given

    def on_blur(self, event: events.Blur) -> None:
        if not isinstance(self.app.screen, ViewMenu):
            self.given = False

    def action_step(self, step: int) -> None:
        self.strip.step_view(step)

    def action_open(self) -> None:
        self.strip.open_menu()

    def action_leave(self) -> None:
        app_of(self).main.query_one("#list").focus()

    @property
    def strip(self) -> ViewStrip:
        return next(a for a in self.ancestors if isinstance(a, ViewStrip))

    def show(self, tab: views.Tab, digits: int, loading: bool) -> int:
        """Draw the chip; return the cells it takes."""
        count = tab["count"]
        shown = "–" if loading or tab["waiting"] or count is None else str(count)
        tone = "$atlas-faint" if shown == "–" else "$atlas-muted"
        body = Content.assemble(tab["label"], " ", (f"{shown:<{digits}}", tone), MENU)
        self.update(body)
        tip = [tab["title"]] if tab["title"] else []
        if tab["waiting"]:
            tip.append(WAIT)
        key = _key("view(1)")
        tip.append(f"Show another view · {key}" if key else "Show another view")
        self.tooltip = "\n".join(tip)
        return body.cell_length + 2

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 1:
            self.add_class("-pressed")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.remove_class("-pressed")

    def on_leave(self, event: events.Leave) -> None:
        self.remove_class("-pressed")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if event.button == 1:
            self.strip.open_menu()


class ViewMenu(AtlasModal[str]):
    """Every view the strip offers, with counts and keys. Opens under the view chip."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding(str(n), f"pick({n})", show=False) for n in range(1, 10)
    ]
    DEFAULT_CSS = """
    ViewMenu { align: left top; }
    ViewMenu > OptionList, ViewMenu > OptionList:focus {
        width: auto; height: auto; max-height: 16; padding: 0;
        border: round $atlas-border-strong; background: $atlas-surface-1;
        background-tint: $foreground 0%;
    }
    ViewMenu > OptionList > .option-list--option { padding: 0 1; }
    """

    def __init__(self, tabs: list[views.Tab], active: str, digits: int, at: Region) -> None:
        super().__init__()
        self.tabs = tabs
        self.active = active
        self.digits = digits
        self.at = at
        self.label_w = max(cell_len(t["label"]) for t in tabs)

    def compose(self) -> ComposeResult:
        options = []
        for t in self.tabs:
            shown = "–" if t["waiting"] else str(t["count"] or 0)
            mine = t["id"] == self.active
            body = Content.assemble(
                (f"{t['label']:<{self.label_w}}", "$atlas-text" if mine else "$atlas-muted"),
                "  ",
                (f"{shown:>{self.digits}}", "$atlas-muted" if mine else "$atlas-faint"),
                "  ",
                (digit(t["id"]) or " ", "$atlas-accent"),
            )
            options.append(Option(body, id=t["id"], disabled=t["waiting"] and not mine))
        yield OptionList(*options)

    def on_mount(self) -> None:
        menu = self.query_one(OptionList)
        ids = [t["id"] for t in self.tabs]
        menu.highlighted = ids.index(self.active) if self.active in ids else 0
        menu.styles.offset = (max(0, self.at.x), self.at.bottom)
        menu.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def action_pick(self, n: int) -> None:
        from ..app import DIGIT_VIEWS

        view = DIGIT_VIEWS[n - 1] if n <= len(DIGIT_VIEWS) else ""
        if any(t["id"] == view and not t["waiting"] for t in self.tabs):
            self.dismiss(view)


class SearchInput(Input):
    """The search text. Typing filters the list at once."""

    DEFAULT_CSS = """
    SearchInput, SearchInput:focus {
        width: 1fr; height: 1; border: none; padding: 0;
        background: transparent; background-tint: $foreground 0%;
    }
    SearchInput > .input--placeholder { color: $atlas-faint; }
    SearchInput > .input--cursor { text-style: none; }
    """


class SearchClear(Static):
    """The `✕` that clears the search. It shows a pressed state until mouse up."""

    ALLOW_SELECT = False

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.add_class("-pressed")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.remove_class("-pressed")

    def on_leave(self, event: events.Leave) -> None:
        self.remove_class("-pressed")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        next(a for a in self.ancestors if isinstance(a, ViewStrip)).clear_search()


class SearchBox(Horizontal):
    """`/`, the input, the result count, and `✕`. Folds to the `/` cell when the strip is short."""

    DEFAULT_CSS = """
    SearchBox {
        width: 28; height: 1; margin-left: 2;
        background: $atlas-surface-2; pointer: text;
    }
    SearchBox:focus-within { background: $atlas-surface-3; }
    SearchBox > #search-icon { width: 3; content-align: center middle; color: $atlas-faint; }
    SearchBox > #search-chip { display: none; width: auto; color: $atlas-text; }
    SearchBox > #search-count { display: none; width: auto; padding-left: 1; color: $atlas-muted; }
    SearchBox > #search-clear {
        display: none; width: 3; content-align: center middle;
        color: $atlas-muted; pointer: pointer;
    }
    SearchBox > #search-clear:hover { background: $atlas-surface-2; color: $atlas-text; }
    SearchBox > #search-clear.-pressed { background: $atlas-surface-3; }
    SearchBox.-filled > #search-count, SearchBox.-filled > #search-clear { display: block; }
    SearchBox.-folded { width: auto; pointer: pointer; }
    SearchBox.-folded:hover { background: $atlas-surface-3; }
    SearchBox.-folded:hover > #search-icon { color: $atlas-text; }
    SearchBox.-folded > SearchInput, SearchBox.-folded > #search-count { display: none; }
    SearchBox.-folded.-filled > #search-chip { display: block; }
    """

    def compose(self) -> ComposeResult:
        yield Static("/", id="search-icon")
        yield SearchInput(placeholder=PLACEHOLDER, id="search", compact=True, select_on_focus=False)
        yield Static(id="search-chip")
        yield Static(id="search-count")
        yield SearchClear("✕", id="search-clear")

    def on_mount(self) -> None:
        self.query_one("#search-clear").tooltip = "Clear search · esc"
        self.query_one("#search-icon").tooltip = "Search · /"

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if not isinstance(event.widget, SearchInput):
            next(a for a in self.ancestors if isinstance(a, ViewStrip)).focus_search(select=False)


class ViewStrip(Horizontal):
    """The view chip, Update all in the Updates view, and the search box.

    focus_search() is the API.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "search_escape", "Clear the search or go to the list", show=False),
        Binding("down", "to_results", "Go to the first result", show=False),
    ]
    DEFAULT_CSS = """
    ViewStrip { height: 1; padding: 0 1; background: $background; color: $atlas-muted; }
    ViewStrip > #views { width: 1fr; height: 1; }
    ViewStrip #update-all { margin-left: 2; background: $atlas-accent; color: $atlas-on-accent; }
    ViewStrip #update-all:hover { background-tint: $atlas-text 12%; }
    ViewStrip #update-all.-pressed { background-tint: $atlas-text 22%; }
    ViewStrip #update-note { width: auto; margin-left: 1; color: $atlas-faint; }
    ViewStrip.-open > #views { display: none; }
    ViewStrip.-open > SearchBox { width: 1fr; margin-left: 0; }
    """

    def __init__(
        self, *, name: str | None = None, id: str | None = None, classes: str | None = None
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._tabs: list[views.Tab] = []
        self._chip_w = 0
        self._digits = 2
        self._results: int | None = None
        self._last: views.ViewState | None = None
        self._job: dict | None = None
        self._button_w = self._note_w = 0
        self._overlap: tuple[object, str, dict[str, int]] = (None, "", {})

    def compose(self) -> ComposeResult:
        with Horizontal(id="views"):
            yield ViewChip()
            yield Cell(run=self._update_all, id="update-all")
            yield Static(id="update-note", markup=False)
        yield SearchBox()

    @property
    def search(self) -> SearchInput:
        return self.query_one(SearchInput)

    @property
    def chip(self) -> ViewChip:
        return self.query_one(ViewChip)

    # API

    def focus_search(self, select: bool = True) -> None:
        """Put the cursor in the search box; `/` also selects the old text, as on the web."""
        app = app_of(self)
        if app.state.marked:
            app.notify("To search, first clear the marks: press esc.")
            return
        self.add_class("-open")
        self._fit()
        box = self.search
        box.focus()
        if select:
            box.select_all()

    def clear_search(self) -> None:
        self.search.value = ""

    def open_menu(self) -> None:
        """Show every view in a menu under the chip; the pick becomes the view."""
        app = app_of(self)
        if not self._tabs:
            return

        def picked(view: str | None) -> None:
            if view:
                app.set_state(view=view)

        at = self.chip.region or self.region
        app.push_screen(ViewMenu(self._tabs, app.state.view, self._digits, at), picked)

    def focus_chip(self) -> None:
        """Give focus to the view chip, as the web does after a "Show all skills" link."""
        chip = self.chip
        chip.given = True
        chip.focus(scroll_visible=False)

    def step_view(self, step: int) -> None:
        """Show the previous or next view that can be shown; focus follows it."""
        app = app_of(self)
        ids = [t["id"] for t in self._tabs if not t["waiting"]]
        if app.state.view in ids:
            i = max(0, min(len(ids) - 1, ids.index(app.state.view) + step))
            app.set_state(view=ids[i])

    # Events

    def on_mount(self) -> None:
        from .. import jobs

        self.search.cursor_blink = self.app.animation_level == "full"
        self._last = app_of(self).state.view_state()
        self._job = jobs.current(app_of(self))
        self._draw()

    def on_resize(self, event: events.Resize) -> None:
        self._fit()

    def on_data_changed(self, event: DataChanged) -> None:
        self._draw()

    def on_job_changed(self, event: JobChanged) -> None:
        changed = (self._job is None) != (event.view is None)
        self._job = event.view
        if changed:
            self._sync_update()
            self._fit()

    def on_state_changed(self, event: StateChanged) -> None:
        fields = event.fields
        app = app_of(self)
        state = app.state
        last, self._last = self._last, state.view_state()
        if fields & {"harness", "view", "show_project", "show_stale"}:
            self._draw()
        if "view" in fields and (app.focused is self.chip or self._left_empty_list(last)):
            self.focus_chip()
        if "query" in fields:
            if self.search.value.strip() != state.query.strip():
                self.search.value = state.query
            self.show_results()
        if "marked" in fields and state.marked and self.search.has_focus:
            self._to_list()
        if "motion" in fields:
            self.search.cursor_blink = self.app.animation_level == "full"

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        app_of(self).set_state(query=event.value.strip())
        self._fit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_to_results()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self._fit()
        self.show_results()

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        self.remove_class("-open")
        self._fit()

    def action_search_escape(self) -> None:
        if self.search.value:
            self.clear_search()
        else:
            self._to_list()

    def action_to_results(self) -> None:
        """Go to the list, on its first result when a search is set."""
        app = app_of(self)
        first = self._first_result() if app.state.query.strip() else None
        if first is not None:
            path, key = first
            app.set_state(selected=path, selected_key=key)
        self._to_list()

    # Drawing

    def _to_list(self) -> None:
        app_of(self).main.query_one("#list").focus()

    def _left_empty_list(self, last: views.ViewState | None) -> bool:
        """The view went back to All from an empty list that had focus: its link went away."""
        app = app_of(self)
        ins = app.data.insights
        if ins is None or last is None or app.state.view != "all" or last.view == "all":
            return False
        if app.focused is not app.main.query_one("#list"):
            return False
        return not views.sections(ins, last)

    def _tab_list(self) -> tuple[list[views.Tab], bool]:
        app = app_of(self)
        ins, st = app.data.insights, app.state.view_state()
        if ins is None:
            ids = FIRST if st.view in FIRST else (*FIRST, st.view)
            return [_tab(v) for v in ids], True
        n = {**app.data.counts(st), **self._overlap_counts(ins, st)}
        tabs = views.view_tabs(ins, st, n)
        have = {t["id"] for t in tabs}
        for v, label, title in views.VIEWS:
            if v in MORE and v not in have and n[v]:
                tabs.append(views.Tab(id=v, label=label, title=title, count=n[v], waiting=False))
        order = [v for v, _, _ in views.VIEWS]
        return sorted(tabs, key=lambda t: order.index(t["id"])), False

    def _overlap_counts(self, ins: views.Insights, st: views.ViewState) -> dict[str, int]:
        """Skills the Similar and Diverged views list, as the other counts: once per Insights."""
        owner, harness, n = self._overlap
        if owner is not ins or harness != st.harness:
            lv = views.loaded_skills(ins, st.harness)
            n = {
                v: sum(1 for s in lv if views.overlap_view(ins, replace(st, view=v), s))
                for v in ("similar", "diverged")
            }
            self._overlap = (ins, st.harness, n)
        return n

    def _draw(self) -> None:
        view = app_of(self).state.view
        tabs, loading = self._tab_list()
        self._tabs = tabs
        n_all = next((t["count"] for t in tabs if t["id"] == "all"), None)
        bound = len(str(n_all)) if n_all is not None else 3
        self._digits = max([2, bound, *(len(str(t["count"] or 0)) for t in tabs)])
        tab = next((t for t in tabs if t["id"] == view), None) or _tab(view)
        need = len(str(tab["count"])) if tab["count"] is not None else 1
        digits = max(need, bound) if view in BOUND else need
        self._chip_w = self.chip.show(tab, digits, loading)
        self._sync_update()
        self._fit()

    def _sync_update(self) -> None:
        """Show Update all in the Updates view, and a note when it skips skills you edited."""
        app = app_of(self)
        shown = app.state.view == "updates" and self._job is None
        n, edited = update_plan(app) if shown else (0, 0)
        button = self.query_one("#update-all", Cell)
        note = self.query_one("#update-note", Static)
        button.display = bool(n)
        label = text = ""
        if n:
            label = f"Update {n}" if edited else "Update all"
            button.update(label)
            tip = "Update each skill you did not edit" if edited else "Update each skill"
            key = _key(UPDATE_ALL)
            button.tooltip = f"{tip} · {key}" if key else tip
        if edited:
            text = f"Skips {edited} you edited" if n else "Skills you edited update one at a time"
            note.update(text)
            note.tooltip = "An update replaces your edits, so update those skills one at a time."
        self._button_w = cell_len(label) + 4 if label else 0
        self._note_w = cell_len(text) + 1 if text else 0

    def _fit(self) -> None:
        """Lay out the row for its width: the chip, then the search box or its `/` cell."""
        width = self.content_size.width
        if not width:
            return
        app = app_of(self)
        box = self.query_one(SearchBox)
        query = self.search.value
        search_w = SEARCH_WIDE if app.size.width >= WIDE else SEARCH
        lead = self._chip_w + self._button_w
        compact = app.size.width < COMPACT_BELOW or lead + self._note_w + SPACE + search_w > width
        is_open = compact and (self.has_class("-open") or self.search.has_focus)
        self.set_class(is_open, "-open")
        box.set_class(compact and not is_open, "-folded")
        box.set_class(bool(query), "-filled")
        box.styles.width = None if compact else search_w
        if compact and not is_open:
            cut = query if cell_len(query) <= CHIP else query[: CHIP - 1] + "…"
            self.query_one("#search-chip", Static).update(Content(cut))
            folded = ICON + (cell_len(cut) + ICON if query else 0)
            fits = lead + self._note_w + SPACE + folded <= width
            self.query_one("#update-note").display = bool(self._note_w) and fits
            return
        self.query_one("#update-note").display = bool(self._note_w)
        self.search.placeholder = fit_placeholder((width if is_open else search_w) - ICON - 1)

    # Search results

    def on_skill_list_results_changed(self, event: SkillList.ResultsChanged) -> None:
        event.stop()
        self._results = event.n
        self.show_results()

    def show_results(self) -> None:
        """Show how many rows the list shows for the search; hidden with no search."""
        out = self.query_one("#search-count", Static)
        n = self._results
        if n is None or not app_of(self).state.query.strip():
            out.update("")
            return
        words = views.plural(n, "result")
        room = self.query_one(SearchBox).size.width - 2 * ICON - 1 - len(words)
        out.update(words if room >= QUERY_ROOM else str(n))
        out.tooltip = words

    def _first_result(self) -> tuple[str | None, str | None] | None:
        """(skill path, None) or (None, available item key) for the top row the list shows."""
        app = app_of(self)
        ins = app.data.insights
        if ins is None:
            return None
        for sec in views.sections(ins, app.state.view_state(), app.state.folds()):
            if not sec["open"]:
                continue
            for g in sec["groups"]:
                if g["open"] and g["skills"]:
                    return g["skills"][0]["path"], None
                if g["available_open"] and g["available"]:
                    return None, f"a:{g['key']}:{g['available'][0]['path']}"
            if sec["rows"]:
                return sec["rows"][0]["path"], None
        return None

    async def _update_all(self) -> None:
        await app_of(self).action_run("jobs:update_all")


def open_view_menu(app: AtlasApp) -> None:
    """Show every view in a menu under the view chip. Picking one shows it."""
    app.main.query_one(ViewStrip).open_menu()
