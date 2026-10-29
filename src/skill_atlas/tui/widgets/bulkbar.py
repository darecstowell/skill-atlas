"""The bar that takes the view strip's row while skills are marked: the count and bulk actions."""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, ClassVar

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.geometry import Size
from textual.widget import Widget

from ...core import views
from ..messages import DataChanged, LoadStarted, StateChanged
from ..screens import AtlasModal
from . import app_of

if TYPE_CHECKING:
    from ..app import AtlasApp

MARKS = {"all": "◆", "some": "◈", "none": "◇"}
MORE = "⋯ More"
FLEX_MIN = 3
# What the bar gives up, in order, as it gets narrow: disabled actions first. Delete never folds.
FOLDS = ("link", "profile", "copy", "hidden", "count", "clear", "on", "off", "update")
FILTERS = frozenset({"marked", "harness", "view", "query", "show_project", "show_stale"})


@dataclass(frozen=True)
class Action:
    """One bulk action: the count it acts on, and the reason when it cannot run."""

    id: str
    label: str
    count: int | None = None
    reason: str = ""
    tip: str = ""
    tone: str = ""
    key: str = ""

    @property
    def enabled(self) -> bool:
        return not self.reason


@dataclass(frozen=True)
class Bulk:
    """What the bar shows: the marked skills, the tri-state of the shown ones, and the actions."""

    marked: tuple[dict, ...]
    shown: tuple[str, ...]
    hidden: int
    state: str
    actions: tuple[Action, ...]

    def action(self, id: str) -> Action | None:
        return next((a for a in self.actions if a.id == id), None)


@dataclass(frozen=True)
class _Fit:
    long_count: bool = True
    long_hidden: bool = True
    folded: tuple[str, ...] = ()
    clear: bool = True

    def fold(self, step: str) -> _Fit:
        if step == "hidden":
            return replace(self, long_hidden=False)
        if step == "count":
            return replace(self, long_count=False)
        if step == "clear":
            return replace(self, clear=False)
        return replace(self, folded=(*self.folded, step))


def mark_state(app: AtlasApp) -> tuple[str, list[str]]:
    """The tri-state of the skills the filters show (all, some, none), and their paths."""
    ins = app.data.insights
    if ins is None:
        return "none", []
    shown = [s["path"] for s in views.visible_skills(ins, app.state.view_state())]
    n = sum(1 for p in shown if p in app.state.marked)
    return ("none" if n == 0 else "all" if n == len(shown) else "some"), shown


def mark_all(app: AtlasApp) -> None:
    """Mark every skill the filters show, collapsed groups too; clear them if all are marked."""
    state, shown = mark_state(app)
    marked = set(app.state.marked)
    if state == "all":
        marked.difference_update(shown)
    else:
        marked.update(shown)
    app.set_state(marked=frozenset(marked))


def clear(app: AtlasApp) -> None:
    app.set_state(marked=frozenset())


def focus_bar(app: AtlasApp) -> None:
    """Tab from the list: the bar while marks exist, else the visible panel's first control.

    Focus never scrolls with motion here; Textual's focus scroll animates.
    """
    main = app.main
    if app.state.marked:
        main.query_one(BulkBar).focus(scroll_visible=False)
        return
    panels = [w for w in main.query("#detail, #side") if w.display] if app.detail_visible else []
    stops = [w for p in panels for w in p.walk_children(Widget) if w.focusable]
    if stops:
        stops[0].focus(scroll_visible=False)
    else:
        app.screen.focus_next()


def _sentence(text: str) -> str:
    return f"{text[:1].upper()}{text[1:]}."


def _what(part: dict) -> str:
    skills, plugins = len(part["skills"]), len(part["plugins"])
    words = [views.plural(skills, "skill") if skills else "", views.plural(plugins, "plugin")]
    return " and ".join(w for w in words[: 2 if plugins else 1] if w)


def _profile(app: AtlasApp) -> tuple[int, str]:
    """How many marked skills a profile can switch, and why none can (profiles owns the rule)."""
    try:
        from ..screens import profiles
    except ModuleNotFoundError:
        return 0, "This action does not work yet."
    if not profiles.can_save(app):
        return 0, profiles.no_switch(app)
    chosen = profiles.picked(app)
    n = len(chosen["skills"]) + len(chosen["plugins"])
    return (
        n,
        "" if n else f"None of the marked skills has an on/off switch in {profiles.where(app)}.",
    )


