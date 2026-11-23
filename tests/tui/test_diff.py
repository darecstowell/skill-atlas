import sys
import threading
import time
import types
from datetime import datetime
from types import SimpleNamespace

import pytest
from textual import events

import skill_atlas.tui
from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.messages import JobChanged
from skill_atlas.tui.screens import HintButton, diff, history
from skill_atlas.tui.screens.diff import (
    CompareScreen,
    DiffScreen,
    DiffView,
    FileList,
    Line,
    fits,
    kb,
    lines_of,
    ops_of,
    unfold,
    wrap,
)
from skill_atlas.tui.screens.history import ConfirmRestore, HistoryScreen, SnapshotList, snap_time

WIDE, NARROW = (120, 36), (80, 24)
NOW = datetime(2026, 10, 28, 12, 0)
REPO = "coreyhaines31/marketingskills"


class Demo(DemoAtlas):
    """DemoAtlas that can hold or fail a read."""

    def __init__(self) -> None:
        super().__init__(now=NOW)
        self.gate: threading.Event | None = None
        self.fail: dict[str, Exception] = {}
        self.rolled: list[tuple[str, str]] = []

    def _hold(self, what: str) -> None:
        if self.gate is not None:
            self.gate.wait(5)
        if what in self.fail:
            raise self.fail[what]

    def diff(self, name):
        self._hold("diff")
        return super().diff(name)

    def compare(self, a, b):
        self._hold("compare")
        return super().compare(a, b)

    def history(self, name):
        self._hold("history")
        return super().history(name)

    def rollback(self, name, snap_id):
        self._hold("rollback")
        self.rolled.append((name, snap_id))
        return super().rollback(name, snap_id)


@pytest.fixture
def jobs(monkeypatch):
    """Record toasts and updates; `running` says whether a job runs."""
    calls = SimpleNamespace(toasts=[], updates=[], running=False)
    try:
        from skill_atlas.tui import jobs as module
    except Exception:
        module = types.ModuleType("skill_atlas.tui.jobs")
        monkeypatch.setitem(sys.modules, module.__name__, module)
        monkeypatch.setattr(skill_atlas.tui, "jobs", module, raising=False)

    def toast(app, text, *, severity="information", action=None):
        calls.toasts.append((str(text), severity))

    monkeypatch.setattr(module, "toast", toast, raising=False)
    monkeypatch.setattr(
        module, "update", lambda app, names=None, confirmed=False: calls.updates.append(names)
    )
    monkeypatch.setattr(module, "running", lambda app: calls.running, raising=False)
    return calls


@pytest.fixture
def atlas():
    return Demo()


@pytest.fixture
def app(prefs, atlas):
    return AtlasApp(atlas, prefs=prefs)


def find(app, text):
    """The screen offset of the first cell of `text` on the top screen."""
    for y, strip in enumerate(app.screen._compositor.render_strips()):
        x = strip.text.find(text)
        if x >= 0:
            return (x, y)
    raise AssertionError(f"{text!r} is not on the screen")


def shown(app, text) -> bool:
    try:
        find(app, text)
    except AssertionError:
        return False
    return True


def record(app, name):
    return next(
        s for s in app.data.skills if s.get("dir_name") == name and "/.agents/" in s["path"]
    )


async def opened(pilot, fn, *args):
    fn(pilot.app, *args)
    await settle(pilot)
    return pilot.app.screen


# ---------------------------------------------------------------- pure parts


def test_lines_are_numbered_and_gaps_fold():
    ops = [("@", "@@ -3,3 +3,4 @@"), (" ", "a"), ("-", "b"), ("+", "B"), ("+", "C"), (" ", "d")]
    ops += [("@", "@@ -10,1 +11,1 @@"), (" ", "j")]
    lines = lines_of(ops)
    assert [(x.kind, x.old, x.new) for x in lines] == [
        ("fold", None, None),
        ("ctx", 3, 3),
        ("del", 4, None),
        ("add", None, 4),
        ("add", None, 5),
        ("ctx", 5, 6),
        ("fold", None, None),
        ("ctx", 10, 11),
    ]
    assert (lines[0].first, lines[0].last, lines[0].shift) == (1, 2, 0)
    assert (lines[6].first, lines[6].last, lines[6].shift) == (6, 9, 1)


