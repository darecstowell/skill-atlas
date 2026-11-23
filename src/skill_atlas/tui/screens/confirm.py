"""The delete confirm, and the parts every dialog shares: the frame, hint buttons, and fields."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeVar, cast

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static

from ... import remove
from ...core import views
from ...core.atlas import Atlas
from .. import theme
from ..messages import DataChanged
from ..widgets import charts
from . import AtlasModal, CloseCell, HintButton

if TYPE_CHECKING:
    from textual.dom import DOMNode
    from textual.worker import Worker

    from ..app import AtlasApp

R = TypeVar("R")
T = TypeVar("T")
Severity = Literal["information", "warning", "error"]
BOLD = Style(bold=True)
NAME_WIDTH = 28
WAIT_AFTER, WAIT_MIN = 0.3, 0.5


# Helpers


def jobs() -> Any:
    """The jobs module, imported on use: it is built at the same time as the screens."""
    return importlib.import_module(f"{__package__.rpartition('.')[0]}.jobs")


async def run_job(name: str, app: AtlasApp, *args: Any, **kwargs: Any) -> Any:
    result = getattr(jobs(), name)(app, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def toast(
    app: AtlasApp,
    text: str | Text,
    *,
    severity: Severity = "information",
    undo: Callable[[], Awaitable[None]] | None = None,
    label: str = "",
) -> None:
    """A toast through jobs. With `undo`, `z` and the toast's `z Undo` hint run it."""
    j = jobs()
    if undo is None:
        j.toast(app, text, severity=severity)
        return
    j.push_undo(app, label or str(text), undo)
    # The newest undo entry is this one while its toast shows: a newer change replaces both.
    j.toast(app, text, severity=severity, action=("z", "Undo", lambda: j.undo(app)))


def said(*parts: str | tuple[str, Literal["bold"]]) -> Text:
    """Toast text with bold names: said("Saved the profile ", (name, "bold"), ".")."""
    return Text.assemble(*((p[0], BOLD) if isinstance(p, tuple) else p for p in parts))


def writable(app: AtlasApp) -> views.Insights | None:
    """The insights when the scan is in and the core can write; else a toast and None."""
    ins = app.data.insights
    if ins is None:
        toast(app, "The skills are still loading. Try again when the list shows.")
        return None
    if not ins.writable:
        toast(app, jobs().READ_ONLY)
        return None
    return ins


async def follow_job(app: AtlasApp, view: dict, note: str = "") -> None:
    """Hand a job that the core already started to jobs, for progress and the end toast."""
    result = jobs().follow(app, view, note=note)
    if inspect.isawaitable(result):
        await result


def spawn(node: DOMNode, work: Callable[[], Awaitable[None]], **kw: Any) -> Worker[None]:
    """Run a coroutine function as a worker. If an exclusive worker cancels it before it
    starts, no coroutine is left unawaited, as there would be with a coroutine object."""
    fn = cast("Callable[[], Coroutine[None, None, None]]", work)
    worker: Worker[None] = node.run_worker(fn, **kw)
    return worker


async def fetch_slow(node: DOMNode, show: Callable[[], object], fn: Callable[..., T], *a: Any) -> T:
    """`app.fetch(fn, *a)`. Calls `show` after WAIT_AFTER; once shown, it stays WAIT_MIN."""
    shown: list[float] = []

    def mark() -> None:
        shown.append(time.monotonic())
        show()

    async def hold() -> None:
        timer.stop()
        if shown:
            await asyncio.sleep(max(0.0, WAIT_MIN - (time.monotonic() - shown[0])))

    timer = node.set_timer(WAIT_AFTER, mark)
    try:
        result = await cast("AtlasApp", node.app).fetch(fn, *a)
    except Exception:
        await hold()
        raise
    await hold()
    return result


def reason(e: BaseException) -> str:
    return (str(e) or type(e).__name__).replace("`", "")


