"""The detail panel: the selected skill, group, or available skill, as on the web page."""

from __future__ import annotations

import importlib
import inspect
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from textual import events
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.timer import Timer
from textual.widget import Widget

from ...core import views
from .. import theme
from ..messages import DataChanged, ItemSelected, JobChanged, SkillSelected, StateChanged
from . import app_of
from .detail_build import Ctx, Load, avail_blocks, group_blocks, skill_blocks
from .detail_parts import Act, Acted, BoxEl, DetailHints, reconcile, wid

if TYPE_CHECKING:
    from ..app import AtlasApp

THROTTLE = 0.05  # design §12: at most one render per 50 ms while j/k repeats
TRAIL = 0.02  # after a new selection, wait so the list paints its frame first
BURST = 0.15  # while j/k repeats, render at least this often
SETTLE = 0.15  # wait for the selection to rest before a read, as the web does
SKELETON_AFTER = 0.15  # a read that ends sooner shows no skeleton
SKELETON_HOLD = 0.5  # once shown, a skeleton stays this long (design §9)
SHORT_ROWS = 30
WATCH = frozenset(
    {"selected", "selected_key", "harness", "folded", "detail_open", "palette", "mode"}
)
MOVES = frozenset({"selected", "selected_key"})
GROUPS = ("src:", "plg:", "prj:")


@dataclass
class Read:
    """One lazy read through app.fetch."""

    started: float
    done: bool = False
    value: Any = None
    error: str = ""
    shown: float = 0.0
    hold: Timer | None = None


async def call(app: AtlasApp, module: str, func: str, *args: Any) -> None:
    """Run `skill_atlas.tui.<module>.<func>(app, *args)`; a missing module gets a toast."""
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


def _jobs() -> Any:
    try:
        return importlib.import_module("skill_atlas.tui.jobs")
    except ModuleNotFoundError:
        return None


def _panel(app: AtlasApp) -> DetailPanel | None:
    found = app.main.query(DetailPanel)
    return found.first() if found else None


def toggle_description(app: AtlasApp) -> None:
    """Show all of a long description, or clamp it again (key shift+m)."""
    panel = _panel(app)
    if panel is not None:
        panel._flip_desc()