def _preview(marked: tuple[dict, ...]) -> str:
    text = " ".join(f"/{s.get('invoke') or s['name']}" for s in marked)
    return text if len(text) <= 80 else f"{text[:80]}…"


def _actions(app: AtlasApp, ins: views.Insights, marked: list[dict]) -> tuple[Action, ...]:
    harness = app.state.harness or "all"
    plan = views.bulk_plan(ins, harness, marked)
    label = (app.data.harnesses.get(harness) or {}).get("label") or harness
    no_switch = harness != "all" and not views.switchable(ins, harness)
    note = _sentence(views.header_meta(ins, harness)[-1]) if harness == "all" or no_switch else ""
    out = []
    for key, other in (("on", "off"), ("off", "on")):
        part, rest = plan[key], plan[other]
        count = len(part["skills"]) + len(part["plugins"])
        if note:
            reason = note
        elif count:
            reason = ""
        elif rest["skills"] or rest["plugins"]:
            reason = f"The marked skills are already {key}."
        else:
            reason = f"None of the marked skills has a switch in {label}."
        tip = f"Turn {_what(part)} {key} in {label}." if count else ""
        out.append(Action(key, f"Turn {key}", count, reason, tip))

    def why(n: int, verb: str, otherwise: str) -> str:
        if n:
            return ""
        return f"{note} Pick All harnesses to {verb} these skills." if no_switch else otherwise

    checking = app.data.updates is None and "updates" in app.data.loading
    none_up = "Checking for updates…" if checking else "None of the marked skills has an update."
    up, link, dele = len(plan["update"]), len(plan["link"]), len(plan["delete"])
    picked, profile_why = _profile(app)
    out += [
        Action("update", "Update", up, why(up, "update", none_up), tone="primary"),
        Action(
            "link",
            "Link to GitHub…",
            link,
            why(link, "link", "Only skills in your skill store that have no repo can be linked."),
        ),
        Action("copy", "Copy as prompt", tip=f"Copy {_preview(tuple(marked))} to the clipboard."),
        Action("profile", "Save as profile…", picked, profile_why),
        Action(
            "delete",
            "Delete…",
            dele,
            why(dele, "delete", "Only skills in your skill store can move to the Trash."),
            tip=f"Move {views.plural(dele, 'skill')} to the Trash.",
            tone="danger",
        ),
        Action("clear", "Clear", tip="Clear the marks.", key="esc"),
    ]
    return tuple(out)


def bulk(app: AtlasApp) -> Bulk | None:
    """The bar's model, from views.bulk_plan. None until the scan arrives or with no marks."""
    ins = app.data.insights
    if ins is None or not app.state.marked:
        return None
    marked = [s for s in ins.skills if s["path"] in app.state.marked]
    state, shown = mark_state(app)
    on_screen = set(shown)
    hidden = sum(1 for s in marked if s["path"] not in on_screen)
    return Bulk(tuple(marked), tuple(shown), hidden, state, _actions(app, ins, marked))


def _say(app: AtlasApp, text: str) -> None:
    try:
        from .. import jobs
    except ModuleNotFoundError:
        app.notify(text, severity="warning")
        return
    jobs.toast(app, text, severity="warning")


def _feature(app: AtlasApp, module: str, func: str) -> Callable[..., Any] | None:
    name = f"skill_atlas.tui.{module}"
    try:
        fn = getattr(importlib.import_module(name), func, None)
    except ModuleNotFoundError as e:
        if e.name != name:
            raise
        fn = None
    if fn is None:
        _say(app, "This action does not work yet.")
    return fn


async def _call(app: AtlasApp, module: str, func: str, *args: Any, **kw: Any) -> None:
    fn = _feature(app, module, func)
    if fn is not None:
        result = fn(app, *args, **kw)
        if inspect.isawaitable(result):
            await result


async def run_action(app: AtlasApp, action: str) -> None:
    """Run one bulk action on the marks. If it cannot run, a toast says why."""
    if action == "clear":
        clear(app)
        return
    ins, b = app.data.insights, bulk(app)
    act = b.action(action) if b else None
    if ins is None or b is None or act is None:
        return
    if not act.enabled:
        _say(app, act.reason)
        return
    plan = views.bulk_plan(ins, app.state.harness or "all", list(b.marked))
    if action in ("on", "off"):
        await _call(app, "jobs", "switch_marks", action == "on")
    elif action == "update":
        await _call(app, "jobs", "update", [views.lock_name(s) for s in plan["update"]])
    elif action == "link":
        await _call(app, "screens.link", "open_link", [s["dir_name"] for s in plan["link"]])
    elif action == "copy":
        await _call(app, "jobs", "copy_prompt")
    elif action == "profile":
        await _call(app, "screens.profiles", "save_profile")
    elif action == "delete":
        await _call(app, "screens.confirm", "confirm_delete", [s["path"] for s in plan["delete"]])