def test_the_end_folds_only_when_the_old_text_is_known_and_whole():
    text = [f"line {n}" for n in range(1, 21)]
    ops = [("@", "@@ -2,2 +2,2 @@"), (" ", "line 2"), ("-", "line 3"), ("+", "new 3")]
    assert lines_of(ops)[-1].kind == "add"
    end = lines_of(ops, text)[-1]
    assert (end.kind, end.first, end.last, end.shift) == ("fold", 4, 20, 0)
    assert lines_of(ops, text, complete=False)[-1].kind == "add"


def test_a_fold_unfolds_into_numbered_lines():
    text = [f"line {n}" for n in range(1, 8)]
    ops = [("@", "@@ -5,2 +5,3 @@"), (" ", "line 5"), ("+", "x"), (" ", "line 6")]
    lines = lines_of(ops, text)
    assert fits(lines, text)
    assert not fits(lines, ["other"] * 7)
    out = unfold(lines, 0, text)
    assert [(x.old, x.new, x.text) for x in out[:4]] == [
        (1, 1, "line 1"),
        (2, 2, "line 2"),
        (3, 3, "line 3"),
        (4, 4, "line 4"),
    ]
    assert out[-1].kind == "fold" and (out[-1].first, out[-1].shift) == (7, 1)


def test_ops_read_the_api_lines():
    entry = {"diff": ["@@ -1 +1 @@", "-old", "+new", " same"]}
    assert ops_of(entry) == [("@", "@@ -1 +1 @@"), ("-", "old"), ("+", "new"), (" ", "same")]
    lines = lines_of(ops_of(entry))
    assert [(x.kind, x.old, x.new) for x in lines] == [
        ("del", 1, None),
        ("add", None, 1),
        ("ctx", 2, 2),
    ]


def test_wrap_breaks_after_spaces_and_keeps_every_cell():
    text = "Keep the first draft short. Expand only the parts the user asks about."
    rows = wrap(text, 20)
    assert "".join(rows) == text
    assert all(len(r) <= 20 for r in rows)
    assert rows[0] == "Keep the first "
    assert wrap("x" * 25, 10) == ["x" * 10, "x" * 10, "x" * 5]
    assert wrap("", 10) == [""]


def test_sizes_and_times_read_as_on_the_web():
    assert kb(900) == "900 B"
    assert kb(2150) == "2.1 KB"
    assert kb(40960) == "40 KB"
    local = datetime(2026, 9, 30, 14, 5).astimezone()
    assert snap_time(local.isoformat()) == "Sep 30, 2026, 2:05 PM"
    assert snap_time("") == "an unknown time"


# ---------------------------------------------------------------- see changes


@pytest.mark.asyncio
async def test_see_changes_lists_files_and_shows_the_first(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "copywriting")
        assert isinstance(screen, DiffScreen)
        assert shown(app, "Changes in /copywriting")
        assert shown(app, f"From your copy to the latest version on {REPO}.")
        assert shown(app, "1 added · 3 changed · 1 removed")
        assert shown(app, "+22 −13 lines")
        files = screen.query_one(FileList)
        assert [f["path"] for f in files.files][:2] == ["SKILL.md", "assets/example.png"]
        assert app.focused is files
        view = screen.query_one(DiffView)
        assert view.text is not None
        assert any(x.kind == "del" for x in view.lines)
        assert shown(app, "27 unchanged lines")
        assert shown(app, "▸")
        assert not screen.query_one("#df-warn").display