def sentence(text: str) -> str:
    """An error from the core as a sentence: first letter capitalized, a period at the end."""
    text = text.replace("`", "").strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def plural(n: int, word: str, many: str = "") -> str:
    return f"{n} {word if n == 1 else many or word + 's'}"


def tilde(path: str) -> str:
    return views.tilde(path, str(Path.home()))


def cut(text: str, width: int) -> str:
    return text if cell_len(text) <= width else text[: max(0, width - 1)] + "…"


def items(rows: Iterable[tuple[str, str, str]]) -> Content:
    """Lines of `name  tag  note`: names in a column, tags in warn, notes muted."""
    rows = list(rows)
    width = min(NAME_WIDTH, max((cell_len(n) for n, _, _ in rows), default=0))
    lines = []
    for name, tag, note in rows:
        name = cut(name, width)
        parts: list[str | tuple[str, str]] = [name + " " * (width - cell_len(name))]
        if tag:
            parts += ["  ", (tag, "$atlas-warn")]
        if note:
            parts += ["  ", (note, "$atlas-muted")]
        lines.append(Content.assemble(*parts))
    return Content("\n").join(lines)


def meta(*parts: str) -> Content:
    """Muted parts with a faint `·` between them."""
    out: list[str | tuple[str, str]] = []
    for i, part in enumerate(parts):
        if i:
            out.append((" · ", "$atlas-faint"))
        out.append((part, "$atlas-muted"))
    return Content.assemble(*out)


def merge_settings(app: AtlasApp, settings: dict) -> None:
    """Put a write's new switch settings into the scan, as the web page does, and redraw."""
    scan = app.data.scan
    if scan is None or not settings:
        return
    scan.setdefault("settings", {}).update(settings)
    app.data.put("scan", scan)
    app.broadcast(lambda: DataChanged(frozenset({"scan"})))


# Parts


class FieldLabel(Static):
    """A click on the label focuses its input."""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if self.parent is not None:
            self.parent.query_one(Input).focus()