async def turn_on(app: AtlasApp) -> None:
    await run_action(app, "on")


async def turn_off(app: AtlasApp) -> None:
    await run_action(app, "off")


async def update(app: AtlasApp) -> None:
    await run_action(app, "update")


async def link(app: AtlasApp) -> None:
    await run_action(app, "link")


async def copy_prompt(app: AtlasApp) -> None:
    await run_action(app, "copy")


async def save_profile(app: AtlasApp) -> None:
    await run_action(app, "profile")


async def delete(app: AtlasApp) -> None:
    await run_action(app, "delete")


def _cells(a: Action, cw: int) -> int:
    """The width of an action's button: one padding cell each side."""
    w = len(a.label) + (len(a.key) + 1 if a.key else 0)
    return w + (1 + cw if a.count is not None else 0) + 2


def _width(b: Bulk, fit: _Fit, cw: int) -> int:
    n = len(b.marked)
    count = len(f"{views.plural(n, 'skill')} selected" if fit.long_count else f"{n} selected")
    hidden = 0
    if b.hidden:
        hidden = 3 + len(
            f"{b.hidden} hidden by filters" if fit.long_hidden else f"{b.hidden} hidden"
        )
    group = [_cells(a, cw) for a in b.actions if a.id not in (*fit.folded, "delete", "clear")]
    if fit.folded:
        group.append(len(MORE) + 2)
    end = _cells(b.actions[-2], cw) + (1 + _cells(b.actions[-1], cw) if fit.clear else 0)
    return 3 + count + hidden + 2 + sum(group) + max(0, len(group) - 1) + FLEX_MIN + end


def _fit(b: Bulk, width: int, cw: int) -> _Fit:
    off = [s for s in FOLDS if (a := b.action(s)) is not None and not a.enabled]
    fit = _Fit()
    for step in (None, *off, *(s for s in FOLDS if s not in off)):
        if step:
            fit = fit.fold(step)
        if _width(b, fit, cw) <= width:
            break
    return fit


def _folded(b: Bulk, fit: _Fit) -> list[Action]:
    """The actions in the More menu, in the bar's order."""
    out = [a for a in b.actions if a.id in fit.folded]
    if not fit.clear:
        out.append(b.actions[-1])
    return out