@pytest.mark.asyncio
async def test_keys_move_between_files_and_close(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "copywriting")
        view = screen.query_one(DiffView)
        await pilot.press("j")
        await settle(pilot)
        assert view.lines[0].text.startswith("Binary file, ")
        assert shown(app, "Binary file, ")
        await pilot.press("right_square_bracket")
        await settle(pilot)
        assert screen.query_one(FileList).cursor == 2
        assert all(x.kind in ("del", "fold") for x in view.lines)
        await pilot.press("left_square_bracket", "left_square_bracket")
        await settle(pilot)
        assert screen.query_one(FileList).cursor == 0
        await pilot.press("tab")
        assert app.focused is view
        await pilot.press("tab")
        assert isinstance(app.focused, HintButton) and app.focused.label == "Close"
        await pilot.press("tab")
        assert app.focused is screen.query_one("#df-update")
        await pilot.press("q")
        await settle(pilot)
        assert not isinstance(app.screen, DiffScreen)
        diff.open_diff(app, "copywriting")
        await settle(pilot)
        await pilot.press("escape")
        await settle(pilot)
        assert not isinstance(app.screen, DiffScreen)


@pytest.mark.asyncio
async def test_enter_on_a_fold_shows_the_unchanged_lines(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "copywriting")
        view = screen.query_one(DiffView)
        before = len(view.lines)
        await pilot.press("tab")
        assert app.focused is view and view.lines[0].kind == "fold"
        await pilot.press("enter")
        await settle(pilot)
        assert len(view.lines) == before + 26
        assert [x.old for x in view.lines[:3]] == [1, 2, 3]
        assert view.cursor == 0


@pytest.mark.asyncio
async def test_mouse_alone_picks_files_unfolds_and_updates(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "copywriting")
        view = screen.query_one(DiffView)
        await pilot.click(offset=find(app, "scripts/score.py"))
        await settle(pilot)
        assert screen.query_one(FileList).cursor == 4
        assert any(x.text.startswith("WEAK =") for x in view.lines)
        await pilot.click(offset=find(app, "SKILL.md"))
        await settle(pilot)
        before = len(view.lines)
        x, y = find(app, "3 unchanged lines")
        await pilot.hover(offset=(x, y))
        await settle(pilot)
        assert view.hover is not None and view.tooltip == "Show the 3 unchanged lines"
        await pilot.click(offset=(x, y))
        await settle(pilot)
        assert len(view.lines) == before + 2
        assert not shown(app, " 3 unchanged lines")
        top = view.scroll_y
        view.post_message(events.MouseScrollDown(view, 5, 5, 0, 1, 0, False, False, False))
        await settle(pilot)
        assert view.scroll_y > top
        await pilot.click(offset=find(app, "u Update"))
        await settle(pilot)
        assert not isinstance(app.screen, DiffScreen)
        assert jobs.updates == [["copywriting"]]


