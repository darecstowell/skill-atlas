import asyncio
import itertools
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
from skill_atlas.tui import keys
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
PIECES = ("check", "warn", "updates", "job")


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


def cell(app, name):
    return head(app).piece(name)


def chip(app):
    return cell(app, "harness")


def text(widget):
    return str(widget.render())


def outdated(app):
    return views.counts(app.data.insights, app.state.view_state())["updates"]


def link(app):
    return f"↑ {views.plural(outdated(app), 'update')}"


def key_for(action):
    return next(k.show for k in keys.KEYS if k.action == action and k.show)


def tint(widget) -> float:
    return widget.styles.background_tint.a


async def start(pilot):
    await settle(pilot)
    await pilot.pause()


# The harness chip


@pytest.mark.asyncio
async def test_the_harness_chip_and_its_menu_glyph_show_at_every_width(calls):
    app = AtlasApp(Atlas(updates={"errors": {"acme/skills": "GitHub did not answer"}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        ids = views.harness_choices(app.data.insights)
        assert ids[0] == "all" and app.state.harness == ids[1]
        top = row(app)
        assert "╱" in top and "Skill Atlas" in top
        assert not app.query_one("#brand").allow_select
        assert "Claude Code · personal ▾" in top and text(chip(app)).endswith(" ▾")
        for h in ids:
            if h != app.state.harness:
                assert header.label_of(app, h) not in top
        assert "more" not in top and "›" not in top

        for size in (WIDE, NARROW, TINY):
            await pilot.resize_terminal(*size)
            await pilot.pause()
            top = row(app)
            assert ("Skill Atlas" in top) == (size[0] >= header.NARROW)
            assert "Claude Code · personal ▾" in top, size
            assert f"↑ {outdated(app)}" in top and "! 1" in top, size
            assert ("! 1 not checked" in top) == (size[0] > TINY[0]), size
            assert chip(app).region.right < cell(app, "warn").region.x
            assert cell(app, "warn").region.right < cell(app, "updates").region.x
            assert cell(app, "updates").region.right <= size[0] - 1


@pytest.mark.asyncio
async def test_a_long_harness_name_is_cut_and_the_cluster_keeps_its_pieces(calls):
    long = "Claude Code · a very long profile name for this machine"
    harnesses = DemoAtlas(n=1).data()["harnesses"]
    harnesses["claude-code:personal"] = {**harnesses["claude-code:personal"], "label": long}
    app = AtlasApp(Atlas(scan={"harnesses": harnesses}, updates={"errors": {"a": "x"}}))
    async with app.run_test(size=TINY) as pilot:
        await start(pilot)
        assert text(chip(app)).endswith("… ▾") and long not in row(app)
        assert chip(app).size.width >= header.CHIP_MIN
        assert "! 1" in row(app) and f"↑ {outdated(app)}" in row(app)
        await pilot.resize_terminal(*WIDE)
        await pilot.pause()
        assert f"{long} ▾" in row(app)


@pytest.mark.asyncio
async def test_mouse_hover_press_and_click_the_chip_opens_the_harness_menu(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        ids = views.harness_choices(app.data.insights)
        c = chip(app)
        surface = app.current_theme.variables["atlas-surface-3"].lower()
        assert c.styles.background.hex.lower() == surface and tint(c) == 0
        await pilot.hover(c)
        await pilot.pause()
        assert c.mouse_hover and tint(c) > 0
        await pilot.mouse_down(c)
        assert c.has_class("-pressed") and tint(c) > 0.1
        await pilot.mouse_up(c)
        assert not c.has_class("-pressed")

        await pilot.click(c, button=3)
        await pilot.pause()
        assert not isinstance(app.screen, AtlasModal)
        await pilot.click(c)
        await pilot.pause()
        menu = app.screen
        assert isinstance(menu, HarnessMenu)
        options = menu.query_one(OptionList)
        assert options.option_count == len(ids)
        assert options.highlighted == ids.index(app.state.harness)
        assert options.region.y == c.region.bottom and options.region.x == c.region.x
        await pilot.click(OptionList, offset=(2, 1 + ids.index("gemini-cli")))
        await pilot.pause()
        assert not isinstance(app.screen, AtlasModal)
        assert app.state.harness == "gemini-cli"
        assert text(chip(app)) == f"{header.label_of(app, 'gemini-cli')} ▾"

        await pilot.click(c)
        await pilot.pause()
        await pilot.click(offset=(5, MID[1] - 3))
        await pilot.pause()
        assert not isinstance(app.screen, AtlasModal) and app.state.harness == "gemini-cli"


@pytest.mark.asyncio
async def test_the_harness_menu_opens_by_key_and_picks_with_the_keyboard(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=NARROW) as pilot:
        await start(pilot)
        ids = views.harness_choices(app.data.insights)
        await app.action_run("widgets.header:open_harness_menu")
        await pilot.pause()
        assert isinstance(app.screen, HarnessMenu)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, AtlasModal)
        open_harness_menu(app)
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        want = ids[ids.index("claude-code:personal") + 2]
        assert app.state.harness == want
        assert text(chip(app)) == f"{header.label_of(app, want)} ▾"


@pytest.mark.asyncio
async def test_brackets_step_through_harnesses_and_the_chip_follows(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        ids = views.harness_choices(app.data.insights)
        i = ids.index(app.state.harness)
        for step in range(len(ids)):
            await pilot.press("right_square_bracket")
            want = ids[(i + step + 1) % len(ids)]
            assert app.state.harness == want
            assert f"{header.label_of(app, want)} ▾" in row(app)
        await pilot.press("left_square_bracket")
        assert app.state.harness == ids[i - 1]


@pytest.mark.asyncio
async def test_the_chip_tooltip_names_the_settings_file_and_the_menu_shows_it(calls):
    app = AtlasApp(Atlas(scan={"bundled_skills_disabled": True}))
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        switch = f"Switch harness · {key_for('harness(-1)')}"
        tips = {}
        for h in ("all", "claude-code:personal", "codex", "cursor"):
            app.set_state(harness=h)
            await pilot.pause()
            tips[h] = chip(app).tooltip
        assert tips["all"] == f"Pick a harness to switch skills\n{switch}"
        assert tips["claude-code:personal"] == (
            f"Built-ins off; writes ~/.claude/settings.json\n{switch}"
        )
        assert tips["codex"] == f"Writes ~/.codex/config.toml\n{switch}"
        assert tips["cursor"] == f"Cursor has no per-skill switch\n{switch}"
        open_harness_menu(app)
        await pilot.pause()
        prompts = [str(o.prompt) for o in app.screen.query_one(OptionList).options]
        personal = next(p for p in prompts if p.startswith("Claude Code · personal"))
        assert personal.endswith("writes ~/.claude/settings.json") and "…" not in personal
        assert not any("built-ins off" in p for p in prompts)
        assert any("Cursor has no per-skill switch" in p for p in prompts)
        assert any(p.startswith("All harnesses") and "pick a harness" in p for p in prompts)


@pytest.mark.asyncio
async def test_one_harness_shows_a_plain_chip_and_none_shows_no_chip(calls):
    one = {"harnesses": {"codex": {**DemoAtlas(n=1).data()["harnesses"]["codex"]}}}
    app = AtlasApp(Atlas(scan=one))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        c = chip(app)
        assert c.display and text(c) == "Codex" and c.has_class("-idle")
        assert "All harnesses" not in row(app) and "▾" not in row(app)
        assert c.tooltip == "Writes ~/.codex/config.toml"
        await pilot.click(c)
        await pilot.pause()
        assert not isinstance(app.screen, AtlasModal)

    app = AtlasApp(Atlas(scan={"harnesses": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        assert not chip(app).display and not app.query_one("#skeleton").display


@pytest.mark.asyncio
async def test_a_skeleton_shows_until_the_scan_names_the_harnesses(calls, monkeypatch):
    gate = threading.Event()
    atlas = Atlas()
    real = atlas.data
    monkeypatch.setattr(atlas, "data", lambda: gate.wait(5) and real())
    app = AtlasApp(atlas)
    async with app.run_test(size=MID) as pilot:
        await pilot.pause()
        assert app.query_one("#skeleton").display and not chip(app).display
        assert "Skill Atlas" in row(app)
        gate.set()
        await settle(pilot)
        assert not app.query_one("#skeleton").display and chip(app).display


@pytest.mark.asyncio
async def test_a_failed_scan_drops_the_skeleton(calls):
    atlas = Atlas()

    def broken():
        raise OSError("scan broke")

    atlas.data = broken
    app = AtlasApp(atlas)
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        assert "scan" in app.data.errors
        assert not app.query_one("#skeleton").display


@pytest.mark.asyncio
async def test_no_color_keeps_the_surface_step_and_never_reverses(calls, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        surface = app.current_theme.variables["atlas-surface-3"].lower()
        assert not chip(app).styles.text_style.reverse
        assert chip(app).styles.background.hex.lower() == surface


# The update cluster


@pytest.mark.asyncio
async def test_the_updates_link_opens_the_updates_view_on_a_left_click_only(calls):
    app = AtlasApp(Atlas(updates={"errors": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        n = outdated(app)
        updates = cell(app, "updates")
        assert n > 0 and text(updates) == link(app)
        top = row(app)
        assert "Update" not in top and "new" not in top
        assert "Check again" not in top and not cell(app, "check").display
        assert not app.query("#count") and not app.query("#new") and not app.query("#all")
        tip = f"Show the {views.plural(n, 'skill')} with updates · 4"
        assert updates.tooltip == tip
        assert updates.styles.background.a == 0
        await pilot.hover(updates)
        await pilot.pause()
        surface = app.current_theme.variables["atlas-surface-2"].lower()
        assert updates.styles.background.hex.lower() == surface
        await pilot.click(updates, button=3)
        assert app.state.view == "all"
        await pilot.mouse_down(updates)
        assert updates.has_class("-pressed")
        await pilot.mouse_up(updates)
        await pilot.click(updates)
        await pilot.pause()
        assert app.state.view == "updates" and not updates.display and calls == []
        await pilot.press("1")
        await pilot.pause()
        assert updates.display


@pytest.mark.asyncio
async def test_the_updates_link_follows_the_harness(calls):
    app = AtlasApp(Atlas(updates={"errors": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        for h in views.harness_choices(app.data.insights):
            app.set_state(harness=h)
            await pilot.pause()
            n = outdated(app)
            assert cell(app, "updates").display == bool(n)
            if n:
                assert text(cell(app, "updates")) == link(app)
            else:
                assert "✓ Up to date" in row(app)


@pytest.mark.asyncio
async def test_marks_hide_the_updates_link(calls):
    app = AtlasApp(Atlas(updates={"errors": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        assert cell(app, "updates").display
        app.set_state(marked={app.data.skills[0]["path"]})
        await pilot.pause()
        assert not cell(app, "updates").display and "↑" not in row(app)
        app.set_state(marked=frozenset())
        await pilot.pause()
        assert cell(app, "updates").display


@pytest.mark.asyncio
async def test_up_to_date_is_a_check_mark_that_checks_again(calls):
    app = AtlasApp(Atlas(updates={"skills": {}, "errors": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        check = cell(app, "check")
        assert "✓ Up to date" in row(app) and not cell(app, "updates").display
        assert check.tooltip == f"Check again · {key_for(header.CHECK_AGAIN)}"
        await pilot.hover(check)
        await pilot.pause()
        surface = app.current_theme.variables["atlas-surface-2"].lower()
        assert check.styles.background.hex.lower() == surface
        await pilot.mouse_down(check)
        assert check.has_class("-pressed")
        await pilot.mouse_up(check)
        await pilot.click(check, button=3)
        assert calls == []
        await pilot.click(check)
        await pilot.pause()
        assert calls == ["check_again"]


@pytest.mark.asyncio
async def test_new_skills_show_no_header_chip(calls):
    app = AtlasApp(Atlas(updates={"errors": {}}))
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        assert views.new_total(app.data.insights)
        assert " new" not in row(app) and "+ " not in row(app)


@pytest.mark.asyncio
async def test_the_warning_lists_the_errors_and_opens_them(calls):
    errors = {"acme/skills": "could not read acme/skills from GitHub: GitHub did not answer"}
    app = AtlasApp(Atlas(updates={"errors": errors}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        warn = cell(app, "warn")
        assert warn.display and text(warn) == "! 1 not checked"
        assert warn.tooltip == f"Could not check 1 source\n{errors['acme/skills']}"
        await pilot.hover(warn)
        await pilot.pause()
        surface = app.current_theme.variables["atlas-surface-2"].lower()
        assert warn.styles.background.hex.lower() == surface
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
        assert check.tooltip is None
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
async def test_a_recheck_with_updates_says_so_then_leaves_the_bar(calls):
    app = AtlasApp(Atlas(updates={"errors": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        check = cell(app, "check")
        button = cell(app, "updates").region
        assert not check.display
        app.reload(["updates"], refresh=True)
        await settle(pilot)
        assert check.display and text(check) == "✓ Checked just now"
        assert check.region.right < cell(app, "updates").region.x
        assert cell(app, "updates").region == button
        head(app)._just_until = 0
        head(app).draw()
        await pilot.pause()
        assert not check.display and "Check again" not in row(app)
        assert cell(app, "updates").region == button


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
async def test_a_job_replaces_the_cluster_and_the_chip_stays_put(calls):
    app = AtlasApp(Atlas())
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        place = (chip(app).region, text(chip(app)))

        def steady():
            assert (chip(app).region, text(chip(app))) == place

        items = {f"s{i}": {"state": "done" if i < 3 else "queued"} for i in range(8)}
        app.broadcast(lambda: JobChanged({"kind": "update", "done": False, "items": items}))
        await pilot.pause()
        job = cell(app, "job")
        assert job.display and "Updating 3 of 8…" in text(job)
        assert not any(cell(app, p).display for p in PIECES if p != "job")
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
        assert not job.display and cell(app, "updates").display
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
        assert not any(cell(app, p).display for p in PIECES)
        atlas.gate.set()
        await settle(pilot)
        assert cell(app, "updates").display
        app.data.insights.writable = False
        head(app).draw()
        assert not any(cell(app, p).display for p in PIECES)


@pytest.mark.asyncio
async def test_a_checking_cluster_keeps_its_settled_width(calls):
    app = AtlasApp(Atlas(updates={"skills": {}, "errors": {}, "available": {}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        cluster = app.query_one("#cluster")
        width = len(" ✓ Up to date ") + 1
        assert "✓ Up to date" in row(app) and cluster.size.width == width
        place = chip(app).region
        head(app)._checking = True
        head(app).draw()
        await pilot.pause()
        assert cluster.size.width == width
        assert chip(app).region == place


@pytest.mark.asyncio
async def test_at_60_columns_a_recheck_keeps_the_warning_and_the_link(calls):
    app = AtlasApp(Atlas(updates={"errors": {"acme/skills": "GitHub did not answer"}}))
    async with app.run_test(size=TINY) as pilot:
        await start(pilot)
        assert "! 1" in row(app) and f"↑ {outdated(app)}" in row(app)
        app.reload(["updates"], refresh=True)
        await settle(pilot)
        top = row(app)
        assert "! 1" in top and f"↑ {outdated(app)}" in top
        assert "Claude Code" in top and chip(app).size.width >= header.CHIP_MIN
        shown = [p for p in PIECES if cell(app, p).display]
        regions = [chip(app).region] + [cell(app, p).region for p in shown]
        assert all(a.right <= b.x for a, b in itertools.pairwise(regions))
        assert regions[-1].right <= TINY[0] - 1


@pytest.mark.asyncio
async def test_the_stale_band_asks_for_a_restart(calls):
    app = AtlasApp(Atlas(scan={"server": {"build": "demo", "stale": True}}))
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        band = app.query_one("#stale", Static)
        assert band.display and head(app).size.height == 2
        assert "Skill Atlas changed on disk. Quit and start it again." in row(app, 1)


def test_glyphs_are_one_cell_wide():
    from rich.cells import cell_len

    for glyph in ("╱", "✓", "✗", "!", "↑", "…", "▾", *header.SPINNER):
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