class BulkBar(Widget, can_focus=True):
    """The marked-skill count and the bulk actions. The app shows it in place of the view strip.

    Tab reaches it from the list; left and right move between actions; enter runs one.
    """

    DEFAULT_CSS = """
    BulkBar { height: 1; padding: 0 1 0 0; background: $background; color: $atlas-text; }
    BulkBar > .bulkbar--mark { color: $atlas-accent; }
    BulkBar > .bulkbar--mark-none { color: $atlas-faint; }
    BulkBar > .bulkbar--count { color: $atlas-text; text-style: bold; }
    BulkBar > .bulkbar--muted { color: $atlas-muted; }
    BulkBar > .bulkbar--faint { color: $atlas-faint; }
    BulkBar > .bulkbar--label { color: $atlas-text; }
    BulkBar > .bulkbar--primary { color: $atlas-accent; }
    BulkBar > .bulkbar--danger { color: $atlas-danger; }
    BulkBar > .bulkbar--key { color: $atlas-accent; }
    BulkBar > .bulkbar--hover { background: $atlas-surface-2; }
    BulkBar > .bulkbar--danger-hover { background: $atlas-danger-tint; }
    BulkBar > .bulkbar--pressed { background: $atlas-surface-3; }
    BulkBar > .bulkbar--cursor { background: $atlas-selection; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "bulkbar--mark",
        "bulkbar--mark-none",
        "bulkbar--count",
        "bulkbar--muted",
        "bulkbar--faint",
        "bulkbar--label",
        "bulkbar--primary",
        "bulkbar--danger",
        "bulkbar--key",
        "bulkbar--hover",
        "bulkbar--danger-hover",
        "bulkbar--pressed",
        "bulkbar--cursor",
    }
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "move(-1)", "Previous action", show=False),
        Binding("right", "move(1)", "Next action", show=False),
        Binding("home", "edge(0)", "First action", show=False),
        Binding("end", "edge(-1)", "Last action", show=False),
        Binding("enter,space", "press", "Run the action", show=False),
    ]
    FOCUS_ON_CLICK = False
    ALLOW_SELECT = False

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.model: Bulk | None = None
        self._count = 0
        self._segs: list[tuple[int, int, str]] = []
        self._nav: list[str] = []
        self._cursor: str | None = None
        self._hover: str | None = None
        self._pressed: str | None = None

    # Model

    def on_mount(self) -> None:
        self._sync()

    def on_state_changed(self, event: StateChanged) -> None:
        if event.fields & FILTERS:
            self._sync()

    def on_data_changed(self, event: DataChanged) -> None:
        self._sync()

    def on_load_started(self, event: LoadStarted) -> None:
        if event.part == "updates":
            self._sync()

    def on_resize(self, event: events.Resize) -> None:
        self._layout()

    def _sync(self) -> None:
        app = app_of(self)
        before, self._count = self._count, len(app.state.marked)
        self.model = bulk(app)
        if before and not self._count:
            self._leave()
        self._layout()

    def _leave(self) -> None:
        self._cursor = self._hover = self._pressed = None
        self.tooltip = None
        if self.has_focus:
            app_of(self).main.query_one("#list").focus()

    # Layout

    @property
    def fit(self) -> _Fit:
        b = self.model
        if b is None:
            return _Fit()
        return _fit(b, self.size.width, len(str(len(b.marked))))

    def folded(self) -> list[Action]:
        """The actions that live in the More menu at this width."""
        return _folded(self.model, self.fit) if self.model else []

    def _layout(self) -> None:
        b, fit = self.model, self.fit
        nav: list[str] = []
        if b is not None:
            for a in b.actions:
                if a.id == "delete" and fit.folded:
                    nav.append("more")
                visible = a.id not in fit.folded and (a.id != "clear" or fit.clear)
                if visible and a.enabled:
                    nav.append(a.id)
        self._nav = nav
        if self._cursor not in nav:
            self._cursor = nav[0] if nav and self.has_focus else None
        self._sync_tip()
        self.refresh()

    # Drawing

    def render(self) -> Text:
        b = self.model
        text = Text(no_wrap=True, overflow="crop", end="")
        self._segs = []
        if b is None:
            return text
        style = self.get_component_rich_style
        width, cw, fit = self.size.width, len(str(len(b.marked))), self.fit

        def button(id: str, parts: list[tuple[str, Style]], enabled: bool, danger: bool) -> None:
            start = len(text)
            focused = enabled and id == self._cursor and self.has_focus
            text.append("▌" if focused and self.app.no_color else " ")
            for chunk, look in parts:
                text.append(chunk, look)
            text.append(" ")
            self._segs.append((start, len(text), id if enabled else f"-{id}"))
            back = self._back(id, danger) if enabled else None
            if back is not None:
                text.stylize(back, start, len(text))

        def action(a: Action) -> None:
            if a.enabled:
                look = style(f"bulkbar--{a.tone or 'label'}", partial=True)
            else:
                look = style("bulkbar--faint", partial=True)
            parts: list[tuple[str, Style]] = []
            if a.key:
                parts += [(a.key, style("bulkbar--key", partial=True)), (" ", Style())]
            parts.append((a.label, look))
            if a.count is not None:
                number = str(a.count) if a.enabled else ""
                parts.append((f" {number:>{cw}}", style("bulkbar--muted", partial=True)))
            button(a.id, parts, a.enabled, a.tone == "danger")

        n = len(b.marked)
        glyph = MARKS[b.state] if b.shown else " "
        tone = "bulkbar--mark-none" if b.state == "none" else "bulkbar--mark"
        button("mark", [(glyph, style(tone, partial=True))], bool(b.shown), False)
        count = f"{views.plural(n, 'skill')} selected" if fit.long_count else f"{n} selected"
        text.append(count, style("bulkbar--count", partial=True))
        if b.hidden:
            words = f"{b.hidden} hidden by filters" if fit.long_hidden else f"{b.hidden} hidden"
            text.append(" · ", style("bulkbar--faint", partial=True))
            text.append(words, style("bulkbar--muted", partial=True))
        text.append(" ")
        for a in b.actions:
            if a.id in ("delete", "clear") or a.id in fit.folded:
                continue
            text.append(" ")
            action(a)
        if fit.folded:
            text.append(" ")
            button("more", [(MORE, style("bulkbar--label", partial=True))], True, False)
        end = _cells(b.actions[-2], cw) + (1 + _cells(b.actions[-1], cw) if fit.clear else 0)
        text.append(" " * max(FLEX_MIN, width - len(text) - end))
        action(b.actions[-2])
        if fit.clear:
            text.append(" ")
            action(b.actions[-1])
        return text

    def _back(self, id: str, danger: bool) -> Style | None:
        style = self.get_component_rich_style
        if id == self._pressed:
            return style("bulkbar--pressed", partial=True)
        if id == self._cursor and self.has_focus:
            return style("bulkbar--cursor", partial=True)
        if id == self._hover:
            return style("bulkbar--danger-hover" if danger else "bulkbar--hover", partial=True)
        return None

    # Mouse

    def _at(self, event: events.MouseEvent) -> str | None:
        """The target under the pointer. A disabled action's id starts with "-"."""
        offset = event.get_content_offset(self)
        if offset is None:
            return None
        return next((id for a, z, id in self._segs if a <= offset.x < z), None)

    def _tip(self, id: str | None) -> str | None:
        b = self.model
        if b is None or id is None:
            return None
        if id == "mark":
            n = len(b.shown)
            return f"Clear all {n}" if b.state == "all" else f"Select all {n} shown"
        if id == "more":
            return "More actions"
        a = b.action(id.lstrip("-"))
        return (a.reason or a.tip or None) if a else None

    def _sync_tip(self) -> None:
        self.tooltip = self._tip(self._hover)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        id = self._at(event)
        if id != self._hover:
            self._hover = id
            self._sync_tip()
            self.refresh()

    def on_leave(self, event: events.Leave) -> None:
        self._hover = self._pressed = None
        self.tooltip = None
        self.refresh()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        id = self._at(event)
        self._pressed = id if id and not id.startswith("-") else None
        self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._pressed is not None:
            self._pressed = None
            self.refresh()

    def on_click(self, event: events.Click) -> None:
        id = self._at(event)
        if id and not id.startswith("-"):
            event.stop()
            self._activate(id)

    # Keys

    def on_focus(self, event: events.Focus) -> None:
        if self._cursor not in self._nav:
            self._cursor = self._nav[0] if self._nav else None
        self.refresh()

    def on_blur(self, event: events.Blur) -> None:
        self.refresh()

    def action_move(self, step: int) -> None:
        if not self._nav:
            return
        i = self._nav.index(self._cursor) if self._cursor in self._nav else -step
        self._cursor = self._nav[max(0, min(len(self._nav) - 1, i + step))]
        self.refresh()

    def action_edge(self, index: int) -> None:
        if self._nav:
            self._cursor = self._nav[index]
            self.refresh()

    def action_press(self) -> None:
        if self._cursor is not None:
            self._activate(self._cursor)

    # Running

    def _activate(self, id: str) -> None:
        app = app_of(self)
        if id == "mark":
            mark_all(app)
        elif id == "more":
            self.open_more()
        else:
            self.run_worker(run_action(app, id), group="bulkbar")

    def open_more(self) -> None:
        """Show the actions that do not fit, in a menu under the More button."""
        items = self.folded()
        seg = next((s for s in self._segs if s[2] == "more"), None)
        if not items or seg is None:
            return
        x = self.content_region.x + seg[0]
        y = self.content_region.y + 1

        def picked(id: str | None) -> None:
            if id:
                self._activate(id)

        cw = len(str(len(self.model.marked))) if self.model else 1
        self.app.push_screen(MoreMenu(items, x, y, cw), picked)


