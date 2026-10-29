import asyncio
import sys
import threading
import types
from datetime import datetime, timezone

import pytest
from textual.widgets import OptionList, Static

import skill_atlas.tui
from skill_atlas.core import views
from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui import app as app_module
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.messages import JobChanged
from skill_atlas.tui.screens import AtlasModal, CloseCell
from skill_atlas.tui.widgets import header
from skill_atlas.tui.widgets.header import (
    AtlasHeader,
    HarnessMenu,
    SourceErrors,
    open_harness_menu,
    show_source_errors,
)

NOW = datetime(2026, 10, 28, 9, tzinfo=timezone.utc)
WIDE, MID, NARROW, TINY = (180, 50), (120, 36), (80, 24), (60, 20)


class Atlas(DemoAtlas):
    """Demo data with parts of the scan or the update check replaced. `gate` holds the check."""

    def __init__(self, scan: dict | None = None, updates: dict | None = None):
        super().__init__(n=120, now=NOW)
        self.scan_patch = scan or {}
        self.updates_patch = updates or {}
        self.gate: threading.Event | None = None

    def data(self):
        return {**super().data(), **self.scan_patch}

    def updates(self, refresh=False):
        if self.gate is not None:
            self.gate.wait(5)
        return {**super().updates(refresh), **self.updates_patch}


class Region(Static, can_focus=True):
    """Stands in for the regions other builders own, so these tests check the header alone."""


@pytest.fixture(autouse=True)
def isolate(monkeypatch, prefs):
    for name in ("ViewStrip", "SkillList", "DetailPanel", "SidePanel", "BulkBar", "KeyBar"):
        monkeypatch.setattr(app_module, name, type(name, (Region,), {}))


@pytest.fixture
def calls(monkeypatch):
    """A fake jobs module; the list records each feature function it ran."""
    done: list[str] = []
    fake = types.ModuleType("skill_atlas.tui.jobs")
    fake.current = lambda app: None
    fake.check_again = lambda app: done.append("check_again")
    fake.update_all = lambda app: done.append("update_all")
    fake.toast = lambda app, text, **kw: None
    monkeypatch.setitem(sys.modules, "skill_atlas.tui.jobs", fake)
    monkeypatch.setattr(skill_atlas.tui, "jobs", fake, raising=False)
    return done


def row(app, y=0):
    return app.screen._compositor.render_strips()[y].text


def head(app):
    return app.query_one(AtlasHeader)


def tabs(app):
    return {t.harness: t for t in head(app)._tabs}


def shown(app):
    return [h for h, t in tabs(app).items() if t.display]


def cell(app, name):
    return head(app).piece(name)


def text(widget):
    return str(widget.render())


def outdated(app):
    return views.counts(app.data.insights, app.state.view_state())["updates"]


async def start(pilot):
    await settle(pilot)
    await pilot.pause()


