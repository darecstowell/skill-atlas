"""Restore /name: the saved versions of a skill, each one diffed against the current folder."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from rich.cells import cell_len
from rich.segment import Segment
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.strip import Strip
from textual.widgets import Static

from ...core import views
from ..widgets import app_of
from . import AtlasModal, CloseCell, HintButton
from .diff import (
    DiffDialog,
    DiffPane,
    Rows,
    _style,
    busy,
    error_text,
    skill_for,
    slash,
    summary,
    toast,
)

if TYPE_CHECKING:
    from ..app import AtlasApp

REASONS = {"restore": "Before a restore", "update": "Before an update"}
EMPTY = "No saved versions yet. Before each update, the atlas saves a copy of this skill here."


def snap_time(at: str) -> str:
    """The web's medium date and short time, in local time: `Oct 27, 2026, 3:14 PM`."""
    if not at:
        return "an unknown time"
    try:
        dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return at
    dt = dt.astimezone() if dt.tzinfo else dt
    hour = dt.hour % 12 or 12
    return f"{dt:%b} {dt.day}, {dt.year}, {hour}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


class SnapshotList(Rows):
    """One row per saved version: date, reason, and version hash. Enter asks to restore it."""

    DEFAULT_CSS = """
    SnapshotList { height: auto; max-height: 5; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.snaps: list[dict] = []
        self._when: list[str] = []

    @property
    def count(self) -> int:
        return len(self.snaps)

    def set_snaps(self, snaps: list[dict]) -> None:
        self.snaps = snaps
        self._when = [snap_time(s.get("at", "")) for s in snaps]
        self.cursor = 0
        self.reflow()

    def draw(self, i: int, sub: int, width: int, *, cursor: bool, hover: bool) -> Strip:
        c = self.palette()
        s = self.snaps[i]
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
        when = self._when[i].ljust(max(map(cell_len, self._when)))
        reason = REASONS.get(s.get("reason", ""), REASONS["update"])
        segs = [
            Segment("▌ " if bar else "  ", _style(c["atlas-text"], bg)),
            Segment(when, _style(c["atlas-text"], bg)),
        ]
        room = width - 2 - cell_len(when)
        if room >= 2 + len(reason):
            segs.append(Segment("  " + reason, _style(c["atlas-muted"], bg)))
            room -= 2 + len(reason)
            if s.get("hash") and room >= 3 + len(s["hash"]):
                segs.append(Segment(" · ", _style(c["atlas-faint"], bg)))
                segs.append(Segment(s["hash"], _style(c["atlas-faint"], bg)))
        return Strip(segs).adjust_cell_length(width, _style(None, bg))


class ConfirmRestore(AtlasModal[bool]):
    """Restore /name from <time>? Cancel has the focus; `r` or the primary hint restores."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("r", "restore", "Restore", show=False)]
    DEFAULT_CSS = """
    ConfirmRestore > #df-dialog {
        width: 64;
        max-width: 100%;
        height: auto;
        max-height: 100%;
        padding: 1 2;
        background: $atlas-surface-1;
        border: round $atlas-border-strong;
    }
    ConfirmRestore #df-head { height: auto; }
    ConfirmRestore #df-title { width: 1fr; text-style: bold; color: $atlas-text; }
    ConfirmRestore .lead { margin-top: 1; color: $atlas-muted; }
    ConfirmRestore #df-actions { height: 1; margin-top: 1; align-horizontal: right; }
    ConfirmRestore #df-actions > HintButton { margin-left: 2; }
    """
    AUTO_FOCUS = "#df-cancel"

    def __init__(self, skill: str, when: str) -> None:
        super().__init__()
        self.skill = skill
        self.when = when

    def compose(self) -> ComposeResult:
        with Vertical(id="df-dialog"):
            with Horizontal(id="df-head"):
                yield Static(f"Restore {self.skill} from {self.when}?", id="df-title")
                yield CloseCell()
            yield Static(
                "The folder and its lock entry go back to that version. Before that, the atlas "
                "saves the current folder to History, so you can go back.",
                classes="lead",
            )
            with Horizontal(id="df-actions"):
                yield HintButton("esc", "Cancel", "close", id="df-cancel")
                yield HintButton("r", "Restore", "restore", variant="primary")

    def action_restore(self) -> None:
        self.dismiss(True)


