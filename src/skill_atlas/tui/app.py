"""The Textual app: layout, UI state, background loads, and the keys that act on the whole app."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeVar, cast

from rich.console import RenderableType
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import BindingType
from textual.command import Hits, Provider
from textual.containers import Horizontal, Vertical
from textual.css.scalar import ScalarOffset
from textual.message import Message
from textual.notifications import SeverityLevel
from textual.screen import Screen
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from ..core import views
from . import keys, state, theme
from .messages import DataChanged, ItemSelected, LoadStarted, SkillSelected, StateChanged
from .state import FIELDS, PARTS, SAVED, AtlasData
from .widgets.bulkbar import BulkBar
from .widgets.detail import DetailPanel
from .widgets.header import AtlasHeader
from .widgets.keybar import KeyBar
from .widgets.progress import JobBar
from .widgets.sidepanel import SidePanel
from .widgets.skill_list import SkillList
from .widgets.viewstrip import ViewStrip

if TYPE_CHECKING:
    from textual.pilot import Pilot

    from ..core.api import AtlasAPI

T = TypeVar("T")
Level = Literal["none", "basic", "full"]
LEVELS: tuple[Level, ...] = ("none", "basic", "full")
MIN_SIZE = (60, 16)
NARROW = 100
PANEL_MIN, LIST_MIN = 30, 40
USAGE_POLL = 1.2
SAVE_DELAY = 0.5
FAILED = {
    "scan": "Could not scan the skills",
    "usage": "Could not read the usage",
    "updates": "Could not check for updates",
}
MOTION_LEVELS: dict[str, Level] = {"full": "full", "reduced": "basic", "off": "none"}
LAYOUT = frozenset({"detail_open", "marked", "selected", "selected_key", "panel_width"})
# While a screen covers the main one, these keys do nothing, so that screen can use them.
MAIN_ONLY = keys.actions("app") - {"quit", "help"}
# Actions that other modules implement: action -> (module in skill_atlas.tui, function(app)).
# Similar and Diverged have no digit; Review (security) matters more.
DIGIT_VIEWS = ("all", "on", "off", "updates", "issues", "new", "unused", "costly", "review")
FEATURES: dict[str, tuple[str, str]] = {
    "toggle_skill": ("jobs", "toggle"),
    "update_skill": ("jobs", "update"),
    "install_skill": ("jobs", "install"),
    "undo": ("jobs", "undo"),
    "read_skill": ("screens.reader", "open_reader"),
    "skill_actions": ("commands", "open_actions"),
    "help": ("screens.help", "open_help"),
}


def _cells(x: int) -> Any:
    """An x offset that styles.animate accepts; its type hint leaves ScalarOffset out."""
    return ScalarOffset.from_offset((x, 0))


class _NoCommands(Provider):
    async def search(self, query: str) -> Hits:
        return
        yield


def _atlas_commands() -> type[Provider]:
    """commands.AtlasCommands, once that module exists."""
    try:
        module = importlib.import_module(f"{__package__}.commands")
    except ModuleNotFoundError as e:
        if e.name != f"{__package__}.commands":
            raise
        return _NoCommands
    return getattr(module, "AtlasCommands", _NoCommands)


_HANDLES: dict[tuple[type, type], bool] = {}


def _handles(node_type: type, message: type[Message]) -> bool:
    """True when the class has an on_* method or an @on handler for the message."""
    key = (node_type, message)
    if key not in _HANDLES:
        _HANDLES[key] = any(
            message.handler_name in vars(base)
            or message in (vars(base).get("_decorated_handlers") or {})
            for base in node_type.__mro__
        )
    return _HANDLES[key]


class ErrorBand(Static):
    """One line per failed load. A click loads the failed parts again."""

    DEFAULT_CSS = """
    ErrorBand { display: none; height: auto; padding: 0 1; }
    ErrorBand { background: $atlas-danger-tint; color: $atlas-danger; }
    """

    def show(self, errors: dict[str, str], *, scanned: bool = True) -> None:
        """Without a scan, the list's empty state shows the scan error and its fix instead."""
        shown = {p: m for p, m in errors.items() if scanned or p != "scan"}
        self.display = bool(shown)
        lines = (
            f"✗ {FAILED[p]}: {msg.rstrip('.')}. Click this line to try again."
            for p, msg in shown.items()
        )
        self.update(Text("\n".join(lines)))

    def on_click(self, event: events.Click) -> None:
        app = cast("AtlasApp", self.app)
        app.reload(list(app.data.errors), refresh=True)