class Field(Vertical):
    """A label, an input, and one line under it: a warning note, or an error and its fix."""

    DEFAULT_CSS = """
    Field { height: auto; }
    Field > FieldLabel { width: auto; color: $atlas-muted; }
    Field > Input { height: 1; border: none; padding: 0 1; }
    Field > Input { background: $atlas-surface-2; color: $atlas-text; }
    Field > Input:focus { border: none; background: $atlas-surface-3; }
    Field > Input:focus { background-tint: transparent; }
    Field > Input.-invalid, Field > Input.-invalid:focus { border: none; }
    Field > Input > .input--cursor { background: $atlas-text; color: $atlas-surface-3; }
    Field > Input > .input--cursor { text-style: none; }
    Field > Input > .input--placeholder { color: $atlas-faint; }
    Field > .field--line { display: none; height: auto; }
    Field > .field--line.-error { display: block; color: $atlas-danger; }
    Field > .field--line.-note { display: block; color: $atlas-warn; }
    """

    def __init__(
        self,
        label: str,
        *,
        value: str = "",
        placeholder: str = "",
        max_length: int = 0,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.label = label
        self.input = Input(
            value,
            placeholder=placeholder,
            max_length=max_length,
            select_on_focus=False,
        )
        self.line = Static("", classes="field--line")
        self.failed = False

    def compose(self) -> ComposeResult:
        yield FieldLabel(self.label)
        yield self.input
        yield self.line

    @property
    def value(self) -> str:
        return self.input.value

    def show_error(self, message: str) -> None:
        """Show the error and its fix, and put the cursor back in the input to fix it."""
        self.failed = True
        self.line.update(Content(f"✗ {message}"))
        self.line.set_classes("field--line -error")
        self.input.focus()

    def show_note(self, message: str) -> None:
        self.failed = False
        self.line.update(Content(f"! {message}"))
        self.line.set_classes("field--line -note")

    def clear(self) -> None:
        self.failed = False
        self.line.update("")
        self.line.set_classes("field--line")


class PickRow(Widget, can_focus=True):
    """A switch, a title, and a muted note on one line. A click, enter, or space flips it."""

    DEFAULT_CSS = """
    PickRow { height: 1; color: $atlas-text; }
    PickRow:hover { background: $atlas-surface-2; }
    PickRow:focus { background: $atlas-selection; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter,space", "flip", show=False)]
    ALLOW_SELECT = False

    on: reactive[bool] = reactive(True)

    class Changed(Message):
        def __init__(self, row: PickRow) -> None:
            super().__init__()
            self.row = row

    def __init__(
        self, title: str, note: str = "", *, on: bool = True, value: str = "", id: str | None = None
    ) -> None:
        super().__init__(id=id)
        self.title = title
        self.note = note
        self.value = value
        self.set_reactive(PickRow.on, on)
        self.tooltip = "Click to skip this" if on else "Click to include this"

    def render(self) -> Content:
        switch = Content.from_rich_text(charts.switch(self.on, theme.colors(self.app)))
        parts: list[str | Content | tuple[str, str]] = ["▌" if self.has_focus else " ", " "]
        parts += [switch, "  ", self.title]
        if self.note:
            parts += ["  ", (self.note, "$atlas-muted")]
        return Content.assemble(*parts)

    def action_flip(self) -> None:
        self.on = not self.on
        self.tooltip = "Click to skip this" if self.on else "Click to include this"
        self.post_message(self.Changed(self))

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.action_flip()


class Fold(Widget, can_focus=True):
    """`▸ Already here: 12` over a list. A click, enter, or space shows or hides the list."""

    DEFAULT_CSS = """
    Fold { height: 1; color: $atlas-muted; }
    Fold:hover { background: $atlas-surface-2; }
    Fold:focus { background: $atlas-selection; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter,space", "fold", show=False)]
    ALLOW_SELECT = False

    def __init__(self, title: str, target: Widget) -> None:
        super().__init__()
        self.title = title
        self.target = target
        target.display = False

    def render(self) -> Content:
        glyph = "▾" if self.target.display else "▸"
        return Content.assemble("▌" if self.has_focus else " ", " ", glyph, " ", self.title)

    def action_fold(self) -> None:
        self.target.display = not self.target.display
        self.refresh()

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.action_fold()


class Dialog(AtlasModal[R]):
    """A titled dialog: a ✕ cell, a body that scrolls when the window is short, hint buttons.

    Subclasses give `heading`, `body`, and `buttons`. Long work runs as an app worker, so it
    ends, and its toast shows, even when the user closes the dialog first.
    """

    DEFAULT_CSS = """
    Dialog { padding: 1 2; }
    Dialog > #frame {
        width: 72; max-width: 100%; height: auto; max-height: 100%;
        background: $atlas-surface-1; border: round $atlas-border-strong; padding: 1 2;
    }
    Dialog #heading { height: auto; }
    Dialog #title { width: auto; max-width: 1fr; text-style: bold; color: $atlas-text; }
    Dialog #title-meta { width: 1fr; color: $atlas-muted; padding-left: 2; }
    Dialog #body {
        height: auto; margin-top: 1;
        scrollbar-size-vertical: 1; scrollbar-size-horizontal: 0;
        scrollbar-background: $atlas-surface-1; scrollbar-background-hover: $atlas-surface-1;
        scrollbar-background-active: $atlas-surface-1; scrollbar-color: $atlas-border-strong;
        scrollbar-color-hover: $atlas-muted; scrollbar-color-active: $atlas-text;
    }
    Dialog #body > * { margin-bottom: 1; }
    Dialog #error { display: none; height: auto; margin-bottom: 1; color: $atlas-danger; }
    Dialog #buttons { height: 1; }
    Dialog #buttons > .gap { width: 1fr; height: 1; }
    Dialog #buttons > HintButton { margin-left: 1; }
    Dialog #buttons > HintButton:first-child { margin-left: 0; }
    Dialog .lead { color: $atlas-text; }
    Dialog .muted { color: $atlas-muted; }
    Dialog .warn { color: $atlas-warn; }
    Dialog .items { text-wrap: nowrap; text-overflow: ellipsis; }
    Dialog .group > .items { padding-left: 7; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("pagedown", "page(1)", show=False),
        Binding("pageup", "page(-1)", show=False),
    ]

    def heading(self) -> str | Content:
        return ""

    def heading_meta(self) -> str | Content:
        return ""

    def body(self) -> ComposeResult:
        yield from ()

    def buttons(self) -> ComposeResult:
        yield from ()

    @property
    def atlas_app(self) -> AtlasApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            with Horizontal(id="heading"):
                yield Static(self.heading(), id="title")
                yield Static(self.heading_meta(), id="title-meta")
                yield CloseCell()
            with VerticalScroll(id="body", can_focus=False):
                yield from self.body()
            yield Static(id="error")
            with Horizontal(id="buttons"):
                yield from self.buttons()

    def on_mount(self) -> None:
        self.call_after_refresh(self.fit)

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self.fit)

    def fit(self) -> None:
        """Clamp the body, so the title and the buttons stay in view on a short window."""
        error = self.query_one("#error")
        chrome = 4 + 1  # border and padding, then the margin above the body
        chrome += self.query_one("#heading").outer_size.height
        chrome += self.query_one("#buttons").outer_size.height
        chrome += error.outer_size.height + 1 if error.display else 0
        self.query_one("#body").styles.max_height = max(3, self.size.height - 2 - chrome)

    def action_page(self, step: int) -> None:
        body = self.query_one("#body", VerticalScroll)
        if step > 0:
            body.scroll_page_down(animate=False)
        else:
            body.scroll_page_up(animate=False)

    def set_heading(self, text: str | Content, meta_text: str | Content = "") -> None:
        self.query_one("#title", Static).update(text)
        self.query_one("#title-meta", Static).update(meta_text)

    def show_error(self, message: str) -> None:
        line = self.query_one("#error", Static)
        line.update(Content(f"✗ {message}") if message else "")
        line.display = bool(message)
        self.call_after_refresh(self.fit)

    @property
    def alive(self) -> bool:
        return self in self.app.screen_stack

    def submit(self, work: Callable[[], Awaitable[None]], button: str = "#go") -> None:
        """Run `work` once at a time, with the button busy, as an app worker."""
        hint = self.query_one(button, HintButton)
        if hint.busy:
            return

        async def run() -> None:
            hint.busy = True
            try:
                await work()
            finally:
                if self.alive:
                    hint.busy = False

        spawn(self.app, run, group=f"dialog-{id(self)}")


# Delete


def trash_problem(atlas: object) -> str | None:
    """Why the real core cannot move folders to the Trash here, or None."""
    if not isinstance(atlas, Atlas):
        return None
    if remove.TRASH is None:
        return "Delete needs a Trash folder, and this system has none"
    if remove.TRASH_INFO is None and not remove.TRASH.is_dir():
        return f"Delete needs a Trash folder, and {tilde(str(remove.TRASH))} is not there"
    return None


def harness_list(names: list[str]) -> str:
    """At most three names: `A, B, and 2 more`, as on the web page."""
    if len(names) > 3:
        return f"{', '.join(names[:3])}, and {len(names) - 3} more"
    return (" and " if len(names) == 2 else ", ").join(names)


def _dedupe(skills: Iterable[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for s in skills:
        seen.setdefault(s["dir_name"], s)
    return list(seen.values())


def marked_skills(app: AtlasApp) -> list[dict]:
    """The marked skills in scan order, as core.views.bulk_plan expects them."""
    ins = app.data.insights
    marked = app.state.marked
    return [s for s in ins.skills if s["path"] in marked] if ins else []


def delete_targets(app: AtlasApp, names: Iterable[str] | None = None) -> list[dict]:
    """Store skills to delete: the named ones, else the marks, the selection, or its group."""
    ins = app.data.insights
    if ins is None:
        return []
    harness = app.state.harness or "all"
    if names is not None:
        want = set(names)
        found = [s for s in ins.skills if s["dir_name"] in want or s["path"] in want]
    elif app.state.marked:
        found = views.bulk_plan(ins, harness, marked_skills(app))["delete"]
    elif app.state.selected:
        skill = app.data.skill(app.state.selected)
        found = [skill] if skill else []
    elif app.state.selected_key and app.state.selected_key[:4] in ("src:", "plg:", "prj:"):
        found = views.members_of(ins, harness, app.state.selected_key)
    else:
        found = []
    return _dedupe(s for s in found if s.get("store"))


class ConfirmDelete(Dialog[bool]):
    """`Move 3 skills to the Trash?` A stray click outside does not cancel; enter never deletes."""

    CLOSE_ON_OUTSIDE = False
    AUTO_FOCUS = "#cancel"
    BINDINGS: ClassVar[list[BindingType]] = [Binding("d", "confirm", show=False)]

    def __init__(self, skills: list[dict], harnesses: list[str], problem: str | None) -> None:
        super().__init__()
        self.skills = skills
        self.harnesses = harnesses
        self.problem = problem

    def heading(self) -> str:
        n = len(self.skills)
        what = f"/{self.skills[0].get('invoke') or self.skills[0]['name']}" if n == 1 else None
        return f"Move {what or plural(n, 'skill')} to the Trash?"

    def body(self) -> ComposeResult:
        n = len(self.skills)
        who = harness_list(self.harnesses)
        stop = f"{'It stops' if n == 1 else 'They stop'} loading in {who}. " if who else ""
        go = f"Lock entries and on/off settings for {'it' if n == 1 else 'them'} go too."
        yield Static(stop + go, classes="lead")
        rows = [
            (
                f"/{s.get('invoke') or s['name']}",
                "± edited" if s.get("local_edits") else "",
                tilde(s.get("dir") or ""),
            )
            for s in self.skills
        ]
        yield Static(items(rows), classes="items list")
        edited = sum(1 for s in self.skills if s.get("local_edits"))
        if edited:
            have = "has" if edited == 1 else "have"
            text = f"± {plural(edited, 'skill')} {have} changes you made after install."
            yield Static(text, classes="warn")
        yield Static(
            "You can undo this from the toast, or take the folders back out of the Trash.",
            classes="muted",
        )

    def buttons(self) -> ComposeResult:
        n = len(self.skills)
        yield HintButton("esc", "Cancel", "close", id="cancel")
        yield Static(classes="gap")
        yield HintButton(
            "d",
            f"Move {'' if n == 1 else f'{n} '}to Trash",
            "confirm",
            variant="danger",
            focusable=False,
            disabled=self.problem is not None,
            id="go",
        )

    def on_mount(self) -> None:
        if self.problem:
            self.show_error(f"{sentence(self.problem)} Remove the folders by hand instead.")

    def action_confirm(self) -> None:
        if self.problem is None:
            self.dismiss(True)


async def confirm_delete(app: AtlasApp, names: Iterable[str] | None = None) -> None:
    """Ask before moving store skills to the Trash, then hand them to jobs.delete."""
    if writable(app) is None:
        return
    skills = delete_targets(app, names)
    if not skills:
        toast(app, "Only skills in your skill store can move to the Trash. Pick one of those.")
        return
    problem = await app.fetch(trash_problem, app.atlas)
    found = app.data.harnesses
    ids = dict.fromkeys(h for s in skills for h in s.get("harnesses") or [] if h in found)
    labels = [found[h].get("label") or found[h].get("name") or h for h in ids]

    async def done(ok: bool | None) -> None:
        if ok:
            await run_job("delete", app, [s["dir_name"] for s in skills])

    app.push_screen(ConfirmDelete(skills, labels, problem), done)