class DetailPanel(VerticalScroll, can_focus=False):
    """Shows app.state.selected (a skill) or app.state.selected_key (a group or available skill).

    Up and down move between controls; enter or space acts. Section folds are saved.
    """

    DEFAULT_CSS = """
    DetailPanel {
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
        scrollbar-gutter: stable;
    }
    DetailPanel.-drawer { border-left: solid $atlas-border-strong; }
    DetailPanel > DetailBox { margin-bottom: 1; }
    DetailPanel > DetailBox.section { margin-bottom: 0; }
    DetailPanel > DetailBox.section.-open { margin-bottom: 1; }
    DetailPanel > DetailBox.section.-open.-after-fold { margin: 1 0 1 0; }
    DetailPanel > DetailBox.danger { margin: 1 0 1 0; }
    DetailPanel DetailText { padding: 0 2; color: $atlas-text; }
    DetailPanel DetailText.desc { max-width: 68; }
    DetailPanel DetailText.hint { padding: 0 2 0 4; }
    DetailPanel DetailHints { padding: 0 1; }
    DetailPanel DefList, DetailPanel DetailSkeleton, DetailPanel SparkView { padding: 0 2; }
    DetailPanel Heatmap, DetailPanel BarChart { padding: 0 2; }
    DetailPanel DetailBox.body > * { margin-bottom: 1; }
    DetailPanel DetailBox.body > DetailRow { margin-bottom: 0; }
    DetailPanel DetailBox.body > HarnessSwitch { margin-bottom: 0; }
    DetailPanel DetailBox.body > DetailText.sub { margin-bottom: 0; }
    DetailPanel DetailBox.body > *:last-child { margin-bottom: 0; }
    DetailPanel DetailBox.finding { padding: 0 2 0 4; }
    DetailPanel DetailBox.finding > DetailText { padding: 0; }
    DetailPanel DetailBox.finding > DetailText.code { padding: 0 1; background: $atlas-surface-2; }
    DetailPanel DetailBox.cards { padding: 0 2; }
    DetailPanel DetailBox.cards > * { margin-bottom: 1; }
    DetailPanel DetailBox.cards > *:last-child { margin-bottom: 0; }
    DetailPanel DetailBox.cards > DetailText { padding: 0; }
    DetailPanel DetailBox.card { background: $atlas-surface-2; }
    DetailPanel DetailBox.card.-accent { background: $atlas-accent-tint; }
    DetailPanel DetailBox.card.-warn { background: $atlas-warn-tint; }
    DetailPanel DetailBox.card.-danger { background: $atlas-danger-tint; }
    DetailPanel DetailBox.card > DetailText, DetailPanel DetailBox.card > DefList { padding: 0 1; }
    DetailPanel DetailBox.card > DetailText.hint { padding: 0 1 0 3; }
    DetailPanel DetailBox.card > DetailHints { padding: 0; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("down,j", "move(1)", "Next control", show=False),
        Binding("up,k", "move(-1)", "Previous control", show=False),
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
        self._target: tuple[str, str] | None = None
        self._timer: Timer | None = None
        self._settle: Timer | None = None
        self._last = 0.0
        self._burst = 0.0
        self._dirty = True
        self._seen: tuple | None = None
        self._reveal: str | None = None
        self._reads: dict[str, Read] = {}
        self._want: dict[str, tuple[Callable[..., Any], tuple[Any, ...]]] = {}
        self._job: dict | None = None
        self._desc_open = False
        self._sec_flip: set[str] = set()
        self._colors: dict[str, str] | None = None

    # Triggers

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self._new_theme)
        self.set_class(app_of(self).narrow, "-drawer")
        self.schedule()

    def _new_theme(self, _theme: object) -> None:
        self._colors = None
        self.schedule()

    def on_state_changed(self, event: StateChanged) -> None:
        if event.fields & WATCH:
            dirty = bool(event.fields & {"palette", "mode"})
            self.schedule(dirty=dirty, moved=bool(event.fields & MOVES))

    def on_data_changed(self, event: DataChanged) -> None:
        if event.parts & {"scan", "updates"}:
            self._drop("diff:", "hist:")
        if "scan" in event.parts:
            self._drop("sec:")
        self.schedule()

    def on_job_changed(self, event: JobChanged) -> None:
        if event.view is None and self._job is not None:
            self._drop("diff:", "hist:")
        self._job = event.view
        self.schedule()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Tab scrolls the control into view at once; Textual would animate the scroll."""
        self.scroll_to_widget(event.widget, animate=False)
        self.call_after_refresh(self._snap, event.widget)

    def _snap(self, widget: Widget) -> None:
        self.app.animator.force_stop_animation(self, "scroll_y")
        if widget.is_attached and widget.has_focus:
            self.scroll_to_widget(widget, animate=False)

    def on_resize(self) -> None:
        self.set_class(app_of(self).narrow, "-drawer")
        self.schedule()

    def schedule(self, dirty: bool = True, moved: bool = False) -> None:
        """Render soon, at most once per 50 ms. A new selection waits until the keys rest
        (trailing), but not more than 150 ms from the first key of a burst."""
        self._dirty = self._dirty or dirty
        now = time.monotonic()
        wait = max(TRAIL if moved else 0.001, THROTTLE - (now - self._last))
        if moved:
            self._burst = self._burst or now
            wait = max(0.001, min(wait, self._burst + BURST - now))
            if self._timer is not None:
                self._timer.stop()
                self._timer = None
        if self._timer is None:
            self._timer = self.set_timer(wait, self._redraw)

    # Lazy reads

    def _drop(self, *prefixes: str) -> None:
        for key in [k for k, r in self._reads.items() if k.startswith(prefixes) and r.done]:
            del self._reads[key]

    def _load(self, key: str, fn: Callable[..., Any], *args: Any) -> Load:
        self._want[key] = (fn, args)
        read = self._reads.get(key)
        now = time.monotonic()
        if read is None:
            return Load("wait")
        if not read.done:
            if now - read.started < SKELETON_AFTER:
                return Load("wait")
            read.shown = read.shown or now
            return Load("skeleton")
        if read.shown and now - read.shown < SKELETON_HOLD:
            if read.hold is None:
                read.hold = self.set_timer(read.shown + SKELETON_HOLD - now + 0.01, self.schedule)
            return Load("skeleton")
        if read.error:
            return Load("error", error=read.error)
        return Load("ok", read.value)

    def _start_reads(self) -> None:
        self._settle = None
        now = time.monotonic()
        started = False
        for key, (fn, args) in self._want.items():
            if key in self._reads:
                continue
            read = self._reads[key] = Read(now)
            self.run_worker(
                self._fetch(key, read, fn, args), group="detail-io", exit_on_error=False
            )
            started = True
        if started:
            self.set_timer(SKELETON_AFTER + 0.01, self.schedule)

    async def _fetch(self, key: str, read: Read, fn: Callable[..., Any], args: tuple) -> None:
        try:
            read.value = await app_of(self).fetch(fn, *args)
        except Exception as e:
            read.error = (str(e) or type(e).__name__).rstrip(".")
        read.done = True
        if self._reads.get(key) is read and key in self._want:
            self.schedule()

    # Rendering

    def target(self) -> tuple[str, str] | None:
        """("skill", path), ("group", id), ("avail", key), or None."""
        st = app_of(self).state
        if st.selected:
            return ("skill", st.selected)
        key = st.selected_key
        if not key:
            return None
        if key.startswith(GROUPS):
            return ("group", key)
        return ("avail", key) if key.startswith("a:") else None

    def _ctx(self) -> Ctx | None:
        app = app_of(self)
        ins = app.data.insights
        if ins is None:
            return None
        jobs = _jobs()
        state_of = getattr(jobs, "state_of", None)
        error_of = getattr(jobs, "error_of", None)
        confirming = getattr(jobs, "confirming", None)

        def job(name: str) -> str | None:
            return state_of(app, name) if state_of is not None else None

        def job_error(name: str) -> str:
            return str((error_of(app, name) if error_of is not None else "") or "")

        if self._colors is None:
            self._colors = theme.colors(app)
        return Ctx(
            ins=ins,
            data=app.data,
            atlas=app.atlas,
            harness=app.state.view_state().harness,
            colors=self._colors,
            dark=app.current_theme.dark,
            width=max(20, self.size.width - 5),
            short=app.size.height < SHORT_ROWS,
            folded=app.state.folded,
            load=self._load,
            job=job,
            job_error=job_error,
            desc_open=self._desc_open,
            confirm=confirming(app) if confirming is not None else None,
            sec_flip=frozenset(self._sec_flip),
            ssh=bool(os.environ.get("SSH_TTY")),
        )

    def _blocks(self, ctx: Ctx, target: tuple[str, str]) -> list[BoxEl]:
        kind, key = target
        if kind == "skill":
            s = ctx.ins.by_path.get(key)
            return skill_blocks(ctx, s) if s else []
        if kind == "group":
            return group_blocks(ctx, key)
        return avail_blocks(ctx, key)

    async def _redraw(self) -> None:
        self._timer = None
        self._burst = 0.0
        app = app_of(self)
        target = self.target()
        if target is None or not app.detail_visible:
            return
        seen = (
            target,
            id(app.data.insights),
            self._job,
            app.state.folded,
            app.state.view_state().harness,
            self.size.width,
            app.size.height < SHORT_ROWS,
        )
        if not self._dirty and seen == self._seen:
            return
        self._seen, self._dirty = seen, False
        self._last = time.monotonic()
        fresh = target != self._target
        if fresh:
            self._target = target
            self._desc_open = False
            self._sec_flip.clear()
        ctx = self._ctx()
        self._want = {}
        blocks = self._blocks(ctx, target) if ctx is not None else []
        focused = app.focused
        if focused is not None and self not in focused.ancestors:
            focused = None
        fid = focused.id if focused is not None else None
        cursor = focused.cursor if isinstance(focused, DetailHints) else 0
        before = self.controls()
        index = before.index(focused) if focused in before else 0
        async with self.batch():
            await reconcile(self, blocks)
        if fresh:
            self.scroll_home(animate=False)
        if focused is not None and not focused.is_attached:
            self._refocus(fid, cursor, index)
        if self._reveal is not None:
            found = self.query(f"#{wid(self._reveal, 'b')}")
            self._reveal = None
            if found:
                self.call_after_refresh(
                    self.scroll_to_widget, found.first(), animate=False, top=False
                )
        if any(k not in self._reads for k in self._want):
            if self._settle is not None:
                self._settle.stop()
            self._settle = self.set_timer(SETTLE, self._start_reads)

    def _refocus(self, fid: str | None, cursor: int, index: int) -> None:
        """Focus the same control again, else the one now at its place in the order."""
        found = self.query(f"#{fid}") if fid else None
        w = found.first() if found else None
        if w is not None and w.focusable:
            if isinstance(w, DetailHints):
                w.cursor = min(cursor, max(0, len(w.hints) - 1))
            w.focus(scroll_visible=False)
            return
        controls = self.controls()
        if not controls:
            app_of(self).main.query_one("#list").focus()
            return
        w = controls[min(index, len(controls) - 1)]
        w.focus(scroll_visible=False)
        self.scroll_to_widget(w, animate=False)

    # Keyboard

    def controls(self) -> list[Widget]:
        """The panel's focus stops, top to bottom."""
        return [w for w in self.walk_children(Widget) if w.focusable]

    def action_move(self, step: int) -> None:
        focused = self.screen.focused
        if isinstance(focused, DetailHints) and focused.move(step):
            return
        controls = self.controls()
        if not controls:
            return
        if focused in controls:
            i = max(0, min(len(controls) - 1, controls.index(focused) + step))
        else:
            i = 0 if step > 0 else len(controls) - 1
        w = controls[i]
        if w is focused:
            if step < 0:
                self.scroll_home(animate=False)
            return
        if isinstance(w, DetailHints):
            w.cursor = 0 if step > 0 else max(0, len(w.hints) - 1)
        w.focus(scroll_visible=False)
        self.scroll_to_widget(w, animate=False)

    # Actions

    def on_acted(self, event: Acted) -> None:
        event.stop()
        self.run_worker(self._do(event.act, event.on), group="detail-act")

    async def _do(self, act: Act, on: bool | None = None) -> None:
        app = app_of(self)
        n, a = act.name, act.args
        local: dict[str, Callable[[], Any]] = {
            "fold": lambda: self._fold(a[0]),
            "secfold": lambda: self._flip_sec(a[0]),
            "more_desc": self._flip_desc,
            "retry": lambda: self._retry(a[0]),
            "select": lambda: self.post_message(SkillSelected(a[0])),
            "group": lambda: self.post_message(ItemSelected(a[0])),
            "close": self._close,
        }
        if n in local:
            local[n]()
            return
        calls: dict[str, tuple[str, str, tuple[Any, ...]]] = {
            "read": ("screens.reader", "open_reader", a),
            "reveal": ("jobs", "reveal", a),
            "github": ("jobs", "open_github", a),
            "copy": ("jobs", "copy", a),
            "more": ("commands", "open_actions", a),
            "update": ("jobs", "update", (list(a),)),
            "unwatch": ("commands", "stop_watching", a),
            "dismiss": ("commands", "dismiss_new", a),
            "diff": ("screens.diff", "open_diff", a),
            "history": ("screens.history", "open_history", a),
            "compare": ("screens.diff", "open_compare", a),
            "link": ("screens.link", "open_link", (list(a),)),
            "delete": ("screens.confirm", "confirm_delete", (list(a),)),
            "install": ("jobs", "install", (a[0], list(a[1:])) if a else ()),
        }
        if n in calls:
            module, func, args = calls[n]
            await call(app, module, func, *args)
        elif n == "switch" and on is not None:
            await call(app, "jobs", "set_switch", a[0], [a[2]], on, a[1])
        elif n == "switch_group" and on is not None:
            await self._switch_group(a[0], a[1], on)

    def _fold(self, key: str) -> None:
        app = app_of(self)
        ctx = self._ctx()
        was_open = ctx.is_open(key) if ctx is not None else True
        folded = set(app.state.folded) - {key, "+" + key}
        folded.add(key if was_open else "+" + key)
        self._reveal = None if was_open else f"s:{key}"
        app.set_state(folded=frozenset(folded))

    def _flip_sec(self, key: str) -> None:
        self._sec_flip ^= {key}
        self.schedule()

    def _flip_desc(self) -> None:
        self._desc_open = not self._desc_open
        self.schedule()

    def _retry(self, key: str) -> None:
        self._reads.pop(key, None)
        self.schedule()

    def _close(self) -> None:
        app = app_of(self)
        if app.narrow:
            app.show_detail(False)
            return
        app.set_state(selected=None, selected_key=None)
        app.main.query_one("#list").focus()

    async def _switch_group(self, harness: str, source: str, on: bool) -> None:
        app = app_of(self)
        ins = app.data.insights
        if ins is None:
            return
        members = views.members_of(ins, harness, f"src:{source}")
        names = [s["name"] for s in members if views.switch_state(ins, harness, s)["on"] != on]
        if names:
            await call(app, "jobs", "set_switch", harness, names, on, "skill")