class Divider(Widget):
    """The handle between the list and the panel. Drag it to resize; double-click resets."""

    ALLOW_SELECT = False
    DEFAULT_CSS = """
    Divider { width: 1; height: 1fr; background: $background; color: $background; }
    Divider:hover { color: $atlas-border-strong; }
    Divider.-drag { color: $atlas-accent; }
    """

    def on_mount(self) -> None:
        self.tooltip = "Drag to resize the panel. Double-click to reset it."

    def render(self) -> RenderableType:
        return "\n".join("│" * self.size.height)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        event.stop()
        self.capture_mouse()
        self.add_class("-drag")

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self.has_class("-drag"):
            cast("AtlasApp", self.app).drag_panel(event.screen_x)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self.has_class("-drag"):
            self.release_mouse()
            self.remove_class("-drag")
            cast("AtlasApp", self.app).drag_panel(event.screen_x, done=True)

    def on_click(self, event: events.Click) -> None:
        if event.chain == 2:
            cast("AtlasApp", self.app).set_state(panel_width=0)


class AtlasApp(App[int]):
    """Skill Atlas in the terminal. Widgets read `state` and `data`, and call `atlas` in workers."""

    TITLE = "Skill Atlas"
    BINDINGS: ClassVar[list[BindingType]] = keys.bindings("app")
    COMMANDS = App.COMMANDS | {_atlas_commands}
    CSS = """
    #_default { background: $background; }
    Screen > .screen--selection { background: $atlas-accent-tint; color: $atlas-text; }
    #rule { margin: 0; color: $atlas-border; background: $background; }
    #main { height: 1fr; layers: default overlay; }
    #detail-pane { background: $atlas-surface-1; }
    #detail-pane > #detail { display: none; }
    #detail-pane.-narrow { layer: overlay; dock: right; }
    #list.-peek { tint: $background 40%; }
    #bulkbar { display: none; }
    #bulkbar.-on { display: block; }
    #viewstrip.-off { display: none; }
    #too-small { display: none; width: 1fr; height: 1fr; content-align: center middle; }
    .-tiny #_default > * { display: none; }
    .-tiny #_default > #too-small { display: block; }
    """

    def __init__(self, atlas: AtlasAPI, *, prefs: Path | None = None) -> None:
        super().__init__()
        self.atlas = atlas
        self.prefs_path = prefs or state.prefs_path()
        self.state = state.load(self.prefs_path)
        self.data = AtlasData(loading={"scan"}, clock=atlas.now)
        self._ceiling: Level = self.animation_level
        if not os.environ.get("TEXTUAL_ANIMATIONS") and os.environ.get("SSH_TTY"):
            self._ceiling = "basic"
        self._laid_out = False
        self._peek = False
        self._width = 0
        self._save_timer: Timer | None = None
        self._window_title = ""

    def compose(self) -> ComposeResult:
        yield AtlasHeader(id="header")
        yield ViewStrip(id="viewstrip")
        yield BulkBar(id="bulkbar")
        yield JobBar(id="rule")
        yield ErrorBand(id="error-band")
        with Horizontal(id="main"):
            yield SkillList(id="list")
            yield Divider(id="divider")
            with Vertical(id="detail-pane"):
                yield DetailPanel(id="detail")
                yield SidePanel(id="side")
        yield KeyBar(id="keybar")
        yield Static(id="too-small")

    def on_mount(self) -> None:
        theme.register(self)
        self._laid_out = True
        self._apply(FIELDS)
        self.main.query_one(SkillList).focus()
        self.reload()
        if os.environ.get("SSH_TTY") and self.console.color_system in theme.LIMITED:
            from . import limited_hint

            self.call_after_refresh(self.notify, limited_hint())  # stderr hides behind the app

    def on_resize(self, event: events.Resize) -> None:
        self._layout()

    def on_unmount(self) -> None:
        if self._save_timer is not None:
            self._save_timer.stop()
            self._save()

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return theme.colors(self)

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        # The palette and mode settings pick the theme, so Textual's theme list stays out.
        yield from (c for c in super().get_system_commands(screen) if c.title != "Theme")
        yield SystemCommand(
            "Reload",
            "Scan the skills and check everything again",
            lambda: self.reload(refresh=True),
        )

    def action_command_palette(self) -> None:
        from . import commands

        commands.open_palette(self)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not (action in MAIN_ONLY and len(self.screen_stack) > 1)

    @property
    def main(self) -> Screen:
        """The screen that holds the layout, even while another screen covers it."""
        return self.screen_stack[0]

    # Layout

    @property
    def narrow(self) -> bool:
        """Below 100 columns the panel is a drawer over the list."""
        return self.size.width < NARROW

    @property
    def detail_visible(self) -> bool:
        """The panel shows: a saved choice when docked, a drawer the user opened when narrow."""
        return self._peek if self.narrow else self.state.detail_open

    def panel_width(self) -> int:
        cols = self.size.width
        if self.narrow:
            return min(cols - 8, 64)
        if self.state.panel_width:
            return max(PANEL_MIN, min(self.state.panel_width, cols - LIST_MIN - 1))
        if cols < 120:
            return 40
        return round(0.34 * cols) if cols < 160 else min(round(0.34 * cols), 64)

    def show_detail(self, show: bool = True) -> None:
        """Show or hide the panel: a drawer when narrow, else a saved choice."""
        if not self.narrow:
            self.set_state(detail_open=show)
            return
        if self._peek == show:
            return
        self._peek = show
        self._slide(show)
        self._broadcast(lambda: StateChanged(frozenset({"detail_open"})))
        if not show:
            self.main.query_one(SkillList).focus()

    def drag_panel(self, screen_x: int, done: bool = False) -> None:
        """Resize the docked panel so its left edge follows the pointer."""
        cols = self.size.width
        width = max(PANEL_MIN, min(cols - screen_x - 1, cols - LIST_MIN - 1))
        self.main.query_one("#detail-pane").styles.width = width
        self._width = width
        if done:
            self.set_state(panel_width=width)

    def _slide(self, show: bool) -> None:
        pane = self.main.query_one("#detail-pane")
        if self.animation_level != "full":
            pane.styles.clear_rule("offset")
            self._layout()
            return
        if show:
            self._layout()
            if not self.animator.is_being_animated(pane.styles, "offset"):
                pane.styles.offset = (self._width, 0)  # else start from where the close left it
            pane.styles.animate("offset", _cells(0), duration=0.2, easing="out_quart")
        else:
            pane.styles.animate(
                "offset",
                _cells(self._width),
                duration=0.15,
                easing="in_cubic",
                on_complete=self._layout,
            )

    def _layout(self) -> None:
        if not self._laid_out:
            return
        cols, rows = self.size
        pane = self.main.query_one("#detail-pane")
        if not self.narrow:
            self._peek = False
            pane.styles.clear_rule("offset")
        tiny = cols < MIN_SIZE[0] or rows < MIN_SIZE[1]
        self.set_class(tiny, "-tiny")
        if tiny:
            need = f"{MIN_SIZE[0]} × {MIN_SIZE[1]}"
            self.main.query_one("#too-small", Static).update(
                f"The window is {cols} × {rows}. Skill Atlas needs at least {need}."
            )
        # Classes go on the smallest node: a class on the App restyles every widget.
        main = self.main
        pane.set_class(self.narrow, "-narrow")
        main.query_one("#list").set_class(self._peek, "-peek")
        pane.display = self.detail_visible
        main.query_one("#divider").display = self.detail_visible and not self.narrow
        marking = bool(self.state.marked)
        main.query_one("#bulkbar").set_class(marking, "-on")
        main.query_one("#viewstrip").set_class(marking, "-off")
        has = self.state.selected is not None or self.state.selected_key is not None
        for panel in main.query("#detail, #side"):
            panel.display = has == (panel.id == "detail")
        width = self.panel_width()
        if width != self._width:
            self._width = width
            pane.styles.width = width

    # State

    def set_state(self, **changes: Any) -> frozenset[str]:
        """Change UIState fields, save the display preferences, and send StateChanged."""
        for name, value in changes.items():
            if name not in FIELDS or not state.valid(name, value):
                raise ValueError(f"bad UI state: {name}={value!r}")
        changed = frozenset(n for n, v in changes.items() if getattr(self.state, n) != v)
        for name in changed:
            value = changes[name]
            setattr(self.state, name, frozenset(value) if name == "marked" else value)
        if changed:
            self._apply(changed)
            if changed & set(SAVED):
                self._save_soon()
            self._broadcast(lambda: StateChanged(changed))
        return changed

    def _apply(self, changed: Iterable[str]) -> None:
        names = set(changed)
        if names & {"palette", "mode"}:
            self.theme = theme.name(self.state.palette, self.state.mode)
        if "motion" in names:
            want = MOTION_LEVELS[self.state.motion]
            self.animation_level = min(want, self._ceiling, key=LEVELS.index)
        if "harness" in names:
            self._set_title()
        if names & LAYOUT:
            self._layout()

    def _set_title(self) -> None:
        ins = self.data.insights
        title = views.window_title(ins, self.state.harness) if ins else self.TITLE
        if title == self._window_title:
            return
        self._window_title = self.title = title
        if self._driver is not None:
            self._driver.write(f"\x1b]2;{title}\x07")  # OSC 2; Textual has no title API

    def _save_soon(self) -> None:
        if self._save_timer is None:
            self._save_timer = self.set_timer(SAVE_DELAY, self._save)
        else:
            self._save_timer.reset()

    def _save(self) -> None:
        self._save_timer = None
        try:
            state.save(self.state, self.prefs_path)
        except OSError as e:
            self.notify(f"Could not save the display settings: {e}", severity="warning")

    def broadcast(self, make: Callable[[], Message]) -> None:
        """Deliver a fresh message from make() to every widget that handles its type."""
        self._broadcast(make)

    def _broadcast(self, make: Callable[[], Message]) -> None:
        kind = type(make())
        for screen in self.screen_stack:
            for node in screen.walk_children(with_self=True):
                if _handles(type(node), kind):
                    node.post_message(make())

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None:
        """Every toast goes through jobs.toast, so all share one look and one stack."""
        from . import jobs

        jobs.toast(self, f"{title}: {message}" if title else message, severity=severity)

    def current(self) -> tuple[str | None, str | None]:
        """(skill path, item key) that keys act on: the selection, else the list's cursor row."""
        if self.state.selected or self.state.selected_key:
            return self.state.selected, self.state.selected_key
        rows = self.main.query(SkillList)
        lst = rows.first() if rows else None
        if lst is None or not 0 <= lst.cursor < len(lst.rows):
            return None, None
        row = lst.rows[lst.cursor]
        return (row.key, None) if row.kind == "skill" else (None, row.key)

    def on_skill_list_results_changed(self, event: SkillList.ResultsChanged) -> None:
        """The list counts what it shows; the view strip's search echo shows that number."""
        n = event.n

        def copy() -> SkillList.ResultsChanged:
            message = SkillList.ResultsChanged(n)
            message.stop()  # handlers still run; a stopped copy does not bubble back here
            return message

        self._broadcast(copy)

    def on_skill_selected(self, event: SkillSelected) -> None:
        self.set_state(selected=event.path, selected_key=None)
        if event.open:
            self.show_detail()

    def on_item_selected(self, event: ItemSelected) -> None:
        self.set_state(selected=None, selected_key=event.key)
        if event.open:
            self.show_detail()

    # Data

    def reload(self, parts: Iterable[str] = PARTS, *, refresh: bool = False) -> None:
        """Load parts in the background: the scan first, then the rest at once.

        refresh=True skips the cache of the update check.
        """
        want = set(parts)
        if "scan" in want:
            self._load_scan(frozenset(want - {"scan"}), refresh)
            return
        if "usage" in want:
            self._load_usage()
        if "updates" in want:
            self._load_updates(refresh)

    async def fetch(self, fn: Callable[..., T], *args: Any) -> T:
        """Run a blocking read on a daemon thread and await it. Quit does not wait for it."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()

        def settle(value: Any, error: BaseException | None) -> None:
            if future.done():
                return
            if error is None:
                future.set_result(value)
            else:
                future.set_exception(error)

        def run() -> None:
            try:
                value, error = fn(*args), None
            except Exception as e:
                value, error = None, e
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(settle, value, error)

        threading.Thread(target=run, name="atlas-read", daemon=True).start()
        return await future

    @work(exclusive=True, group="scan")
    async def _load_scan(self, then: frozenset[str], refresh: bool) -> None:
        await self._load("scan", self.atlas.data)
        self.reload(then, refresh=refresh)

    @work(exclusive=True, group="usage")
    async def _load_usage(self) -> None:
        ok = await self._load("usage", self.atlas.usage)
        if ok and (self.data.usage or {}).get("status") == "indexing":
            self.set_timer(USAGE_POLL, lambda: self.reload(["usage"]))

    @work(exclusive=True, group="updates")
    async def _load_updates(self, refresh: bool) -> None:
        await self._load("updates", lambda: self.atlas.updates(refresh=refresh))

    async def _load(self, part: str, fn: Callable[[], dict]) -> bool:
        self.data.loading.add(part)
        self._broadcast(lambda: LoadStarted(part))

        def read() -> tuple[dict, state.Basis, views.Insights | None]:
            value = fn()
            basis = self.data.basis(part, value)
            return value, basis, self.data.build(basis)

        try:
            result, basis, ins = await self.fetch(read)
        except Exception as e:
            self.data.errors[part] = str(e) or type(e).__name__
            ok = False
        else:
            self.data.put(part, result, basis, ins)
            self.data.errors.pop(part, None)
            if part == "scan":
                self._after_scan()
                self._load_missing()
            ok = True
        self.data.loading.discard(part)
        self._set_title()
        self.main.query_one(ErrorBand).show(self.data.errors, scanned=self.data.scan is not None)
        self._broadcast(lambda: DataChanged(frozenset({part})))
        return ok

    @work(exclusive=True, group="missing")
    async def _load_missing(self) -> None:
        try:
            plan = await self.fetch(self.atlas.restore_plan)
        except Exception:
            return  # the restore item is a hint; the scan already reports real errors
        self.data.missing = len(plan.get("install") or [])
        self.data.put("scan", self.data.scan or {})
        self._broadcast(lambda: DataChanged(frozenset({"scan"})))

    def _after_scan(self) -> None:
        ins = self.data.insights
        if ins is None:
            return
        changes: dict[str, Any] = {}
        if self.state.harness not in views.harness_choices(ins):
            changes["harness"] = views.default_harness(ins)
        if self.state.selected and self.state.selected not in ins.by_path:
            changes["selected"] = None
        kept = frozenset(p for p in self.state.marked if p in ins.by_path)
        if kept != self.state.marked:
            changes["marked"] = kept
        self.set_state(**changes)

    # Actions

    async def run_key(self, key: keys.Key) -> None:
        """Run a key's action where it is bound, as a click on its hint does."""
        target = self.main.query_one(SkillList) if key.where == "list" else self
        await self.run_action(key.action, target)

    def action_search(self) -> None:
        self.main.query_one(ViewStrip).focus_search()

    def action_view(self, n: int) -> None:
        # Fixed numbers: a view keeps its key when other views hide.
        if 1 <= n <= len(DIGIT_VIEWS):
            self.set_state(view=DIGIT_VIEWS[n - 1])

    def action_harness(self, step: int) -> None:
        ins = self.data.insights
        ids = views.harness_choices(ins) if ins else []
        if ids:
            i = ids.index(self.state.harness) if self.state.harness in ids else 0
            self.set_state(harness=ids[(i + step) % len(ids)])

    def action_compact(self) -> None:
        self.set_state(compact=not self.state.compact)

    def action_toggle_detail(self) -> None:
        self.show_detail(not self.detail_visible)

    def action_escape(self) -> None:
        from . import jobs

        if jobs.escape(self):
            return
        if self.state.query:
            self.set_state(query="")
        elif self.narrow and self._peek:
            self.show_detail(False)
        elif self.state.marked:
            self.set_state(marked=frozenset())
        elif self.state.view != "all" and self.main.query_one(SkillList).has_focus:
            self.set_state(view="all")
        else:
            self.main.query_one(SkillList).focus()

    async def action_toggle_skill(self) -> None:
        await self._feature("toggle_skill")

    async def action_update_skill(self) -> None:
        await self._feature("update_skill")

    async def action_install_skill(self) -> None:
        await self._feature("install_skill")

    async def action_read_skill(self) -> None:
        await self._feature("read_skill")

    async def action_skill_actions(self) -> None:
        await self._feature("skill_actions")

    async def action_undo(self) -> None:
        await self._feature("undo")

    async def action_help(self) -> None:
        await self._feature("help")

    async def action_run(self, target: str) -> None:
        """Run `module:function` from this package, for keys.py entries such as run('jobs:undo')."""
        module, _, func = target.partition(":")
        await self._call(module, func)

    async def _feature(self, action: str) -> None:
        await self._call(*FEATURES[action])

    async def _call(self, module: str, func: str) -> None:
        name = f"{__package__}.{module}"
        try:
            fn = getattr(importlib.import_module(name), func, None)
        except ModuleNotFoundError as e:
            if e.name != name:
                raise
            fn = None
        if fn is None:
            self.notify("This key does not work yet.", severity="warning")
            return
        result = fn(self)
        if inspect.isawaitable(result):
            await result


async def settle(pilot: Pilot[Any], timeout: float = 10) -> None:
    """Wait until the loads and their follow-ups finish. For tests and screenshots."""
    app = pilot.app
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await pilot.pause()
        if all(w.is_finished for w in app.workers):
            break
        await asyncio.sleep(0.02)
    await pilot.pause()
    await pilot.wait_for_scheduled_animations()


def run(demo: bool = False) -> int:
    """Start the TUI on this machine's skills, or on sample data. Returns the exit code."""
    atlas: AtlasAPI
    if demo:
        from ..core.demo import DemoAtlas

        atlas = DemoAtlas()
    else:
        from ..core.atlas import default

        atlas = default()
    app = AtlasApp(atlas)
    tty = sys.stdout.isatty()
    if tty:
        sys.stdout.write("\x1b[22;2t")  # push the terminal's title, so exit restores it
    try:
        app.run()
    finally:
        if tty:
            sys.stdout.write("\x1b[23;2t")
            sys.stdout.flush()
    return app.return_code or 0
