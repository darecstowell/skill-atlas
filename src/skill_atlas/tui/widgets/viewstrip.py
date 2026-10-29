"""The view tabs with their counts, the notes on where switches write, and the search box."""

from __future__ import annotations

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
from ..messages import DataChanged, StateChanged
from ..screens import AtlasModal
from . import app_of

if TYPE_CHECKING:
    from .skill_list import SkillList

GAP = 1
EDGE = 3
SPACE = 2
SEARCH, SEARCH_WIDE, WIDE = 28, 34, 160
COMPACT_BELOW = 100
CHIP = 16
QUERY_ROOM = 12
PLACEHOLDER = "Search skills, sources, paths"
WAIT = "Reading your agent sessions…"
NO_COUNT = frozenset({"similar", "diverged"})
# Counts that move with each toggle, or that arrive late, keep the width of the All count.
BOUND = frozenset({"all", "on", "off", "unused"})
FIRST = ("all", "on", "off", "updates", "unused")


def digit(view: str) -> str:
    """The digit key that shows the view, from the app's table; "" when it has none."""
    from ..app import DIGIT_VIEWS

    return str(DIGIT_VIEWS.index(view) + 1) if view in DIGIT_VIEWS else ""


def _tab(view: str) -> views.Tab:
    label, title = next((lab, t) for v, lab, t in views.VIEWS if v == view)
    return views.Tab(id=view, label=label, title=title, count=None, waiting=False)


def fit_placeholder(cells: int) -> str:
    """The web placeholder, cut at a comma to fit, so it never ends mid-word."""
    text = PLACEHOLDER
    while cell_len(text) > cells and ", " in text:
        text = text.rsplit(", ", 1)[0]
    return text if cell_len(text) <= cells else ""


def window(widths: list[int], active: int, room: int) -> tuple[int, int]:
    """The tabs [i, j) that hold the active one, leftmost first, with room for edge cells."""
    n = len(widths)
    for i in range(active + 1):
        used = EDGE + GAP if i else 0
        j = i
        while j < n and used + widths[j] + (EDGE if j + 1 < n else 0) <= room:
            used += widths[j]
            j += 1
        if j > active:
            return i, j
    return active, active + 1


class ViewTab(Static):
    """One view: label and count. A click shows the view; the Unused tab waits for usage.

    A tab takes focus only when the strip gives it, so it is never a tab-key stop.
    """

    ALLOW_SELECT = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "step(-1)", "Show the previous view", show=False),
        Binding("right", "step(1)", "Show the next view", show=False),
        Binding("enter,space,down,escape", "leave", "Go to the list", show=False),
    ]
    DEFAULT_CSS = """
    ViewTab {
        width: auto; height: 1; padding: 0 1; margin-right: 1;
        color: $atlas-muted; pointer: pointer;
    }
    ViewTab:hover { color: $atlas-text; }
    ViewTab.-pressed { background: $atlas-surface-2; }
    ViewTab.-waiting, ViewTab.-waiting:hover { color: $atlas-faint; pointer: default; }
    ViewTab.-active { background: $atlas-surface-3; color: $atlas-text; }
    ViewTab:focus { background: $atlas-selection; color: $atlas-text; }
    """

    def __init__(self, view: str) -> None:
        super().__init__(id=f"tab-{view}")
        self.view = view
        self.given = False

    def allow_focus(self) -> bool:
        return self.given

    def on_blur(self, event: events.Blur) -> None:
        self.given = False

    def action_step(self, step: int) -> None:
        next(a for a in self.ancestors if isinstance(a, ViewStrip)).step_view(step)

    def action_leave(self) -> None:
        app_of(self).main.query_one("#list").focus()

    def show(self, tab: views.Tab, digits: int, active: bool, loading: bool) -> int:
        """Draw the tab; return the cells it takes, with its margin."""
        self.set_class(active, "-active")
        self.set_class((tab["waiting"] or loading) and not active, "-waiting")
        if self.view in NO_COUNT and not loading:
            body = Content(tab["label"])
        else:
            count = tab["count"]
            shown = "–" if loading or tab["waiting"] or count is None else str(count)
            tone = "$atlas-muted" if active and shown != "–" else "$atlas-faint"
            body = Content.assemble(tab["label"], " ", (f"{shown:>{digits}}", tone))
        self.update(body)
        tip = [tab["title"]] if tab["title"] else []
        if tab["waiting"]:
            tip.append(WAIT)
        if digit(self.view):
            tip.append(f"Press {digit(self.view)}")
        self.tooltip = "\n".join(tip) or None
        return body.cell_length + 2 + GAP

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if not self.has_class("-waiting"):
            self.add_class("-pressed")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.remove_class("-pressed")

    def on_leave(self, event: events.Leave) -> None:
        self.remove_class("-pressed")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if not self.has_class("-waiting"):
            app_of(self).set_state(view=self.view)