class HistoryScreen(DiffDialog):
    """History of /name: pick a saved version, see how it differs from your copy, restore it."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "restore", "Restore", show=False),
        Binding("t", "again", "Try again", show=False),
    ]
    AUTO_FOCUS = "HintButton"
    DEFAULT_CSS = """
    HistoryScreen #df-state { height: auto; margin-top: 1; color: $atlas-muted; }
    HistoryScreen #df-state.-error { color: $atlas-danger; }
    HistoryScreen #df-snaps-label { height: 1; margin-top: 1; color: $atlas-muted; }
    HistoryScreen #df-summary { margin-top: 1; }
    HistoryScreen DiffPane { margin-top: 0; }
    HistoryScreen #df-snaps-label, HistoryScreen SnapshotList, HistoryScreen #df-summary,
    HistoryScreen DiffPane { display: none; }
    HistoryScreen.-ready #df-snaps-label, HistoryScreen.-ready SnapshotList,
    HistoryScreen.-ready #df-summary, HistoryScreen.-ready DiffPane { display: block; }
    HistoryScreen.-short SnapshotList { max-height: 3; }
    """

    def __init__(self, lock: str, skill: dict) -> None:
        super().__init__()
        self.lock_key = lock
        self.skill = skill
        self.snaps: list[dict] | None = None
        self.error: str | None = None
        self.diff_failed = False
        self.diffs: dict[str, dict] = {}
        self.text: list[str] | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="df-dialog"):
            with Horizontal(id="df-head"):
                yield Static(f"History of {slash(self.skill)}", id="df-title")
                yield CloseCell()
            yield Static(
                "From your copy to the selected saved version. "
                "Restore… replaces your copy with it.",
                classes="lead",
            )
            yield Static(id="df-state")
            yield Static("SAVED VERSIONS", id="df-snaps-label")
            yield SnapshotList(id="df-snaps")
            yield Static(id="df-summary")
            yield DiffPane(id="df-pane")
            with Horizontal(id="df-actions"):
                yield HintButton("esc", "Close", "close")
                yield HintButton("t", "Try again", "again", id="df-again")
                yield HintButton(
                    "r",
                    "Restore…",
                    "restore",
                    variant="primary",
                    busy_label="Restoring…",
                    id="df-restore",
                )

    def on_mount(self) -> None:
        super().on_mount()
        self.sync_actions()
        self.load()

    @property
    def snap_list(self) -> SnapshotList:
        return self.query_one(SnapshotList)

    def waiting(self, text: str) -> None:
        if self.snaps is None:
            self._state(text)
        else:
            super().waiting(text)

    def _state(self, text: str, *, error: bool = False) -> None:
        state = self.query_one("#df-state", Static)
        state.update(f"✗ {text}" if error else text)
        state.display = bool(text)
        state.set_class(error, "-error")

    @work(exclusive=True, group="history")
    async def load(self) -> None:
        app = app_of(self)
        self.error = None
        self.sync_actions()
        try:
            out = await self.wait_for("Reading saved versions…", app.atlas.history, self.lock_key)
        except Exception as e:
            self.error = error_text(e)
            fix = "Check that you can read the history folder, then press t to try again."
            self._state(f"Could not read the history: {self.error}. {fix}", error=True)
            self.sync_actions()
            return
        self.snaps = list(out.get("snapshots") or [])
        self._state("" if self.snaps else EMPTY)
        self.set_class(bool(self.snaps), "-ready")
        self.sync_actions()
        if not self.snaps:
            return
        self.snap_list.set_snaps(self.snaps)
        if self.focused is None or isinstance(self.focused, HintButton):
            self.snap_list.focus()
        self.show_snap(0)
        try:
            text = await app.fetch(app.atlas.skill_text, self.skill["path"])
        except Exception:
            return
        self.text = text.splitlines()
        self.query_one(DiffPane).add_text("SKILL.md", self.text)

    @on(Rows.Moved, "SnapshotList")
    def _snap_moved(self, event: Rows.Moved) -> None:
        event.stop()
        self.show_snap(event.index)

    @on(Rows.Activated, "SnapshotList")
    def _snap_opened(self, event: Rows.Activated) -> None:
        event.stop()
        if not event.mouse:
            self.action_restore()

    def show_snap(self, i: int) -> None:
        snap = (self.snaps or [])[i]
        d = self.diffs.get(snap["id"])
        if d is not None:
            self.show_diff(d)
        else:
            self.query_one("#df-summary", Static).update("")
            self.load_diff(snap["id"])

    @work(exclusive=True, group="snapshot")
    async def load_diff(self, snap_id: str) -> None:
        app = app_of(self)
        pane = self.query_one(DiffPane)
        self.diff_failed = False
        self.sync_actions()
        try:
            d = await self.wait_for(
                "Loading the diff…", app.atlas.snapshot_diff, self.lock_key, snap_id
            )
        except Exception as e:
            fix = "Press t to try again."
            pane.message(f"Could not get the changes: {error_text(e)}. {fix}", error=True)
            self.diff_failed = True
            self.sync_actions()
            return
        self.diffs[snap_id] = d
        cur = self.current()
        if cur is not None and cur["id"] == snap_id:
            self.show_diff(d)

    def show_diff(self, d: dict) -> None:
        pane = self.query_one(DiffPane)
        files = d.get("files") or []
        if self.text is not None:
            pane.texts["SKILL.md"] = self.text
        if not files:
            self.query_one("#df-summary", Static).update("")
            pane.message("This version has the same files as your copy.")
            return
        self.query_one("#df-summary", Static).update(
            summary(files, d.get("added", 0), d.get("removed", 0), self.palette())
        )
        pane.show_files(files)

    def current(self) -> dict | None:
        if not self.snaps:
            return None
        return self.snaps[self.snap_list.cursor]

    def sync_actions(self) -> None:
        self.query_one("#df-restore", HintButton).display = bool(self.snaps)
        self.query_one("#df-again", HintButton).display = self.error is not None or self.diff_failed

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "restore":
            return bool(self.snaps) and not self.query_one("#df-restore", HintButton).busy
        if action == "again":
            return self.error is not None or self.diff_failed
        return True

    def action_again(self) -> None:
        cur = self.current()
        if self.error is not None:
            self.load()
        elif self.diff_failed and cur is not None:
            self.load_diff(cur["id"])

    def action_restore(self) -> None:
        snap = self.current()
        if snap is None or not self.check_action("restore", ()):
            return
        app = app_of(self)
        if busy(app):
            toast(app, "An update is still running.")
            return
        when = snap_time(snap.get("at", ""))

        def done(ok: bool | None) -> None:
            if ok:
                self.restore(snap["id"], when)

        app.push_screen(ConfirmRestore(slash(self.skill), when), done)

    @work(exclusive=True, group="restore")
    async def restore(self, snap_id: str, when: str) -> None:
        app = app_of(self)
        hint = self.query_one("#df-restore", HintButton)
        hint.busy = True
        try:
            await app.fetch(app.atlas.rollback, self.lock_key, snap_id)
        except RuntimeError:
            toast(app, "An update is still running.")
        except Exception as e:
            toast(app, f"Could not restore: {error_text(e)}", severity="error")
        else:
            harness = app.data.harnesses.get(app.state.harness, {}).get("name") or "agent"
            self.dismiss(None)
            toast(
                app,
                Text.assemble(
                    "Restored ",
                    (self.lock_key, "bold"),
                    f" from {when}. Restart {harness} sessions to pick it up.",
                ),
            )
            app.reload()
            return
        hint.busy = False


def open_history(app: AtlasApp, name: str | None = None) -> None:
    """Show the saved versions of the tracked skill with this lock name, or the selected one."""
    s = skill_for(app, name)
    if s is None:
        toast(app, "Select a skill to see its saved versions.")
        return
    lock = views.lock_name(s)
    if lock is None:
        toast(app, f"{slash(s)} has no saved versions. Only skills from GitHub have them.")
        return
    app.push_screen(HistoryScreen(lock, s))