@pytest.mark.asyncio
async def test_brand_tabs_and_the_more_cell_fit_each_width(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        ids = views.harness_choices(app.data.insights)
        assert ids[0] == "all" and app.state.harness == ids[1]
        top = row(app)
        assert "╱" in top and "Skill Atlas" in top and "All harnesses" in top
        assert not app.query_one("#brand").allow_select
        assert "Claude Code · personal" in top
        more = cell(app, "more")
        hidden = len(ids) - len(shown(app))
        assert more.display and hidden > 0 and f"{hidden} more ›" in top and "+" not in top
        assert more.tooltip == f"Show all {len(ids)} harnesses"
        for h in ids:
            if h not in shown(app):
                assert header.label_of(app, h) not in top

        await pilot.resize_terminal(*NARROW)
        await pilot.pause()
        top = row(app)
        assert "╱" in top and "Skill Atlas" not in top
        assert shown(app) == [app.state.harness] and more.display
        assert f"{ids.index(app.state.harness) + 1} of {len(ids)} ›" in top

        await pilot.resize_terminal(*TINY)
        await pilot.pause()
        top = row(app)
        assert "Claude Code · personal" in top and "Update all" in top
        assert cell(app, "all").region.right <= TINY[0] - 1

        await pilot.resize_terminal(*WIDE)
        await pilot.pause()
        assert len(shown(app)) > 3 and "Check again" in row(app)


@pytest.mark.asyncio
async def test_mouse_hover_press_and_click_a_harness_tab(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        work = tabs(app)["claude-code:work"]
        colors = app.current_theme.variables
        assert work.styles.background.hex.lower() != colors["atlas-surface-2"].lower()
        await pilot.hover(work)
        await pilot.pause()
        assert work.mouse_hover
        assert work.styles.background.hex.lower() == colors["atlas-surface-2"].lower()
        await pilot.mouse_down(work)
        assert work.has_class("-pressed")
        await pilot.mouse_up(work)
        assert not work.has_class("-pressed")

        await pilot.click(work, button=3)
        assert app.state.harness == "claude-code:personal"
        await pilot.click(work)
        await pilot.pause()
        assert app.state.harness == "claude-code:work"
        assert work.has_class("-active")
        assert sum(t.has_class("-active") for t in tabs(app).values()) == 1
        active = app.current_theme.variables["atlas-surface-3"].lower()
        assert work.styles.background.hex.lower() == active
        assert work.styles.color.hex.lower() == colors["atlas-text"].lower()


@pytest.mark.asyncio
async def test_brackets_step_through_harnesses_and_keep_the_active_tab_shown(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        ids = views.harness_choices(app.data.insights)
        i = ids.index(app.state.harness)
        for step in range(len(ids)):
            await pilot.press("right_square_bracket")
            want = ids[(i + step + 1) % len(ids)]
            assert app.state.harness == want
            assert want in shown(app) and tabs(app)[want].has_class("-active")
            assert header.label_of(app, want) in row(app)
        await pilot.press("left_square_bracket")
        assert app.state.harness == ids[i - 1]


@pytest.mark.asyncio
async def test_the_more_cell_opens_a_harness_menu_for_the_mouse(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        ids = views.harness_choices(app.data.insights)
        await pilot.click("#more")
        await pilot.pause()
        menu = app.screen
        assert isinstance(menu, HarnessMenu)
        options = menu.query_one(OptionList)
        assert options.option_count == len(ids)
        assert options.highlighted == ids.index(app.state.harness)
        more = cell(app, "more").region
        assert options.region.y == more.bottom
        target = ids.index("gemini-cli")
        await pilot.click(OptionList, offset=(2, 1 + target))
        await pilot.pause()
        assert not isinstance(app.screen, AtlasModal)
        assert app.state.harness == "gemini-cli" and "gemini-cli" in shown(app)

        await pilot.click("#more")
        await pilot.pause()
        await pilot.click(offset=(5, MID[1] - 3))
        await pilot.pause()
        assert not isinstance(app.screen, AtlasModal) and app.state.harness == "gemini-cli"


@pytest.mark.asyncio
async def test_the_harness_menu_works_from_the_keyboard(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=NARROW) as pilot:
        await start(pilot)
        ids = views.harness_choices(app.data.insights)
        open_harness_menu(app)
        await pilot.pause()
        assert isinstance(app.screen, HarnessMenu)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, AtlasModal)
        open_harness_menu(app)
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert app.state.harness == ids[ids.index("claude-code:personal") + 2]
        assert app.state.harness in shown(app) and cell(app, "more").display


@pytest.mark.asyncio
async def test_meta_notes_show_in_tab_tooltips_and_in_the_menu(calls):
    app = AtlasApp(Atlas(scan={"bundled_skills_disabled": True}))
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        t = tabs(app)
        assert t["all"].tooltip == "Pick a harness to switch skills"
        assert t["claude-code:personal"].tooltip == (
            "Built-ins off; writes ~/.claude/settings.json"
        )
        assert t["codex"].tooltip == "Writes ~/.codex/config.toml"
        assert t["cursor"].tooltip == "Cursor has no per-skill switch"
        open_harness_menu(app)
        await pilot.pause()
        prompts = [str(o.prompt) for o in app.screen.query_one(OptionList).options]
        assert any("Cursor has no per-skill switch" in p for p in prompts)
        assert any(p.startswith("All harnesses") and "pick a harness" in p for p in prompts)


@pytest.mark.asyncio
async def test_update_all_runs_on_a_left_click_only(calls):
    app = AtlasApp(Atlas(updates={"errors": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        n = outdated(app)
        assert n > 0
        assert f"↑ {views.plural(n, 'update')}" in row(app) and "Update all" in row(app)
        await pilot.click("#all", button=3)
        assert calls == []
        await pilot.mouse_down("#all")
        assert cell(app, "all").has_class("-pressed")
        await pilot.mouse_up("#all")
        await pilot.click("#all")
        await pilot.pause()
        assert calls == ["update_all"]


@pytest.mark.asyncio
async def test_up_to_date_is_a_check_mark_that_checks_again(calls):
    app = AtlasApp(Atlas(updates={"skills": {}, "errors": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        check = cell(app, "check")
        assert "✓ Up to date" in row(app) and not cell(app, "all").display
        assert check.tooltip in ("Check again", "Check again (ctrl+r)")
        await pilot.hover(check)
        await pilot.pause()
        surface = app.current_theme.variables["atlas-surface-2"].lower()
        assert check.styles.background.hex.lower() == surface
        await pilot.click(check)
        await pilot.pause()
        assert calls == ["check_again"]


@pytest.mark.asyncio
async def test_the_new_chip_opens_the_new_view_and_hides_there(calls):
    app = AtlasApp(Atlas(updates={"errors": {}}))
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        fresh = views.new_total(app.data.insights)
        chip = cell(app, "new")
        assert fresh and chip.display and f"{fresh} new" in text(chip)
        assert chip.tooltip == f"Show the {views.plural(fresh, 'new skill')}"
        await pilot.click(chip)
        await pilot.pause()
        assert app.state.view == "new" and not chip.display
        await pilot.press("1")
        await pilot.pause()
        assert chip.display


@pytest.mark.asyncio
async def test_unchecked_sources_show_the_errors_and_check_again(calls):
    errors = {"acme/skills": "could not read acme/skills from GitHub: GitHub did not answer"}
    app = AtlasApp(Atlas(updates={"errors": errors}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        warn = cell(app, "warn")
        assert warn.display and "1 unchecked" in text(warn)
        assert warn.tooltip == errors["acme/skills"]
        await pilot.click(warn)
        await pilot.pause()
        popup = app.screen
        assert isinstance(popup, SourceErrors)
        body = " ".join(str(s.render()) for s in popup.query(Static))
        assert "Could not check 1 source" in body and "acme/skills" in body
        await pilot.click("#again")
        await pilot.pause()
        assert not isinstance(app.screen, AtlasModal) and calls == ["check_again"]

        await pilot.click(warn)
        await pilot.pause()
        await pilot.click(CloseCell)
        await pilot.pause()
        assert not isinstance(app.screen, AtlasModal) and calls == ["check_again"]

        show_source_errors(app)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert calls == ["check_again", "check_again"]


@pytest.mark.asyncio
async def test_checking_waits_then_holds_and_ignores_clicks(calls, monkeypatch):
    monkeypatch.setattr(header, "SHOW_AFTER", 0.05)
    monkeypatch.setattr(header, "SHOW_FOR", 1.0)
    atlas = Atlas(updates={"skills": {}, "errors": {}})
    atlas.gate = threading.Event()
    app = AtlasApp(atlas)
    async with app.run_test(size=MID) as pilot:
        for _ in range(50):
            await pilot.pause(0.02)
            if app.data.scan is not None:
                break
        assert not cell(app, "check").display
        await pilot.pause(0.2)
        check = cell(app, "check")
        assert check.display and "Checking…" in text(check) and check.has_class("-idle")
        await pilot.click(check)
        assert calls == []
        atlas.gate.set()
        await settle(pilot)
        assert "updates" not in app.data.loading and "Checking…" in text(check)
        await pilot.pause(1.1)
        assert "Up to date" in text(check) and not check.has_class("-idle")


@pytest.mark.asyncio
async def test_a_fast_check_never_flashes_and_a_recheck_says_so(calls, monkeypatch):
    shows: list[bool] = []
    real = AtlasHeader._show_checking
    monkeypatch.setattr(AtlasHeader, "_show_checking", lambda h: shows.append(True) or real(h))
    app = AtlasApp(Atlas(updates={"skills": {}, "errors": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        assert shows == [] and "✓ Up to date" in text(cell(app, "check"))
        app.reload(["updates"], refresh=True)
        await settle(pilot)
        assert shows == [] and "Checked just now" in text(cell(app, "check"))
        head(app)._just_until = 0
        head(app).draw()
        assert "✓ Up to date" in text(cell(app, "check"))


@pytest.mark.asyncio
async def test_a_recheck_locks_the_check_cell_as_its_load_starts(calls):
    atlas = Atlas(updates={"skills": {}, "errors": {}})
    app = AtlasApp(atlas)
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        check = cell(app, "check")
        assert not check.has_class("-idle")
        atlas.gate = threading.Event()
        app.reload(["updates"], refresh=True)
        await pilot.pause(0.05)
        assert "updates" in app.data.loading and check.has_class("-idle")
        assert "✓ Up to date" in text(check)
        await pilot.click(check)
        assert calls == []
        atlas.gate.set()
        await settle(pilot)
        assert not check.has_class("-idle")


@pytest.mark.asyncio
async def test_a_job_replaces_the_cluster_and_the_tabs_stay_put(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        place = [(t.region, t.display) for t in head(app)._tabs]
        cluster = app.query_one("#cluster").region

        def steady():
            assert [(t.region, t.display) for t in head(app)._tabs] == place
            assert app.query_one("#cluster").region == cluster

        items = {f"s{i}": {"state": "done" if i < 3 else "queued"} for i in range(8)}
        app.broadcast(lambda: JobChanged({"kind": "update", "done": False, "items": items}))
        await pilot.pause()
        job = cell(app, "job")
        assert job.display and "Updating 3 of 8…" in text(job)
        assert not any(cell(app, p).display for p in ("new", "count", "warn", "all", "check"))
        steady()
        if app.animation_level == "full":
            first = text(job)
            await pilot.pause(0.25)
            assert text(job) != first and text(job)[2:] == first[2:]

        items = {f"s{i}": {"state": "done"} for i in range(8)} | {"s7": {"state": "failed"}}
        app.broadcast(lambda: JobChanged({"kind": "install", "done": True, "items": items}))
        await pilot.pause()
        assert "✗ Installed 7 of 8" in text(job)
        steady()

        app.broadcast(lambda: JobChanged(None))
        await pilot.pause()
        assert not job.display and cell(app, "all").display
        steady()

        head(app)._checking = True
        head(app).draw()
        await pilot.pause()
        assert "Checking…" in text(cell(app, "check"))
        steady()


@pytest.mark.asyncio
async def test_the_cluster_waits_for_the_first_check_and_hides_when_read_only(calls):
    atlas = Atlas()
    atlas.gate = threading.Event()
    app = AtlasApp(atlas)
    async with app.run_test(size=MID) as pilot:
        for _ in range(50):
            await pilot.pause(0.02)
            if app.data.scan is not None:
                break
        names = ("new", "count", "warn", "all", "check", "job")
        assert not any(cell(app, p).display for p in names)
        atlas.gate.set()
        await settle(pilot)
        assert cell(app, "all").display
        app.data.insights.writable = False
        head(app).draw()
        assert not any(cell(app, p).display for p in names)


@pytest.mark.asyncio
async def test_a_skeleton_shows_until_the_scan_names_the_harnesses(calls, monkeypatch):
    gate = threading.Event()
    atlas = Atlas()
    real = atlas.data
    monkeypatch.setattr(atlas, "data", lambda: gate.wait(5) and real())
    app = AtlasApp(atlas)
    async with app.run_test(size=MID) as pilot:
        await pilot.pause()
        assert app.query_one("#skeleton").display and not head(app)._tabs
        assert "Skill Atlas" in row(app)
        gate.set()
        await settle(pilot)
        assert not app.query_one("#skeleton").display and head(app)._tabs


@pytest.mark.asyncio
async def test_one_harness_has_no_all_tab_and_none_shows_no_tabs(calls):
    one = {"harnesses": {"codex": {**DemoAtlas(n=1).data()["harnesses"]["codex"]}}}
    app = AtlasApp(Atlas(scan=one))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        assert shown(app) == ["codex"] and "All harnesses" not in row(app)
        assert not cell(app, "more").display

    app = AtlasApp(Atlas(scan={"harnesses": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        assert head(app)._tabs == [] and not cell(app, "more").display
        assert not app.query_one("#skeleton").display


@pytest.mark.asyncio
async def test_the_stale_band_asks_for_a_restart(calls):
    app = AtlasApp(Atlas(scan={"server": {"build": "demo", "stale": True}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        band = app.query_one("#stale", Static)
        assert band.display and head(app).size.height == 2
        assert "Skill Atlas changed on disk. Quit and start it again." in row(app, 1)


@pytest.mark.asyncio
async def test_no_color_keeps_the_surface_step_and_never_reverses(calls, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        surface = app.current_theme.variables["atlas-surface-3"].lower()
        for h, tab in tabs(app).items():
            assert not tab.styles.text_style.reverse
            assert (tab.styles.background.hex.lower() == surface) == (h == app.state.harness)


@pytest.mark.asyncio
async def test_the_update_count_opens_the_updates_view(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        count = cell(app, "count")
        n = outdated(app)
        assert count.tooltip == f"Show the {views.plural(n, 'update')}"
        await pilot.hover(count)
        await pilot.pause()
        surface = app.current_theme.variables["atlas-surface-2"].lower()
        assert count.styles.background.hex.lower() == surface
        await pilot.click(count)
        await pilot.pause()
        assert app.state.view == "updates"


@pytest.mark.asyncio
async def test_a_short_cluster_leaves_room_for_more_tabs(calls):
    app = AtlasApp(Atlas(updates={"skills": {}, "errors": {}, "available": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        cluster = app.query_one("#cluster")
        assert "✓ Up to date" in row(app) and cluster.size.width == len(" ✓ Up to date ")
        place = [t.display for t in head(app)._tabs]
        assert sum(place) >= 3
        head(app)._checking = True
        head(app).draw()
        await pilot.pause()
        assert cluster.size.width == len(" ✓ Up to date ")
        assert [t.display for t in head(app)._tabs] == place


@pytest.mark.asyncio
async def test_a_failed_scan_drops_the_tab_skeleton(calls):
    atlas = Atlas()

    def broken():
        raise OSError("scan broke")

    atlas.data = broken
    app = AtlasApp(atlas)
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        assert "scan" in app.data.errors
        assert not app.query_one("#skeleton").display


def test_glyphs_are_one_cell_wide():
    from rich.cells import cell_len

    for glyph in ("╱", "✓", "✗", "↑", "!", "+", "…", *header.SPINNER):
        assert cell_len(glyph) == 1


@pytest.mark.asyncio
async def test_the_spinner_stops_when_nothing_is_busy(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        spinner = head(app)._spinner
        assert spinner is not None and not spinner._active.is_set()
        items = {"a": {"state": "queued"}}
        app.broadcast(lambda: JobChanged({"done": False, "items": items}))
        await pilot.pause()
        assert spinner._active.is_set() == (app.animation_level == "full")
        app.broadcast(lambda: JobChanged(None))
        await pilot.pause()
        await asyncio.sleep(0)
        assert not spinner._active.is_set()