class ViewEdge(Static):
    """An edge cell: more tabs sit past this edge. A click lists every view."""

    ALLOW_SELECT = False
    DEFAULT_CSS = """
    ViewEdge {
        width: 3; height: 1; content-align: center middle;
        color: $atlas-faint; pointer: pointer;
    }
    ViewEdge#edge-left { margin-right: 1; }
    ViewEdge:hover { background: $atlas-surface-2; color: $atlas-text; }
    ViewEdge.-pressed { background: $atlas-surface-3; }
    """

    def on_mount(self) -> None:
        self.tooltip = "Show every view"

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.add_class("-pressed")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.remove_class("-pressed")

    def on_leave(self, event: events.Leave) -> None:
        self.remove_class("-pressed")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        strip = next(a for a in self.ancestors if isinstance(a, ViewStrip))
        strip.open_menu(self.region, right=self.id == "edge-right")


class ViewMenu(AtlasModal[str]):
    """Every view the strip shows, with counts and keys. Opens from the edge cells."""

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

    def __init__(
        self, tabs: list[views.Tab], active: str, digits: int, at: Region, right: bool
    ) -> None:
        super().__init__()
        self.tabs = tabs
        self.active = active
        self.digits = digits
        self.at = at
        self.right = right
        self.label_w = max(cell_len(t["label"]) for t in tabs)

    def compose(self) -> ComposeResult:
        options = []
        for t in self.tabs:
            shown = "" if t["id"] in NO_COUNT else "–" if t["waiting"] else str(t["count"] or 0)
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
        width = self.label_w + self.digits + 9
        x = self.at.right - width if self.right else self.at.x
        menu.styles.offset = (max(0, x), self.at.bottom)
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
    """The view tabs at the left, then the notes and the search box. focus_search() is the API."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "search_escape", "Clear the search or go to the list", show=False),
        Binding("down", "to_results", "Go to the first result", show=False),
    ]
    DEFAULT_CSS = """
    ViewStrip { height: 1; padding: 0 1; background: $background; color: $atlas-muted; }
    ViewStrip > #tabs { width: 1fr; height: 1; overflow: hidden; }
    ViewStrip > #meta { width: auto; height: 1; margin-left: 2; color: $atlas-muted; }
    ViewStrip.-open > #tabs, ViewStrip.-open > #meta { display: none; }
    ViewStrip.-open > SearchBox { width: 1fr; margin-left: 0; }
    """

    def __init__(
        self, *, name: str | None = None, id: str | None = None, classes: str | None = None
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._tabs: list[views.Tab] = []
        self._cells: dict[str, int] = {}
        self._digits = 2
        self._meta = Content("")
        self._results: int | None = None
        self._last: views.ViewState | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="tabs"):
            yield ViewEdge("‹", id="edge-left")
            for view, _, _ in views.VIEWS:
                yield ViewTab(view)
            yield ViewEdge("›", id="edge-right")
        yield Static(id="meta")
        yield SearchBox()

    @property
    def search(self) -> SearchInput:
        return self.query_one(SearchInput)

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

    def open_menu(self, at: Region, right: bool) -> None:
        """Show every view in a menu under `at`; the pick becomes the view."""
        app = app_of(self)
        if not self._tabs:
            return

        def picked(view: str | None) -> None:
            if view:
                app.set_state(view=view)

        app.push_screen(ViewMenu(self._tabs, app.state.view, self._digits, at, right), picked)

    def focus_tab(self, view: str) -> None:
        """Give focus to a view's tab, as the web does after a "Show all skills" link."""
        tab = self.query_one(f"#tab-{view}", ViewTab)
        tab.given = True
        tab.focus(scroll_visible=False)

    def step_view(self, step: int) -> None:
        """Show the previous or next view that can be shown; focus follows it."""
        app = app_of(self)
        ids = [t["id"] for t in self._tabs if not t["waiting"]]
        if app.state.view in ids:
            i = max(0, min(len(ids) - 1, ids.index(app.state.view) + step))
            app.set_state(view=ids[i])

    # Events

    def on_mount(self) -> None:
        self.search.cursor_blink = self.app.animation_level == "full"
        self._last = app_of(self).state.view_state()
        self._draw()

    def on_resize(self, event: events.Resize) -> None:
        self._fit()

    def on_data_changed(self, event: DataChanged) -> None:
        self._draw()

    def on_state_changed(self, event: StateChanged) -> None:
        fields = event.fields
        app = app_of(self)
        state = app.state
        last, self._last = self._last, state.view_state()
        if fields & {"harness", "view", "show_project", "show_stale"}:
            self._draw()
        if "view" in fields and (isinstance(app.focused, ViewTab) or self._left_empty_list(last)):
            self.focus_tab(state.view)
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
        return not views.sections(ins, last, app.state.collapsed)

    def _tab_list(self) -> tuple[list[views.Tab], bool]:
        app = app_of(self)
        ins, st = app.data.insights, app.state.view_state()
        if ins is None:
            ids = FIRST if st.view in FIRST else (*FIRST, st.view)
            return [_tab(v) for v in ids], True
        return views.view_tabs(ins, st, app.data.counts(st)), False

    def _draw(self) -> None:
        app = app_of(self)
        tabs, loading = self._tab_list()
        self._tabs = tabs
        n_all = next((t["count"] for t in tabs if t["id"] == "all"), None)
        bound = len(str(n_all)) if n_all is not None else 3
        self._digits = max([2, bound, *(len(str(t["count"] or 0)) for t in tabs)])
        shown = {t["id"]: t for t in tabs}
        self._cells = {}
        for tab in self.query(ViewTab):
            t = shown.get(tab.view)
            tab.display = t is not None
            if t is None:
                continue
            need = len(str(t["count"])) if t["count"] is not None else 1
            digits = max(need, bound) if tab.view in BOUND else need
            self._cells[tab.view] = tab.show(t, digits, tab.view == app.state.view, loading)
        ins = app.data.insights
        notes = views.header_meta(ins, app.state.view_state().harness) if ins else []
        parts: list[str | tuple[str, str]] = []
        for note in notes:
            parts += [(" · ", "$atlas-faint"), note] if parts else [note]
        self._meta = Content.assemble(*parts)
        self.query_one("#meta", Static).update(self._meta)
        self._fit()

    def _fit(self) -> None:
        """Lay out the row for its width: a window of tabs, the notes if they fit, the search."""
        width = self.content_size.width
        if not width:
            return
        app = app_of(self)
        box = self.query_one(SearchBox)
        query = self.search.value
        ids = [t["id"] for t in self._tabs if t["id"] in self._cells]
        cells = [self._cells[v] for v in ids]
        natural = sum(cells)
        search_w = SEARCH_WIDE if app.size.width >= WIDE else SEARCH
        compact = app.size.width < COMPACT_BELOW or natural + SPACE + search_w > width
        is_open = compact and (self.has_class("-open") or self.search.has_focus)
        self.set_class(is_open, "-open")
        box.set_class(compact and not is_open, "-folded")
        box.set_class(bool(query), "-filled")
        if compact and not is_open:
            cut = query if cell_len(query) <= CHIP else query[: CHIP - 1] + "…"
            self.query_one("#search-chip", Static).update(Content(cut))
            search_w = EDGE + (cell_len(cut) + EDGE if query else 0)
        else:
            box.styles.width = None if is_open else search_w
            room = (width if is_open else search_w) - EDGE - 1
            self.search.placeholder = fit_placeholder(room)
        if is_open:
            return
        room = width - search_w - SPACE
        meta = self.query_one("#meta", Static)
        meta_w = self._meta.cell_length + SPACE
        meta.display = bool(self._meta) and natural + meta_w <= room
        if meta.display:
            room -= meta_w
        active = ids.index(app.state.view) if app.state.view in ids else 0
        i, j = (0, len(ids)) if natural <= room else window(cells, active, room)
        for k, view in enumerate(ids):
            self.query_one(f"#tab-{view}").display = i <= k < j
        self.query_one("#edge-left").display = i > 0
        self.query_one("#edge-right").display = j < len(ids)

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
        room = self.query_one(SearchBox).size.width - 2 * EDGE - 1 - len(words)
        out.update(words if room >= QUERY_ROOM else str(n))
        out.tooltip = words

    def _first_result(self) -> tuple[str | None, str | None] | None:
        """(skill path, None) or (None, available item key) for the top row the list shows."""
        app = app_of(self)
        ins = app.data.insights
        if ins is None:
            return None
        for sec in views.sections(ins, app.state.view_state(), app.state.collapsed):
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
