import importlib
import sys
import types
from datetime import datetime, timezone

import pytest
from textual.widgets import Static

from skill_atlas.core import views
from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.messages import LoadStarted
from skill_atlas.tui.widgets import bulkbar
from skill_atlas.tui.widgets.bulkbar import BulkBar, MoreMenu
from skill_atlas.tui.widgets.skill_list import SkillList
from skill_atlas.tui.widgets.viewstrip import ViewStrip

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
WIDE, MID, NARROW = (180, 50), (120, 36), (80, 24)
HARNESS = "claude-code:personal"


def find(app, text, row=None):
    """The screen offset of the first cell of `text`, read from what the screen shows."""
    for y, strip in enumerate(app.screen._compositor.render_strips()):
        x = strip.text.find(text)
        if x >= 0 and row in (None, y):
            return (x, y)
    raise AssertionError(f"{text!r} is not on the screen")


def on_screen(app, text):
    return any(text in s.text for s in app.screen._compositor.render_strips())


@pytest.fixture
def app(prefs, monkeypatch):
    """The app over fixed demo data. The panel regions are stubs; this file tests the bar."""
    monkeypatch.setattr("skill_atlas.tui.app.DetailPanel", Static)
    monkeypatch.setattr("skill_atlas.tui.app.SidePanel", Static)
    return AtlasApp(DemoAtlas(now=NOW))


@pytest.fixture
def calls(monkeypatch):
    """Replace the functions the bar calls in other modules, and record each call."""
    seen: list[tuple] = []

    def stub(name, *funcs):
        full = f"skill_atlas.tui.{name}"
        try:
            module = importlib.import_module(full)
        except ModuleNotFoundError:
            module = types.ModuleType(full)
            monkeypatch.setitem(sys.modules, full, module)
        for func in funcs:

            def record(app, *args, _f=func, **kw):
                seen.append((_f, *args, *(kw.items())))

            monkeypatch.setattr(module, func, record, raising=False)

    stub("jobs", "switch_marks", "update", "copy_prompt")
    stub("screens.link", "open_link")
    stub("screens.profiles", "save_profile")
    stub("screens.confirm", "confirm_delete")
    return seen


def mixed(app, harness=HARNESS):
    """Paths of 3 skills that are on, 2 that are off, 2 with updates, and 1 plugin skill."""
    ins = app.data.insights
    own = [s for s in ins.skills if views.live(harness, s) and s.get("store")]
    on = [s for s in own if views.switch_state(ins, harness, s)["on"]]
    off = [s for s in own if not views.switch_state(ins, harness, s)["on"]]
    out = [s for s in own if views.is_outdated(ins, s)]
    plug = [s for s in ins.skills if s.get("scope") == "plugin" and s.get("status") != "stale"]
    return frozenset(s["path"] for s in on[:3] + off[:2] + out[:2] + plug[:1])


def plan_of(app):
    ins = app.data.insights
    marked = [s for s in ins.skills if s["path"] in app.state.marked]
    return views.bulk_plan(ins, app.state.harness, marked)


async def start(pilot, marks=None, **state):
    await settle(pilot)
    app = pilot.app
    if state:
        app.set_state(**state)
    app.set_state(marked=marks if marks is not None else mixed(app, app.state.harness))
    await settle(pilot)
    return app.query_one(BulkBar)