class MoreList(Widget, can_focus=True):
    """The rows of the More menu. Up and down move; enter or a click runs a row."""

    DEFAULT_CSS = """
    MoreList {
        width: auto;
        height: auto;
        background: $atlas-surface-1;
        border: round $atlas-border-strong;
    }
    MoreList > .morelist--label { color: $atlas-text; }
    MoreList > .morelist--primary { color: $atlas-accent; }
    MoreList > .morelist--muted { color: $atlas-muted; }
    MoreList > .morelist--faint { color: $atlas-faint; }
    MoreList > .morelist--key { color: $atlas-accent; }
    MoreList > .morelist--bar { color: $atlas-text; }
    MoreList > .morelist--hover { background: $atlas-surface-2; }
    MoreList > .morelist--pressed { background: $atlas-surface-3; }
    MoreList > .morelist--cursor { background: $atlas-selection; }
    """
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "morelist--label",
        "morelist--primary",
        "morelist--muted",
        "morelist--faint",
        "morelist--key",
        "morelist--bar",
        "morelist--hover",
        "morelist--pressed",
        "morelist--cursor",
    }
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up,k", "move(-1)", "Previous", show=False),
        Binding("down,j", "move(1)", "Next", show=False),
        Binding("home", "edge(0)", "First", show=False),
        Binding("end", "edge(-1)", "Last", show=False),
        Binding("enter,space", "press", "Run", show=False),
    ]
    ALLOW_SELECT = False

    def __init__(self, items: list[Action], cw: int) -> None:
        super().__init__()
        self.items = items
        self.cw = cw
        live = [i for i, a in enumerate(items) if a.enabled]
        self._live = live
        self._cursor: int | None = live[0] if live else None
        self._hover: int | None = None
        self._pressed: int | None = None

    def _right(self, a: Action) -> str:
        if a.key:
            return a.key
        return str(a.count) if a.count is not None and a.enabled else ""

    def _label_width(self) -> int:
        return max(len(a.label) for a in self.items)

    def _right_width(self) -> int:
        return max(self.cw, *(len(self._right(a)) for a in self.items))

    def get_content_width(self, container: Size, viewport: Size) -> int:
        return 2 + self._label_width() + 3 + self._right_width() + 1

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return len(self.items)

    def render(self) -> Text:
        style = self.get_component_rich_style
        lw, rw = self._label_width(), self._right_width()
        lines = []
        for i, a in enumerate(self.items):
            tone = f"morelist--{a.tone if a.tone == 'primary' else 'label'}"
            look = style(tone if a.enabled else "morelist--faint", partial=True)
            right = style("morelist--key" if a.key else "morelist--muted", partial=True)
            focused = i == self._cursor and self.has_focus
            line = Text(no_wrap=True, end="")
            line.append("▌" if focused else " ", style("morelist--bar", partial=True))
            line.append(" ").append(a.label.ljust(lw), look)
            line.append("   ").append(self._right(a).rjust(rw), right).append(" ")
            if i == self._pressed:
                line.stylize(style("morelist--pressed", partial=True))
            elif focused:
                line.stylize(style("morelist--cursor", partial=True))
            elif i == self._hover and a.enabled:
                line.stylize(style("morelist--hover", partial=True))
            lines.append(line)
        return Text("\n", end="").join(lines)

    def _row_at(self, event: events.MouseEvent) -> int | None:
        offset = event.get_content_offset(self)
        if offset is None or not 0 <= offset.y < len(self.items):
            return None
        return offset.y

    def on_mouse_move(self, event: events.MouseMove) -> None:
        row = self._row_at(event)
        if row != self._hover:
            self._hover = row
            a = self.items[row] if row is not None else None
            self.tooltip = (a.reason or a.tip or None) if a else None
            self.refresh()

    def on_leave(self, event: events.Leave) -> None:
        self._hover = self._pressed = None
        self.tooltip = None
        self.refresh()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        row = self._row_at(event)
        self._pressed = row if row in self._live else None
        self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self._pressed = None
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        row = self._row_at(event)
        if row in self._live:
            self.screen.dismiss(self.items[row].id)

    def action_move(self, step: int) -> None:
        if not self._live:
            return
        i = self._live.index(self._cursor) if self._cursor in self._live else -step
        self._cursor = self._live[max(0, min(len(self._live) - 1, i + step))]
        self.refresh()

    def action_edge(self, index: int) -> None:
        if self._live:
            self._cursor = self._live[index]
            self.refresh()

    def action_press(self) -> None:
        if self._cursor is not None:
            self.screen.dismiss(self.items[self._cursor].id)


class MoreMenu(AtlasModal[str | None]):
    """The bulk actions that do not fit in the bar, under its More button."""

    DEFAULT_CSS = """
    MoreMenu { align: left top; background: transparent; }
    """

    def __init__(self, items: list[Action], x: int, y: int, cw: int) -> None:
        super().__init__()
        self.items = items
        self.at = (x, y)
        self.cw = cw

    def compose(self) -> ComposeResult:
        yield MoreList(self.items, self.cw)

    def on_mount(self) -> None:
        menu = self.query_one(MoreList)
        width = menu.get_content_width(self.size, self.size) + 2
        x, y = self.at
        menu.styles.offset = (max(0, min(x, self.size.width - width)), y)
        menu.focus()
