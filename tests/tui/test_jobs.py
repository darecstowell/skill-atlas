import asyncio
import threading
from datetime import datetime, timezone

import pytest
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from skill_atlas.core import views
from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui import app as appmod
from skill_atlas.tui import jobs, theme
from skill_atlas.tui.app import AtlasApp, ErrorBand, settle
from skill_atlas.tui.messages import DataChanged, JobChanged
from skill_atlas.tui.screens import profiles
from skill_atlas.tui.screens.reader import ReaderScreen, open_reader
from skill_atlas.tui.widgets import toast as toasts
from skill_atlas.tui.widgets.progress import JobBar, fraction, headline
from skill_atlas.tui.widgets.toast import AtlasToast, ToastClose, ToastHint

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
SIZE = (120, 36)
HOME = "claude-code:personal"
MARKETING = "coreyhaines31/marketingskills"


class Rows(Widget, can_focus=True):
    """Stands in for the skill list: it keeps the messages it got, in order."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.data_events = 0
        self.views: list[dict | None] = []
        self.cursor = 0
        self.rows: list = []

    def on_data_changed(self, event: DataChanged) -> None:
        self.data_events += 1

    def on_job_changed(self, event: JobChanged) -> None:
        self.views.append(event.view)


class LeanApp(AtlasApp):
    """The app with only the regions these tests need, so other screens cannot break them."""

    def compose(self):
        yield Static("Skill Atlas", id="header")
        yield Static(id="viewstrip")
        yield Static(id="bulkbar")
        yield JobBar(id="rule")
        yield ErrorBand(id="error-band")
        with Horizontal(id="main"):
            yield appmod.SkillList(id="list")
            yield Static(id="divider")
            yield Vertical(id="detail-pane")
        yield Static("keys", id="keybar")
        yield Static(id="too-small")


class Spy:
    def __init__(self, result=None):
        self.calls: list[tuple] = []
        self.result = result

    def __call__(self, *args, **kw):
        self.calls.append(args + tuple(kw.items()))
        return self.result


def raises(error):
    def fail(*args, **kw):
        raise error

    return fail


@pytest.fixture
def demo():
    return DemoAtlas(now=NOW)


class Steps(list):
    """The timers of a job's end: the hold and the ticks. The test runs them by hand."""

    def run(self):
        self.pop(0)()


@pytest.fixture
def steps():
    return Steps()


@pytest.fixture
def lean(prefs, demo, steps, monkeypatch):
    monkeypatch.setattr(appmod, "SkillList", Rows)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setattr(jobs, "POLL", 0.01)
    monkeypatch.setattr(jobs, "_later", lambda app, seconds, fn: steps.append(fn))
    monkeypatch.setattr(jobs, "_pbcopy", Spy())
    monkeypatch.setattr(jobs.webbrowser, "open", Spy(True))
    app = LeanApp(demo)
    monkeypatch.setattr(app, "copy_to_clipboard", Spy())
    return app


@pytest.fixture
def held(demo, monkeypatch):
    """Polls of the demo job wait until the test sets this event."""
    gate = threading.Event()
    real = demo.job

    def job(job_id):
        gate.wait(5)
        return real(job_id)

    monkeypatch.setattr(demo, "job", job)
    yield gate
    gate.set()


def skill(app, name):
    return next(s for s in app.data.insights.skills if s["name"] == name and s.get("store"))


def switch(app, name):
    return views.switch_state(app.data.insights, app.state.harness, skill(app, name))["on"]


def disk(demo, name, harness=HOME):
    return name not in demo.data()["settings"][harness]["skillOverrides"]


def shown(app):
    t = toasts.current(app)
    return t.text.plain if t else None


async def start(app, pilot, name=None, **state):
    await settle(pilot)
    if name:
        state["selected"] = skill(app, name)["path"]
    app.set_state(**state)
    await pilot.pause()