@pytest.mark.asyncio
async def test_the_bar_takes_the_view_strip_row_while_marks_exist(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        bar, strip = app.query_one(BulkBar), app.query_one(ViewStrip)
        assert not bar.display and strip.display
        await start(pilot)
        assert bar.display and not strip.display
        assert bar.region.y == 1 and bar.region.height == 1
        n = len(app.state.marked)
        assert find(app, f"{n} skills selected", row=1)
        assert find(app, "◈", row=1)[0] == 1
        app.set_state(marked=frozenset())
        await settle(pilot)
        assert not bar.display and strip.display


@pytest.mark.asyncio
async def test_each_action_shows_the_count_from_the_plan(app):
    async with app.run_test(size=WIDE) as pilot:
        bar = await start(pilot)
        plan = plan_of(app)
        model = bar.model
        assert model is not None
        got = {a.id: a.count for a in model.actions}
        assert got["on"] == len(plan["on"]["skills"]) + len(plan["on"]["plugins"])
        assert got["off"] == len(plan["off"]["skills"]) + len(plan["off"]["plugins"])
        assert got["update"] == len(plan["update"]) > 0
        assert got["link"] == len(plan["link"])
        assert got["delete"] == len(plan["delete"]) > 0
        assert got["copy"] is None
        for label in ("Turn on", "Turn off", "Update", "Copy as prompt", "Delete…", "Clear"):
            assert find(app, label, row=1)
        assert find(app, f"Update {got['update']}", row=1)
        assert find(app, f"Delete… {got['delete']}", row=1)


@pytest.mark.asyncio
async def test_actions_that_do_not_apply_say_why(app):
    async with app.run_test(size=WIDE) as pilot:
        bar = await start(pilot, harness="all")
        model = bar.model
        assert model.action("on").reason == "Pick a harness to switch skills."
        assert model.action("off").reason == "Pick a harness to switch skills."
        assert model.action("delete").enabled
        app.set_state(harness="cursor")
        await settle(pilot)
        reason = bar.model.action("on").reason
        assert reason == "Cursor has no per-skill switch."
        assert bar.model.action("delete").reason.startswith(reason)
        app.set_state(harness=HARNESS)
        await settle(pilot)
        ins = app.data.insights
        on = [
            s["path"]
            for s in ins.skills
            if views.live(HARNESS, s) and views.switch_state(ins, HARNESS, s)["on"]
        ]
        app.set_state(marked=frozenset(on[:2]))
        await settle(pilot)
        assert bar.model.action("on").reason == "The marked skills are already on."
        assert bar.model.action("off").enabled


@pytest.mark.asyncio
async def test_marks_that_the_filters_hide_are_counted(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        app.set_state(query="acme")
        await settle(pilot)
        bar = app.query_one(BulkBar)
        hidden = bar.model.hidden
        assert hidden > 0
        assert find(app, f"{hidden} hidden by filters", row=1)


@pytest.mark.asyncio
async def test_mouse_runs_each_action(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        plan = plan_of(app)
        focused = app.focused
        await pilot.click(offset=find(app, "Turn off", row=1))
        await pilot.click(offset=find(app, "Turn on", row=1))
        await pilot.click(offset=find(app, "Update", row=1))
        await pilot.click(offset=find(app, "Copy as prompt", row=1))
        await pilot.click(offset=find(app, "Delete…", row=1))
        await settle(pilot)
        assert app.focused is focused
        assert calls == [
            ("switch_marks", False),
            ("switch_marks", True),
            ("update", [views.lock_name(s) for s in plan["update"]]),
            ("copy_prompt",),
            ("confirm_delete", [s["path"] for s in plan["delete"]]),
        ]


@pytest.mark.asyncio
async def test_hover_on_a_disabled_action_says_why(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        bar = await start(pilot, harness="all")
        x, y = find(app, "Turn on", row=1)
        await pilot.hover(offset=(x, y))
        assert bar.tooltip == "Pick a harness to switch skills."
        await pilot.click(offset=(x, y))
        await settle(pilot)
        assert not calls
        await pilot.hover(offset=find(app, "Delete…", row=1))
        assert bar.tooltip.startswith("Move ") and bar.tooltip.endswith(" to the Trash.")


@pytest.mark.asyncio
async def test_the_mark_cell_marks_all_shown_then_clears_them(app):
    async with app.run_test(size=WIDE) as pilot:
        bar = await start(pilot)
        shown = {s["path"] for s in views.visible_skills(app.data.insights, app.state.view_state())}
        await pilot.hover(offset=(1, 1))
        assert bar.tooltip == f"Select all {len(shown)} shown"
        await pilot.click(offset=(1, 1))
        await settle(pilot)
        assert shown <= app.state.marked
        assert find(app, "◆", row=1)[0] == 1
        await pilot.click(offset=(1, 1))
        await settle(pilot)
        assert not app.state.marked & shown
        assert not bar.display


@pytest.mark.asyncio
async def test_clear_by_click_and_by_esc(app):
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        await pilot.click(offset=find(app, "Clear", row=1))
        await settle(pilot)
        assert not app.state.marked
        await start(pilot)
        await pilot.press("escape")
        await settle(pilot)
        assert not app.state.marked
        assert app.focused is app.query_one(SkillList)


@pytest.mark.asyncio
async def test_keys_move_between_actions_and_run_one(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        bar = await start(pilot, harness="all")
        await pilot.press("shift+tab")
        assert app.focused is bar
        assert bar._cursor == "update"  # Turn on and Turn off are disabled in All
        await pilot.press("right")
        assert bar._cursor == "link" if bar.model.action("link").enabled else "copy"
        await pilot.press("left", "left")
        assert bar._cursor == "update"
        await pilot.press("end")
        assert bar._cursor == "clear"
        await pilot.press("home", "enter")
        await settle(pilot)
        assert [c[0] for c in calls] == ["update"]
        await pilot.press("escape")
        await settle(pilot)
        assert not app.state.marked
        assert app.focused is app.query_one(SkillList)


@pytest.mark.asyncio
async def test_tab_from_the_list_reaches_the_bar_only_while_marking(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        bulkbar.focus_bar(app)
        assert app.focused is not app.query_one(BulkBar)
        bar = await start(pilot)
        app.query_one(SkillList).focus()
        bulkbar.focus_bar(app)
        await pilot.pause()
        assert app.focused is bar


@pytest.mark.asyncio
async def test_tab_without_marks_goes_to_the_panel_with_no_motion(prefs):
    app = AtlasApp(DemoAtlas(now=NOW))
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.query_one(SkillList).focus()
        bulkbar.focus_bar(app)
        await pilot.pause()
        pane = app.query_one("#detail-pane")
        assert app.focused is not None and pane in app.focused.ancestors
        assert not any(
            app.animator.is_being_animated(w, attr)
            for w in (pane, *pane.walk_children())
            for attr in ("scroll_x", "scroll_y")
        )


@pytest.mark.asyncio
async def test_update_says_checking_while_the_update_check_loads(app):
    async with app.run_test(size=WIDE) as pilot:
        bar = await start(pilot)
        app.data.put("updates", None)
        app.data.loading.add("updates")
        bar.post_message(LoadStarted("updates"))
        await settle(pilot)
        assert bar.model.action("update").reason == "Checking for updates…"


@pytest.mark.asyncio
async def test_narrow_bar_folds_actions_into_more_and_keeps_delete(app, calls):
    async with app.run_test(size=NARROW) as pilot:
        bar = await start(pilot)
        assert find(app, "⋯ More", row=1)
        assert find(app, "Delete…", row=1)
        assert not on_screen(app, "Link to GitHub…")
        folded = [a.id for a in bar.folded()]
        assert "link" in folded and "delete" not in folded
        await pilot.click(offset=find(app, "More", row=1))
        await settle(pilot)
        assert isinstance(app.screen, MoreMenu)
        await pilot.click(offset=find(app, "Link to GitHub…"))
        await settle(pilot)
        assert not isinstance(app.screen, MoreMenu)
        plan = plan_of(app)
        if plan["link"]:
            assert ("open_link", [s["dir_name"] for s in plan["link"]]) in calls


@pytest.mark.asyncio
async def test_more_menu_by_keys(app, calls):
    async with app.run_test(size=NARROW) as pilot:
        bar = await start(pilot)
        bar.focus()
        await pilot.press("end", "left")
        assert bar._cursor == "more"
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, MoreMenu)
        await pilot.press("escape")
        await settle(pilot)
        assert not isinstance(app.screen, MoreMenu) and app.state.marked
        assert app.focused is bar
        await pilot.press("enter")
        await settle(pilot)
        items = app.screen.query_one("MoreList").items
        target = next(i for i, a in enumerate(items) if a.id == "copy")
        live = [i for i, a in enumerate(items) if a.enabled]
        await pilot.press(*["down"] * live.index(target), "enter")
        await settle(pilot)
        assert [c[0] for c in calls] == ["copy_prompt"]


@pytest.mark.asyncio
async def test_the_bar_appears_at_once_with_no_motion(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        bar = app.query_one(BulkBar)
        app.set_state(marked=mixed(app))
        bar._sync()  # as StateChanged does, without waiting for the message
        assert bar.styles.opacity == 1.0
        assert not app.animator.is_being_animated(bar.styles, "opacity")


@pytest.mark.asyncio
async def test_narrow_bar_folds_disabled_actions_first(app):
    async with app.run_test(size=NARROW) as pilot:
        bar = await start(pilot, harness="all")
        fit = bar.fit
        in_bar = [a for a in bar.model.actions if a.id not in fit.folded and a.id != "delete"]
        folded = [a for a in bar.model.actions if a.id in fit.folded]
        assert folded and any(not a.enabled for a in folded)
        if any(a.enabled for a in folded):
            assert all(a.enabled for a in in_bar)
        assert not on_screen(app, "Turn on")
        assert find(app, "Update", row=1)


@pytest.mark.asyncio
async def test_palette_functions_run_or_say_why(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot, harness="all")
        await bulkbar.turn_on(app)
        assert not calls
        await settle(pilot)
        assert on_screen(app, "Pick a harness to switch skills.")
        await bulkbar.copy_prompt(app)
        await bulkbar.save_profile(app)
        assert [c[0] for c in calls] == ["copy_prompt", "save_profile"]
        bulkbar.clear(app)
        assert not app.state.marked


@pytest.mark.asyncio
async def test_a_missing_module_gives_a_warning_not_a_crash(app, monkeypatch):
    monkeypatch.setitem(sys.modules, "skill_atlas.tui.screens.link", None)
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        await bulkbar.link(app)
        await settle(pilot)
        assert app.is_running
        assert on_screen(app, "This action does not work yet.")