@pytest.mark.asyncio
async def test_u_updates_and_the_close_cell_closes(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await opened(pilot, diff.open_diff, "copywriting")
        await pilot.press("u")
        await settle(pilot)
        assert jobs.updates == [["copywriting"]]
        await opened(pilot, diff.open_diff, "copywriting")
        await pilot.click(offset=find(app, "✕"))
        await settle(pilot)
        assert not isinstance(app.screen, DiffScreen)
        assert jobs.updates == [["copywriting"]]


@pytest.mark.asyncio
async def test_edited_skill_warns_and_asks_to_replace_edits(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "seo-audit")
        assert screen.query_one("#df-warn").display
        assert shown(app, "You changed this skill after install.")
        hint = screen.query_one("#df-update", HintButton)
        assert hint.label == "Replace my edits" and hint.has_class("-warn")


@pytest.mark.asyncio
async def test_update_hides_when_current_or_a_job_runs(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "analytics")
        assert not screen.query_one("#df-update").display
        await pilot.press("u")
        await settle(pilot)
        assert isinstance(app.screen, DiffScreen) and jobs.updates == []
        await pilot.press("escape")
        jobs.running = True
        screen = await opened(pilot, diff.open_diff, "copywriting")
        assert not screen.query_one("#df-update").display


@pytest.mark.asyncio
async def test_a_job_that_starts_hides_update_and_a_theme_change_redraws(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "copywriting")
        assert screen.query_one("#df-update").display
        jobs.running = True
        app.broadcast(lambda: JobChanged({"done": False, "items": {}}))
        await settle(pilot)
        assert not screen.query_one("#df-update").display
        view = screen.query_one(DiffView)
        dark = view.render_line(0)
        app.theme = "atlas-light"
        await settle(pilot)
        assert view.render_line(0).text == dark.text
        assert view.render_line(0) != dark


@pytest.mark.asyncio
async def test_slow_download_shows_progress_then_the_diff(app, atlas, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        atlas.gate = threading.Event()
        diff.open_diff(app, "copywriting")
        await pilot.pause(0.1)
        screen = app.screen
        assert not shown(app, "Downloading")
        assert screen.query_one("#df-update", HintButton).disabled
        await pilot.pause(0.4)
        assert shown(app, f"Downloading {REPO}…")
        atlas.gate.set()
        start = time.monotonic()
        while screen.query_one(DiffView).lines[0].kind == "msg":
            await pilot.pause(0.05)
            assert time.monotonic() - start < 3
        assert not screen.query_one("#df-update", HintButton).disabled


@pytest.mark.asyncio
async def test_errors_and_same_files_say_so(app, atlas, jobs, monkeypatch):
    atlas.fail["diff"] = ValueError("could not download acme/x: not found")
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "copywriting")
        assert shown(app, "✗ Could not get the changes: could not download acme/x: not found.")
        error = screen.query_one(DiffView).lines[0]
        assert error.kind == "error" and error.text.endswith(
            "Check your network, then press t to try again."
        )
        assert screen.query_one("#df-update", HintButton).disabled
        assert screen.query_one("#df-again").display
        del atlas.fail["diff"]
        await pilot.press("t")
        await settle(pilot)
        assert screen.query_one(FileList).count == 5
        assert not screen.query_one("#df-again").display
        assert not screen.query_one("#df-update", HintButton).disabled
        await pilot.press("escape")
        monkeypatch.setattr(
            atlas,
            "diff",
            lambda name: {"name": name, "repo": REPO, "local_edits": False, "files": []},
        )
        await opened(pilot, diff.open_diff, "copywriting")
        assert shown(app, "The files are the same. Only the version record is different.")


@pytest.mark.asyncio
async def test_untracked_or_no_selection_toasts(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.set_state(selected=None)
        diff.open_diff(app)
        acme = next(s for s in app.data.skills if s["name"] == "acme-api-style")
        app.set_state(selected=acme["path"])
        diff.open_diff(app)
        history.open_history(app)
        await settle(pilot)
        assert [t for t, _ in jobs.toasts] == [
            "Select a skill to see its changes.",
            "Could not get the changes: /acme-api-style is not linked to a GitHub repo.",
            "/acme-api-style has no saved versions. Only skills from GitHub have them.",
        ]


@pytest.mark.asyncio
async def test_narrow_window_stacks_the_files_over_the_diff(app, jobs):
    async with app.run_test(size=NARROW) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "copywriting")
        pane = screen.query_one("#df-pane")
        assert pane.has_class("-stacked")
        files, view = screen.query_one(FileList), screen.query_one(DiffView)
        assert files.region.bottom <= view.region.y
        assert view.region.height >= 9
        assert shown(app, "esc Close") and shown(app, "u Update")


@pytest.mark.asyncio
async def test_one_file_at_80_by_24_gives_the_diff_most_rows(app, jobs):
    async with app.run_test(size=NARROW) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "ai-seo")
        view = screen.query_one(DiffView)
        assert not screen.query_one("#df-caption").display
        assert shown(app, "SKILL.md   +7 −2 lines")
        assert find(app, "SKILL.md")[1] == find(app, "Changes in /ai-seo")[1]
        assert view.region.height >= 17