async def until(pilot, check, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not check():
        assert loop.time() < end, "timed out"
        await asyncio.sleep(0.01)
        await pilot.pause()


# Switches


@pytest.mark.asyncio
async def test_x_flips_the_switch_at_once_then_writes_with_an_undo_toast(lean, demo):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads")
        rows = lean.query_one(Rows)
        before = rows.data_events
        assert switch(lean, "ads")
        await pilot.press("x")
        assert not switch(lean, "ads")
        assert rows.data_events > before
        await settle(pilot)
        assert not disk(demo, "ads")
        assert shown(lean) == "Turned ads off. Restart Claude Code sessions to pick it up."
        hint = lean.query_one(ToastHint)
        assert hint.render().plain == "z Undo"


@pytest.mark.asyncio
async def test_z_puts_the_switch_back_and_does_nothing_when_the_stack_is_empty(lean, demo):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads")
        await pilot.press("z")
        await settle(pilot)
        assert shown(lean) is None and switch(lean, "ads")
        await pilot.press("x")
        await settle(pilot)
        await pilot.press("z")
        assert switch(lean, "ads")
        await settle(pilot)
        assert disk(demo, "ads")
        await pilot.press("z")
        await settle(pilot)
        assert switch(lean, "ads") and disk(demo, "ads")


@pytest.mark.asyncio
async def test_click_undo_on_the_toast(lean, demo):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads")
        await pilot.press("x")
        await settle(pilot)
        await pilot.click(ToastHint)
        await settle(pilot)
        assert switch(lean, "ads") and disk(demo, "ads")
        await until(pilot, lambda: not lean.query(AtlasToast))


@pytest.mark.asyncio
async def test_a_failed_write_reverts_the_switch_and_says_why(lean, demo, monkeypatch):
    gate = threading.Event()

    def broken(*args):
        gate.wait(5)
        raise ValueError(
            "/home/demo/.claude/settings.json is read-only, so the atlas cannot change it"
        )

    monkeypatch.setattr(demo, "toggle", broken)
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads")
        await pilot.press("x")
        assert not switch(lean, "ads")
        gate.set()
        await settle(pilot)
        assert switch(lean, "ads")
        assert shown(lean) == (
            "✗ Could not save: /home/demo/.claude/settings.json is read-only, "
            "so the atlas cannot change it. Check the file's permissions, then try again."
        )
        assert not lean.query(ToastHint)
        await pilot.press("z")
        await settle(pilot)
        assert switch(lean, "ads")


@pytest.mark.asyncio
async def test_x_on_a_source_group_turns_every_skill_from_it_on(lean, demo):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, selected_key=f"src:{MARKETING}")
        members = views.members_of(lean.data.insights, HOME, f"src:{MARKETING}")
        off = [s["name"] for s in members if not switch(lean, s["name"])]
        assert off
        await pilot.press("x")
        assert all(switch(lean, s["name"]) for s in members)
        await settle(pilot)
        assert shown(lean) == (
            f"Turned {len(off)} skills from {MARKETING} on. "
            "Restart Claude Code sessions to pick it up."
        )
        await pilot.press("z")
        await settle(pilot)
        assert [s["name"] for s in members if not disk(demo, s["name"])] == off


@pytest.mark.asyncio
async def test_x_with_marks_turns_skills_and_plugins_to_the_side_most_need(lean, demo):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        ins = lean.data.insights
        plugin = next(
            s
            for s in ins.skills
            if s["name"] == "brainstorming" and HOME in s["harnesses"] and s["status"] != "stale"
        )
        marked = {skill(lean, n)["path"] for n in ("ads", "cro", "analytics")} | {plugin["path"]}
        await start(lean, pilot, marked=marked)
        await pilot.press("x")
        ref = plugin["plugin_ref"]
        assert not switch(lean, "ads") and not switch(lean, "cro")
        await settle(pilot)
        settings = demo.data()["settings"][HOME]
        assert settings["enabledPlugins"][ref] is False
        assert shown(lean) == (
            "Turned 2 skills and 1 plugin off. Restart Claude Code sessions to pick it up."
        )


