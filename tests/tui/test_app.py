import json
import threading

import pytest
from textual.app import App
from textual.widgets import Input, OptionList, Static

from skill_atlas.core import views
from skill_atlas.tui import keys, state
from skill_atlas.tui.app import AtlasApp, ErrorBand, settle
from skill_atlas.tui.messages import StateChanged
from skill_atlas.tui.screens import AtlasModal
from skill_atlas.tui.widgets import toast
from skill_atlas.tui.widgets.bulkbar import BulkBar
from skill_atlas.tui.widgets.detail import DetailPanel
from skill_atlas.tui.widgets.header import AtlasHeader
from skill_atlas.tui.widgets.keybar import KeyBar
from skill_atlas.tui.widgets.sidepanel import SidePanel
from skill_atlas.tui.widgets.skill_list import SkillList
from skill_atlas.tui.widgets.viewstrip import ViewStrip

WIDE, NARROW = (140, 40), (90, 30)


def find(app, text, row=None):
    """The screen offset of the first cell of `text`, read from what the screen shows."""
    for y, strip in enumerate(app.screen._compositor.render_strips()):
        x = strip.text.find(text)
        if x >= 0 and row in (None, y):
            return (x, y)
    raise AssertionError(f"{text!r} is not on the screen")


@pytest.mark.asyncio
async def test_app_starts_with_every_region(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        for kind in (AtlasHeader, ViewStrip, SkillList, DetailPanel, SidePanel, BulkBar, KeyBar):
            assert len(app.query(kind)) == 1
        assert app.data.scan is not None and app.data.usage is not None
        assert app.data.updates is not None and not app.data.loading
        assert app.state.harness in app.data.harnesses
        assert app.query_one(SkillList).rows
        assert app.query_one("#detail-pane").display
        assert not app.query_one(BulkBar).display
        assert app.focused is app.query_one(SkillList)


@pytest.mark.asyncio
async def test_window_title_follows_the_data_and_the_harness(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        ins = app.data.insights
        assert app.title == views.window_title(ins, app.state.harness)
        assert "↑" in app.title
        other = next(h for h in app.data.harnesses if h != app.state.harness)
        app.set_state(harness=other)
        assert app.title == views.window_title(ins, other)


@pytest.mark.asyncio
async def test_current_is_the_selection_else_the_cursor_row(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        app.set_state(selected=None, selected_key=None)
        row = lst.rows[lst.cursor]
        assert app.current() == ((row.key, None) if row.kind == "skill" else (None, row.key))
        skill = next(r for r in lst.rows if r.kind == "skill")
        app.set_state(selected=skill.key)
        assert app.current() == (skill.key, None)


@pytest.mark.asyncio
async def test_skeleton_rows_until_the_scan_arrives(stub, prefs):
    stub.gate = threading.Event()
    app = AtlasApp(stub)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        rows = app.query_one(SkillList)
        assert "scan" in app.data.loading and app.data.scan is None
        assert rows.mode == "skeleton" and not rows.rows
        stub.gate.set()
        await settle(pilot)
        assert app.data.scan is not None
        assert sum(r.kind == "skill" for r in rows.rows) == stub.n


@pytest.mark.asyncio
async def test_a_failed_load_shows_a_band_not_a_crash(stub, prefs):
    stub.fail = {"usage"}
    app = AtlasApp(stub)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        assert app.is_running
        assert "usage broke" in app.data.errors["usage"]
        assert app.query_one(ErrorBand).display
        assert "Click this line to try again" in str(app.query_one(ErrorBand).render())
        assert app.data.scan is not None and app.data.updates is not None
        assert toast.current(app) is None


@pytest.mark.asyncio
async def test_a_failed_first_scan_shows_only_the_empty_state(stub, prefs):
    stub.fail = {"scan"}
    app = AtlasApp(stub)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        assert "scan" in app.data.errors
        assert not app.query_one(ErrorBand).display
        assert toast.current(app) is None


@pytest.mark.asyncio
async def test_too_small_shows_only_the_message(app):
    async with app.run_test(size=(59, 15)) as pilot:
        await settle(pilot)
        assert app.has_class("-tiny")
        assert not app.query_one(KeyBar).display or app.query_one(KeyBar).styles.display == "none"
        assert app.query_one("#too-small").styles.display == "block"


@pytest.mark.asyncio
async def test_backslash_hides_and_shows_the_panel(app, prefs, monkeypatch):
    monkeypatch.setattr("skill_atlas.tui.app.SAVE_DELAY", 60)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        pane = app.query_one("#detail-pane")
        await pilot.press("backslash")
        assert not app.state.detail_open and not pane.display
        await pilot.press("backslash", "backslash")
        assert not prefs.exists()
    assert json.loads(prefs.read_text())["detail_open"] is False


@pytest.mark.parametrize(
    ("cols", "width"), [(100, 40), (119, 40), (120, 41), (159, 54), (160, 54), (240, 64)]
)
@pytest.mark.asyncio
async def test_panel_width_follows_the_window(app, cols, width):
    async with app.run_test(size=(cols, 40)) as pilot:
        await settle(pilot)
        assert app.query_one("#detail-pane").size.width == width


@pytest.mark.asyncio
async def test_drag_the_divider_to_resize_the_panel(app, prefs):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        divider = app.query_one("#divider")
        x = divider.region.x
        await pilot.mouse_down(divider)
        await pilot.hover(offset=(x - 20, 10))
        await pilot.mouse_up(offset=(x - 20, 10))
        await pilot.pause()
        width = app.query_one("#detail-pane").size.width
        assert width == app.state.panel_width == WIDE[0] - (x - 20) - 1
        await pilot.click(divider, times=2)
        await pilot.pause()
        assert app.state.panel_width == 0
    assert json.loads(prefs.read_text())["panel_width"] == 0


@pytest.mark.asyncio
async def test_a_tiny_window_says_what_it_needs(app):
    async with app.run_test(size=(50, 14)) as pilot:
        await settle(pilot)
        assert not app.query_one("#main").display and app.query_one("#too-small").display
        message = str(app.query_one("#too-small", Static).render())
        assert "50 × 14" in message and "60 × 16" in message


@pytest.mark.asyncio
async def test_narrow_panel_is_an_overlay_and_keeps_the_saved_choice(app):
    async with app.run_test(size=NARROW) as pilot:
        await settle(pilot)
        pane = app.query_one("#detail-pane")
        assert app.narrow and not pane.display
        await pilot.press("backslash")
        await settle(pilot)
        assert pane.display and pane.styles.layer == "overlay"
        assert pane.size.width == min(NARROW[0] - 8, 64)
        await pilot.press("escape")
        await settle(pilot)
        assert not pane.display and app.state.detail_open


@pytest.mark.asyncio
async def test_enter_selects_and_opens_the_detail(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("backslash", "j", "enter")
        await pilot.pause()
        assert app.state.selected is not None
        assert app.state.detail_open
        assert app.query_one(DetailPanel).display and not app.query_one(SidePanel).display


@pytest.mark.asyncio
async def test_q_quits(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running
    assert app.return_code == 0


@pytest.mark.asyncio
async def test_typing_in_search_does_not_run_keys(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("slash", "q", "1", "c")
        await pilot.pause()
        assert app.is_running
        assert app.state.query == "q1c" and not app.state.compact


@pytest.mark.asyncio
async def test_marks_swap_the_view_strip_for_the_bulk_bar(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        row = app.query_one(ViewStrip).region.y
        path = app.data.skills[0]["path"]
        app.set_state(marked={path})
        await pilot.pause()
        assert app.query_one(BulkBar).display and not app.query_one(ViewStrip).display
        assert app.query_one(BulkBar).region.y == row
        await pilot.press("escape")
        assert app.state.marked == frozenset() and not app.query_one(BulkBar).display


@pytest.mark.asyncio
async def test_click_a_harness_tab_and_a_view_tab(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        other = next(h for h in app.data.harnesses if h != app.state.harness)
        h = app.data.harnesses[other]
        await pilot.click(offset=find(app, h.get("label") or h["name"], row=0))
        assert app.state.harness == other
        await pilot.click(offset=find(app, "Off", row=1))
        assert app.state.view == "off"


@pytest.mark.asyncio
async def test_click_a_key_bar_hint_runs_its_action(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.click(offset=find(app, "search", row=WIDE[1] - 1))
        assert isinstance(app.focused, Input)
        await pilot.click(offset=find(app, "quit", row=WIDE[1] - 1))
        await pilot.pause()
        assert not app.is_running


@pytest.mark.asyncio
async def test_a_click_outside_a_modal_closes_it_unless_it_opts_out(app):
    class Box(AtlasModal[None]):
        def compose(self):
            yield Static("Box", id="box")

    class Sticky(Box):
        CLOSE_ON_OUTSIDE = False

    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.push_screen(Box())
        await pilot.pause()
        await pilot.click("#box")
        assert isinstance(app.screen, Box)
        await pilot.press("1")
        assert isinstance(app.screen, Box)
        await pilot.click(offset=(1, 1))
        assert not isinstance(app.screen, Box)
        app.push_screen(Sticky())
        await pilot.pause()
        await pilot.click(offset=(1, 1))
        assert isinstance(app.screen, Sticky)
        await pilot.press("escape")
        assert not isinstance(app.screen, Sticky)


@pytest.mark.asyncio
async def test_state_changed_reaches_widgets_that_handle_it(app):
    seen = []

    class Probe(OptionList):
        def on_state_changed(self, event: StateChanged) -> None:
            seen.append(event.fields)

    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await app.main.mount(Probe())
        app.set_state(compact=True, view="off")
        await pilot.pause()
        assert seen == [frozenset({"compact", "view"})]


@pytest.mark.asyncio
async def test_motion_levels_map_to_textual(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.set_state(motion="reduced")
        assert app.animation_level == "basic"
        app.set_state(motion="off")
        assert app.animation_level == "none"


@pytest.mark.asyncio
async def test_view_counts_are_computed_once_per_data_change(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        st = app.state.view_state()
        first = app.data.counts(st)
        assert first == views.counts(app.data.insights, st)
        assert app.data.counts(st) is first
        app.data.put("usage", app.data.usage or {})
        assert app.data.counts(st) is not first


def test_old_reduced_motion_pref_loads_as_reduced(tmp_path):
    path = tmp_path / "tui.json"
    path.write_text(json.dumps({"reduced_motion": True}), encoding="utf-8")
    assert state.load(path).motion == "reduced"


@pytest.mark.asyncio
async def test_palette_and_mode_pick_the_theme(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        assert app.theme == "atlas-dark"
        app.set_state(palette="sage", mode="light")
        assert app.theme == "sage-light"


def test_prefs_round_trip(tmp_path):
    path = tmp_path / "tui.json"
    saved = state.UIState(
        harness="codex",
        group_by="type",
        sort="uses",
        compact=True,
        palette="stone",
        mode="light",
        key_hints=False,
        motion="off",
        show_project=True,
        show_stale=True,
        detail_open=False,
        query="not saved",
        selected="/x/SKILL.md",
    )
    state.save(saved, path)
    loaded = state.load(path)
    assert loaded.prefs() == saved.prefs()
    assert loaded.query == "" and loaded.selected is None


def test_bad_prefs_fall_back_to_defaults(tmp_path):
    path = tmp_path / "tui.json"
    path.write_text(json.dumps({"palette": "neon", "compact": "yes", "sort": "uses", "x": 1}))
    loaded = state.load(path)
    assert loaded.palette == "atlas" and loaded.compact is False and loaded.sort == "uses"
    path.write_text("{not json")
    assert state.load(path) == state.UIState()


def test_prefs_path_honours_the_env(tmp_path, monkeypatch):
    monkeypatch.delenv(state.PREFS_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert state.prefs_path() == tmp_path / "skill-atlas" / "tui.json"
    monkeypatch.setenv(state.PREFS_ENV, str(tmp_path / "x.json"))
    assert state.prefs_path() == tmp_path / "x.json"


def test_set_state_rejects_bad_values(app):
    with pytest.raises(ValueError):
        app.set_state(mode="sepia")
    with pytest.raises(ValueError):
        app.set_state(nothing=1)


def test_every_app_key_has_an_action():
    for name in keys.actions("app"):
        assert hasattr(AtlasApp, f"action_{name}"), name
    builtin = {k.action for k in keys.KEYS if k.where == "builtin"}
    assert all(hasattr(App, f"action_{name}") for name in builtin)


def test_no_key_takes_a_terminal_shortcut():
    taken = {key for k in keys.KEYS for key in k.keys.split(",")}
    assert not taken & {"ctrl+c", "ctrl+z", "ctrl+s", "ctrl+q"}