@pytest.mark.asyncio
async def test_lines_read_without_color(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "copywriting")
        view = screen.query_one(DiffView)
        rows = [view.render_line(y).text for y in range(view.size.height)]
        assert any(r.lstrip().startswith("31") and " − Compare" in r for r in rows)
        assert any(" + Keep the first draft" in r for r in rows)
        await pilot.press("tab")
        assert view.render_line(0).text.startswith("▌")


@pytest.mark.asyncio
async def test_a_long_diff_draws_only_what_shows(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, diff.open_diff, "copywriting")
        view = screen.query_one(DiffView)
        lines = [Line("add" if n % 3 else "ctx", f"line {n}", old=n, new=n) for n in range(4000)]
        start = time.monotonic()
        view.show(lines)
        view.focus()
        await settle(pilot)
        await pilot.press("pagedown", "pagedown", "end")
        await settle(pilot)
        assert time.monotonic() - start < 2
        assert view.cursor == 3999
        assert len(view._cache) < 200


# ---------------------------------------------------------------- compare


@pytest.mark.asyncio
async def test_compare_shows_both_paths_and_the_diff(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        s = record(app, "copywriting")
        screen = await opened(pilot, diff.open_compare, s["path"])
        assert isinstance(screen, CompareScreen)
        assert shown(app, "− ~/.agents/skills/copywriting/SKILL.md")
        assert shown(app, "+ ~/.claude-work/skills/copywriting/SKILL.md")
        assert shown(app, "+1 −2 lines")
        view = screen.query_one(DiffView)
        assert app.focused is view
        assert view.text is not None and view.lines[-1].kind == "fold"
        await pilot.press("enter")
        await settle(pilot)
        assert view.lines[0].old == 1
        await pilot.click(offset=find(app, "esc Close"))
        await settle(pilot)
        assert not isinstance(app.screen, CompareScreen)


@pytest.mark.asyncio
async def test_compare_states(app, atlas, jobs, monkeypatch):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        s = record(app, "copywriting")
        app.set_state(selected=s["path"])
        same = {"lines": [], "truncated": False, "added": 0, "removed": 0}
        monkeypatch.setattr(atlas, "compare", lambda a, b: same)
        await opened(pilot, diff.open_compare)
        assert shown(app, "The two files are the same now.")
        await pilot.press("escape")
        monkeypatch.setattr(atlas, "compare", lambda a, b: (_ for _ in ()).throw(OSError("gone")))
        await opened(pilot, diff.open_compare)
        assert shown(app, "✗ Could not compare the files: gone. Press ctrl+p and choose Reload")
        await pilot.press("escape")
        alone = next(x for x in app.data.skills if not x.get("copies"))
        app.set_state(selected=alone["path"])
        diff.open_compare(app)
        assert jobs.toasts[-1][0] == f"/{alone['invoke']} has no copies that differ."


# ---------------------------------------------------------------- history


@pytest.mark.asyncio
async def test_history_lists_versions_and_diffs_each(app, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, history.open_history, "copywriting")
        assert isinstance(screen, HistoryScreen)
        assert shown(app, "History of /copywriting")
        assert shown(app, "From your copy to the selected saved version.")
        snaps = screen.query_one(SnapshotList)
        assert snaps.count == 5 and app.focused is snaps
        assert shown(app, "Before a restore") and shown(app, "Before an update")
        view = screen.query_one(DiffView)
        first = list(view.lines)
        assert any(x.kind in ("add", "del") for x in first)
        await pilot.press("j")
        await settle(pilot)
        assert snaps.cursor == 1 and view.lines != first
        await pilot.click(offset=find(app, snap_time(snaps.snaps[3]["at"])))
        await settle(pilot)
        assert snaps.cursor == 3
        assert screen.diffs.keys() >= {snaps.snaps[i]["id"] for i in (0, 1, 3)}


@pytest.mark.asyncio
async def test_restore_asks_once_then_rolls_back(app, atlas, jobs, monkeypatch):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        reloads = []
        monkeypatch.setattr(app, "reload", lambda *a, **k: reloads.append(a))
        screen = await opened(pilot, history.open_history, "copywriting")
        snap = screen.query_one(SnapshotList).snaps[0]
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, ConfirmRestore)
        assert shown(app, f"Restore /copywriting from {snap_time(snap['at'])}?")
        await pilot.press("enter")
        await settle(pilot)
        assert app.screen is screen and atlas.rolled == []
        await pilot.press("r")
        await settle(pilot)
        await pilot.click(offset=find(app, "r Restore "))
        await settle(pilot)
        assert atlas.rolled == [("copywriting", snap["id"])]
        assert not isinstance(app.screen, HistoryScreen)
        restart = app.data.harnesses[app.state.harness]["name"]
        when = snap_time(snap["at"])
        expected = f"Restored copywriting from {when}. Restart {restart} sessions to pick it up."
        assert jobs.toasts == [(expected, "information")]
        assert reloads