class SkillList(Rows):
    """Rows with the real list's refresh_visible, so a toggle can paint before it rebuilds."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.painted = 0

    def refresh_visible(self):
        self.painted += 1
        self.refresh()


@pytest.mark.asyncio
async def test_a_toggle_paints_its_rows_before_the_rebuild(lean, monkeypatch):
    monkeypatch.setattr(appmod, "SkillList", SkillList)
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads")
        lst = lean.query_one(SkillList)
        before, events = lean.data.insights, lst.data_events
        jobs.toggle(lean)
        jobs.toggle(lean)
        assert lst.painted == 2 and lean.data.insights is before
        assert switch(lean, "ads")
        await settle(pilot)
        assert lean.data.insights is not before and lst.data_events > events
        assert switch(lean, "ads")


@pytest.mark.asyncio
async def test_x_at_first_load_acts_on_the_cursor_row(prefs, demo, monkeypatch):
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setattr(jobs, "_later", lambda app, seconds, fn: None)
    app = AtlasApp(demo)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert app.state.selected is None and app.state.selected_key is None
        path, key = app.current()
        assert path is None and key == "src:acme-*"

        def on():
            ins = app.data.insights
            members = views.members_of(ins, app.state.harness, key)
            return [views.switch_state(ins, app.state.harness, m)["on"] for m in members]

        assert not all(on())
        await pilot.press("x")
        await settle(pilot)
        assert all(on())
        assert shown(app).startswith("Turned 1 skill from acme-* on.")


@pytest.mark.asyncio
async def test_one_switch_call_turns_a_skill_off_in_several_harnesses_with_one_undo(lean, demo):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads")
        jobs.set_switch(lean, [HOME, "codex"], ["ads"], False)
        assert not switch(lean, "ads")
        await settle(pilot)
        assert not disk(demo, "ads") and "ads" in demo.data()["settings"]["codex"]["off"]
        assert shown(lean) == (
            "Turned ads off in 2 harnesses. Restart agent sessions to pick it up."
        )
        await pilot.press("z")
        await settle(pilot)
        assert disk(demo, "ads") and "ads" not in demo.data()["settings"]["codex"]["off"]


@pytest.mark.asyncio
async def test_all_harnesses_and_project_skills_explain_why_there_is_no_switch(lean):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads", harness="all")
        await pilot.press("x")
        assert shown(lean) == "Pick a harness to switch skills. Press [ or ] to change it."
        await start(lean, pilot, harness="cursor")
        await pilot.press("x")
        assert shown(lean) == "Cursor has no per-skill switch."
        await start(lean, pilot, harness=HOME, selected=None, selected_key="prj:atlas-web")
        await pilot.press("x")
        assert "no switch" in shown(lean)


# Jobs


@pytest.mark.asyncio
async def test_u_runs_a_job_the_bar_fills_and_the_ticks_leave(lean, held, steps):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "cro")
        bar = lean.query_one(JobBar)
        await pilot.press("u")
        assert jobs.state_of(lean, "cro") == "queued"
        assert jobs.headline(lean) == "Updating 0 of 1…"
        await pilot.pause()
        assert bar.active and bar.tooltip == "Updating 0 of 1…"
        held.set()
        await settle(pilot)
        assert jobs.state_of(lean, "cro") == "done"
        assert jobs.headline(lean) == "Updated 1 of 1"
        text = shown(lean)
        assert text.startswith("Updated cro in ") and text.endswith(
            "s. Restart Claude Code sessions to pick it up."
        )
        rows = lean.query_one(Rows)
        assert rows.views[0]["items"] == {"cro": {"state": "queued"}}
        assert rows.views[-1]["done"] and bar.active and bar.fill == 1.0
        assert not views.is_outdated(lean.data.insights, skill(lean, "cro"))
        steps.run()
        await pilot.pause()
        assert jobs.current(lean) is None and rows.views[-1] is None
        assert jobs.state_of(lean, "cro") == "done"
        await pilot.wait_for_scheduled_animations()
        assert not bar.active
        steps.run()
        await pilot.pause()
        assert jobs.state_of(lean, "cro") is None and "cro" in jobs.flashes(lean)
        assert not steps


@pytest.mark.asyncio
async def test_update_all_skips_edits_and_names_the_failure(lean, held, steps):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        await pilot.press("U")
        view = jobs.current(lean)
        assert "seo-audit" not in view["items"] and "paywalls" in view["items"]
        assert len(view["items"]) == 8
        held.set()
        await settle(pilot)
        assert jobs.headline(lean) == "Updated 7 of 8"
        assert shown(lean) == (
            "✗ Updated 7, 1 failed: no SKILL.md in the download. Press u on the row to try again."
        )
        steps.run()
        steps.run()
        assert jobs.current(lean) is None
        assert jobs.state_of(lean, "paywalls") == "failed"
        assert jobs.error_of(lean, "paywalls") == "no SKILL.md in the download"
        await start(lean, pilot, marked={skill(lean, "seo-audit")["path"]})
        await pilot.press("u")
        assert shown(lean) == "All 1 have your edits. Update them one at a time."


@pytest.mark.asyncio
async def test_an_edited_skill_asks_before_its_edits_go(lean, held):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "seo-audit")
        await pilot.press("u")
        assert jobs.current(lean) is None and jobs.confirming(lean) == "seo-audit"
        assert shown(lean) == "! /seo-audit has changes you made. An update replaces them."
        assert lean.query_one(ToastHint).render().plain == "u Replace my edits"
        assert jobs.escape(lean) and jobs.confirming(lean) is None
        assert not jobs.escape(lean)
        await pilot.press("u")
        await pilot.press("u")
        assert jobs.current(lean)["items"] == {"seo-audit": {"state": "queued"}}
        held.set()
        await settle(pilot)


@pytest.mark.asyncio
async def test_click_replace_my_edits_starts_the_update(lean, held):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "seo-audit")
        await pilot.press("u")
        await pilot.click(ToastHint)
        assert jobs.current(lean) is not None and jobs.confirming(lean) is None
        held.set()
        await settle(pilot)
        assert jobs.state_of(lean, "seo-audit") == "done"


@pytest.mark.asyncio
async def test_a_confirmed_update_does_not_ask_again(lean, held):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        jobs.update(lean, ["seo-audit"], confirmed=True)
        assert jobs.confirming(lean) is None and not lean.query(ToastHint)
        assert jobs.current(lean)["items"] == {"seo-audit": {"state": "queued"}}
        held.set()
        await settle(pilot)
        assert jobs.state_of(lean, "seo-audit") == "done"


@pytest.mark.asyncio
async def test_the_confirm_ends_with_its_toast(lean, monkeypatch):
    monkeypatch.setattr(jobs, "CONFIRM", 0.05)
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "seo-audit")
        await pilot.press("u")
        await until(pilot, lambda: jobs.confirming(lean) is None)
        assert jobs.current(lean) is None


@pytest.mark.asyncio
async def test_one_job_at_a_time(lean, held):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "cro")
        await pilot.press("u")
        lean.set_state(selected=skill(lean, "pricing")["path"])
        await pilot.press("u")
        assert shown(lean) == "An update is already running."
        jobs.install(lean, "mattpocock/skills")
        assert shown(lean) == "Another job is still running."
        assert list(jobs.current(lean)["items"]) == ["cro"]
        held.set()
        await settle(pilot)


@pytest.mark.asyncio
async def test_a_job_that_cannot_start_or_goes_missing(lean, demo, monkeypatch):
    def busy(names):
        raise RuntimeError("another update is still running")

    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "cro")
        monkeypatch.setattr(demo, "update", busy)
        await pilot.press("u")
        await settle(pilot)
        assert shown(lean) == (
            "✗ Could not start: another update is still running. "
            "Check your network, then press u again."
        )
        assert jobs.current(lean) is None
        monkeypatch.undo()
        monkeypatch.setattr(jobs, "POLL", 0.01)
        monkeypatch.setattr(demo, "job", lambda job_id: None)
        await pilot.press("u")
        await settle(pilot)
        assert jobs.error_of(lean, "cro") == jobs.GONE
        assert shown(lean).startswith("✗ Updated 0, 1 failed: that job is gone.")


@pytest.mark.asyncio
async def test_errors_drop_backticks_and_python_reprs(lean, demo, monkeypatch):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "cro")
        monkeypatch.setattr(demo, "update", raises(OSError("A private repo needs `gh auth login`")))
        await pilot.press("u")
        await settle(pilot)
        assert shown(lean) == (
            "✗ Could not start: A private repo needs gh auth login. "
            "Check your network, then press u again."
        )
        monkeypatch.setattr(demo, "update", raises(KeyError("repo")))
        await pilot.press("u")
        await settle(pilot)
        assert shown(lean).startswith(
            "✗ Could not start: something in the request was missing (repo). "
        )


@pytest.mark.asyncio
async def test_install_one_available_skill_and_the_new_ones(lean, steps):
    async with lean.run_test(size=SIZE) as pilot:
        repo = "mattpocock/skills"
        key = f"a:{repo}:skills/triage-issue/SKILL.md"
        await start(lean, pilot, selected=None, selected_key=key)
        await pilot.press("i")
        await settle(pilot)
        assert lean.query_one(Rows).views[0]["kind"] == "install"
        assert shown(lean).startswith(f"Installed triage-issue from {repo} in ")
        assert any(s["name"] == "triage-issue" for s in lean.data.skills)
        await start(lean, pilot, selected_key=f"src:{repo}")
        await pilot.press("I")
        await settle(pilot)
        last = [v for v in lean.query_one(Rows).views if v][-1]
        assert sorted(last["items"]) == ["migrate-to-shoehorn", "obsidian-vault"]
        assert shown(lean).startswith(f"Installed 2 skills from {repo} in ")
        await pilot.press("I")
        assert shown(lean) == f"No new skills from {repo}."


@pytest.mark.asyncio
async def test_follow_tracks_a_job_the_core_already_started(lean, demo):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        view = demo.install("mattpocock/skills", ["skills/triage-issue/SKILL.md"])
        jobs.follow(lean, view, note=" Switched 2 skills.")
        assert jobs.current(lean)["kind"] == "install"
        await settle(pilot)
        assert jobs.state_of(lean, "triage-issue") == "done"
        text = shown(lean)
        assert text.startswith("Installed triage-issue in ")
        assert text.endswith("s. Switched 2 skills. Restart Claude Code sessions to pick it up.")


@pytest.mark.asyncio
async def test_a_taken_name_does_not_start_an_install(lean):
    async with lean.run_test(size=SIZE) as pilot:
        await start(
            lean, pilot, selected_key="a:mattpocock/skills:skills/engineering/grilling/SKILL.md"
        )
        await pilot.press("i")
        assert jobs.current(lean) is None
        assert shown(lean) == "This repo moved the folder of a skill you have. Update or relink it."


@pytest.mark.asyncio
async def test_check_again_forces_a_fresh_check(lean, monkeypatch):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        spy = Spy()
        monkeypatch.setattr(lean, "reload", spy)
        await pilot.press("ctrl+r")
        assert spy.calls == [(["updates"], ("refresh", True))]
        lean.data.loading.add("updates")
        jobs.check_again(lean)
        assert len(spy.calls) == 1


# Delete and undo


@pytest.mark.asyncio
async def test_delete_moves_to_the_trash_and_z_puts_it_back(lean):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads")
        path = skill(lean, "ads")["path"]
        lean.set_state(marked={path})
        jobs.delete(lean, ["ads"])
        await settle(pilot)
        assert lean.state.selected is None and lean.state.marked == frozenset()
        assert all(s["name"] != "ads" for s in lean.data.skills if s.get("store"))
        assert shown(lean) == "Moved ads to the Trash."
        await pilot.press("z")
        await settle(pilot)
        assert shown(lean) == "Put back 1 skill."
        assert "ads" in jobs.flashes(lean) and skill(lean, "ads")["path"] == path


@pytest.mark.asyncio
async def test_only_the_last_delete_stays_on_the_undo_stack(lean):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        jobs.delete(lean, ["ads"])
        await settle(pilot)
        jobs.delete(lean, ["cro", "pricing"])
        await settle(pilot)
        assert shown(lean) == "Moved 2 skills to the Trash."
        await pilot.press("z")
        await settle(pilot)
        assert shown(lean) == "Put back 2 skills."
        await pilot.press("z")
        await settle(pilot)
        assert shown(lean) == "Put back 2 skills."


@pytest.mark.asyncio
async def test_delete_and_undo_errors(lean, demo, monkeypatch):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        jobs.delete(lean, ["nope"])
        await settle(pilot)
        assert shown(lean) == (
            "✗ Could not delete: not a personal skill: nope. "
            "Check the folder's permissions, then press delete again."
        )
        jobs.delete(lean, ["ads"])
        await settle(pilot)
        monkeypatch.setattr(demo, "undo_delete", lambda: (_ for _ in ()).throw(ValueError("gone")))
        await pilot.press("z")
        await settle(pilot)
        assert shown(lean) == (
            "✗ Could not undo: gone. The skill is in the Trash. Move it back from there."
        )


# Toasts


@pytest.mark.parametrize(
    ("words", "long", "seconds"),
    [(3, False, 4.0), (3, True, 8.0), (20, False, 6.0), (30, True, 9.0)],
)
def test_toast_duration_follows_the_word_count(words, long, seconds):
    assert toasts.duration(" ".join(["word"] * words), long=long) == pytest.approx(seconds)


@pytest.mark.asyncio
async def test_a_toast_is_plain_text_sits_above_the_key_bar_and_replaces_the_last(lean):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        jobs.toast(lean, "First")
        await pilot.pause()
        jobs.toast(lean, "[b]Second[/b] has no markup", severity="warning")
        await pilot.pause()
        await pilot.pause()
        assert [t.text.plain for t in lean.query(AtlasToast)] == ["! [b]Second[/b] has no markup"]
        t = lean.query_one(AtlasToast)
        keybar = lean.query_one("#keybar")
        assert t.region.bottom == keybar.region.y and t.region.right == SIZE[0] - 1
        assert t.region.width <= toasts.MAX_WIDTH


@pytest.mark.asyncio
async def test_hover_pauses_a_toast_and_the_close_cell_dismisses_it(lean):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        t = jobs.toast(lean, "Hover me")
        await pilot.pause()
        await pilot.hover(AtlasToast)
        assert t._timer is None
        await pilot.hover("#header")
        assert t._timer is not None
        assert t.seconds == 4.0
        await pilot.click(ToastClose)
        await until(pilot, lambda: not lean.query(AtlasToast))


@pytest.mark.asyncio
async def test_a_long_toast_ends_its_third_line_with_an_ellipsis(lean):
    words = "Could not install from acme/one, acme/two, acme/three, acme/four, acme/five"
    text = f"{words}, acme/six, acme/seven. Check your network, then press i again."
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        t = jobs.toast(lean, text, action=("z", "Undo", lambda: None))
        await pilot.pause()
        lines = t.text.plain.split("\n")
        body = t.query_one(".toast--body")
        assert len(lines) == 3 and lines[2].endswith("…")
        assert body.tooltip == text and body.region.height == 3
        assert max(map(len, lines)) <= toasts.room(t._hint)
        short = jobs.toast(lean, "Short")
        await pilot.pause()
        assert short.full is None and short.query_one(".toast--body").tooltip is None


@pytest.mark.asyncio
async def test_a_toast_outlives_the_reader_with_the_time_it_had(lean, monkeypatch):
    monkeypatch.setattr(jobs, "_local_mac", lambda: True)
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        open_reader(lean, skill(lean, "ads")["path"])
        await settle(pilot)
        assert isinstance(lean.screen, ReaderScreen)
        await pilot.press("y")
        await settle(pilot)
        first = toasts.current(lean)
        assert first.screen is lean.screen and shown(lean) == "Copied the Markdown"
        await asyncio.sleep(0.2)
        await pilot.press("q")
        await settle(pilot)
        assert not isinstance(lean.screen, ReaderScreen)
        moved = toasts.current(lean)
        assert moved is not first and moved.screen is lean.screen
        assert shown(lean) == "Copied the Markdown"
        assert moved.styles.opacity == 1.0
        assert 0 < moved.seconds < first.seconds - 0.1


@pytest.mark.asyncio
async def test_a_profile_undo_toast_outlives_its_dialog(lean, demo):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        await profiles.open_profiles(lean)
        await settle(pilot)
        dialog = lean.screen
        await pilot.press("delete")
        await settle(pilot)
        assert shown(lean) == "Deleted the profile Writing mode."
        await pilot.press("escape")
        await settle(pilot)
        assert lean.screen is not dialog
        assert shown(lean) == "Deleted the profile Writing mode."
        assert toasts.current(lean).screen is lean.screen
        await pilot.click(ToastHint)
        await settle(pilot)
        assert shown(lean) == "Put back the profile Writing mode."
        assert "Writing mode" in [p["name"] for p in demo.profiles()["profiles"]]


@pytest.mark.asyncio
async def test_a_toast_times_out(lean):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        toasts.toast(lean, "Brief", seconds=0.05)
        await until(pilot, lambda: not lean.query(AtlasToast))


@pytest.mark.parametrize("level", ["none", "basic", "full"])
@pytest.mark.asyncio
async def test_toast_and_bar_motion_follow_the_animation_level(lean, level):
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        lean.animation_level = level
        t = jobs.toast(lean, "Hello")
        await pilot.pause()
        assert t.styles.opacity == (0.0 if level == "full" else 1.0) or level == "full"
        bar = lean.query_one(JobBar)
        bar.post_message(JobChanged({"items": {"a": {"state": "done"}}, "done": True}))
        await pilot.pause()
        if level != "full":
            assert bar.fill == 1.0
        bar.post_message(JobChanged(None))
        await pilot.pause()
        if level != "full":
            assert not bar.active
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        assert not bar.active and t.styles.opacity == 1.0
        body = t.query_one(".toast--body").region
        row = lean.screen._compositor.render_strips()[body.y].crop(body.x, body.right)
        assert {seg.style.bgcolor.name for seg in row if seg.style} == {
            theme.colors(lean)["atlas-surface-3"]
        }


def test_bar_fraction_and_headline():
    view = {
        "kind": "install",
        "items": {"a": {"state": "done"}, "b": {"state": "installing"}, "c": {"state": "failed"}},
    }
    assert fraction(view) == pytest.approx(2 / 3)
    assert headline(view) == "Installing 2 of 3…"
    assert headline({**view, "done": True}) == "Installed 1 of 3"
    assert fraction({"items": {}}) == 1.0


# Clipboard, file manager, and browser


@pytest.mark.asyncio
async def test_copy_uses_osc52_and_pbcopy_on_a_local_mac(lean, monkeypatch):
    monkeypatch.setattr(jobs, "_local_mac", lambda: True)
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads")
        await pilot.press("y")
        await settle(pilot)
        assert lean.copy_to_clipboard.calls == [("/ads",)]
        assert jobs._pbcopy.calls == [("/ads",)]
        assert shown(lean) == "Copied /ads"
        names = ("ads", "cro", "pricing", "copywriting", "launch", "emails")
        await start(lean, pilot, marked={skill(lean, n)["path"] for n in names})
        await pilot.press("y")
        await settle(pilot)
        text = lean.copy_to_clipboard.calls[-1][0]
        assert sorted(text.split()) == sorted(f"/{n}" for n in names)
        assert shown(lean).startswith("Copied 6 skills: /") and shown(lean).endswith("…")
        assert len(shown(lean)) == jobs.COPY_CELLS


@pytest.mark.asyncio
async def test_over_ssh_copy_does_not_claim_success_and_reveal_explains(lean, monkeypatch):
    monkeypatch.setenv("SSH_TTY", "/dev/ttys001")
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads")
        assert not jobs._local_mac()
        jobs.copy(lean, "/tmp/x", "the path")
        await settle(pilot)
        assert not jobs._pbcopy.calls
        assert shown(lean) == "Sent the path to your terminal's clipboard."
        await pilot.press("R")
        assert shown(lean) == "Reveal does not work over SSH: the folder is on the remote machine."
        await pilot.press("o")
        url = "https://github.com/" + skill(lean, "ads")["origin"]["source"]
        assert lean.copy_to_clipboard.calls[-1] == (url,)
        assert shown(lean) == f"Sent the GitHub link to your terminal's clipboard: {url}"
        assert not jobs.webbrowser.open.calls


@pytest.mark.asyncio
async def test_pbcopy_failure_says_could_not_copy(lean, monkeypatch):
    def broken(text):
        raise OSError("pbcopy is missing")

    monkeypatch.setattr(jobs, "_local_mac", lambda: True)
    monkeypatch.setattr(jobs, "_pbcopy", broken)
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot)
        jobs.copy(lean, "text", "the text")
        await settle(pilot)
        assert shown(lean) == "✗ Could not copy: pbcopy is missing."


def test_github_url_reads_the_marketplace_or_the_source(demo):
    by_name = {s["name"]: s for s in demo.data()["skills"] if s.get("store")}
    assert jobs.github_url(by_name["ads"]) == f"https://github.com/{MARKETING}"
    assert jobs.github_url({"origin": {"source": "owner/repo"}}) == ""
    assert jobs.github_url({"marketplace_source": {"url": "https://github.com/a/b.git"}}) == (
        "https://github.com/a/b"
    )


@pytest.mark.asyncio
async def test_reveal_and_github_open_locally(lean, demo, monkeypatch):
    spy = Spy()
    monkeypatch.setattr(demo, "reveal", spy)
    async with lean.run_test(size=SIZE) as pilot:
        await start(lean, pilot, "ads")
        await pilot.press("R")
        await settle(pilot)
        assert spy.calls == [(skill(lean, "ads")["path"],)]
        await pilot.press("o")
        await settle(pilot)
        url = "https://github.com/" + skill(lean, "ads")["origin"]["source"]
        assert jobs.webbrowser.open.calls == [(url,)]
        await start(lean, pilot, selected=None, selected_key=f"src:{MARKETING}")
        await pilot.press("o")
        await settle(pilot)
        assert jobs.webbrowser.open.calls[-1] == (f"https://github.com/{MARKETING}",)
        monkeypatch.setattr(jobs.webbrowser, "open", Spy(False))
        link = f"https://github.com/{MARKETING}"
        monkeypatch.setattr(jobs, "_local_mac", lambda: True)
        await pilot.press("o")
        await settle(pilot)
        assert jobs._pbcopy.calls[-1] == (link,)
        assert shown(lean) == f"Could not open a browser. Copied the link: {link}"
        monkeypatch.setattr(jobs, "_local_mac", lambda: False)
        await pilot.press("o")
        await settle(pilot)
        assert lean.copy_to_clipboard.calls[-1] == (link,)
        assert shown(lean) == (
            f"Could not open a browser. Sent the link to your terminal's clipboard: {link}"
        )