@pytest.mark.asyncio
async def test_restore_by_mouse_alone(app, atlas, jobs, monkeypatch):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        monkeypatch.setattr(app, "reload", lambda *a, **k: None)
        screen = await opened(pilot, history.open_history, "emails")
        snap = screen.query_one(SnapshotList).snaps[1]
        await pilot.click(offset=find(app, snap_time(snap["at"])))
        await pilot.click(offset=find(app, "r Restore…"))
        await settle(pilot)
        assert isinstance(app.screen, ConfirmRestore)
        await pilot.click(offset=find(app, "esc Cancel"))
        await settle(pilot)
        assert app.screen is screen and atlas.rolled == []
        await pilot.click(offset=find(app, "r Restore…"))
        await settle(pilot)
        await pilot.click(offset=find(app, "r Restore "))
        await settle(pilot)
        assert atlas.rolled == [("emails", snap["id"])]


@pytest.mark.asyncio
async def test_restore_blocked_or_failed_says_why(app, atlas, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, history.open_history, "copywriting")
        jobs.running = True
        await pilot.press("r")
        await settle(pilot)
        assert app.screen is screen
        assert jobs.toasts[-1] == ("An update is still running.", "information")
        jobs.running = False
        atlas.fail["rollback"] = OSError("disk full")
        await pilot.press("r")
        await settle(pilot)
        await pilot.press("r")
        await settle(pilot)
        assert app.screen is screen
        assert jobs.toasts[-1] == ("Could not restore: disk full", "error")
        hint = screen.query_one("#df-restore", HintButton)
        assert hint.label == "Restore…" and not hint.busy
        atlas.fail["rollback"] = RuntimeError("an update is still running")
        await pilot.press("r")
        await settle(pilot)
        await pilot.press("r")
        await settle(pilot)
        assert jobs.toasts[-1] == ("An update is still running.", "information")


@pytest.mark.asyncio
async def test_history_empty_and_error_states(app, atlas, jobs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = await opened(pilot, history.open_history, "analytics")
        assert shown(app, "No saved versions yet. Before each update, the atlas saves a copy")
        assert not screen.query_one("#df-restore").display
        await pilot.press("escape")
        atlas.fail["history"] = OSError("permission denied")
        screen = await opened(pilot, history.open_history, "copywriting")
        assert shown(app, "✗ Could not read the history: permission denied. Check that you")
        assert screen.query_one("#df-state").has_class("-error")
        assert screen.query_one("#df-again").display
        del atlas.fail["history"]
        await pilot.click(offset=find(app, "t Try again"))
        await settle(pilot)
        assert screen.query_one(SnapshotList).count == 5
        assert not screen.query_one("#df-again").display


@pytest.mark.asyncio
async def test_history_at_80_by_24(app, jobs):
    async with app.run_test(size=NARROW) as pilot:
        await settle(pilot)
        screen = await opened(pilot, history.open_history, "copywriting")
        snaps, view = screen.query_one(SnapshotList), screen.query_one(DiffView)
        assert snaps.region.height == 3 and view.region.height >= 4
        await pilot.press("end")
        await settle(pilot)
        assert snaps.cursor == 4 and shown(app, snap_time(snaps.snaps[4]["at"]))
