import importlib
import json
import statistics
import sys
import threading
import time
import types
from datetime import datetime, timezone

import pytest
from textual.widgets import Static

from skill_atlas.core import views
from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.messages import JobChanged
from skill_atlas.tui.widgets.skill_list import (
    FLASH_STEPS,
    MINI_MAX,
    STATUS_W,
    STATUS_WIDE,
    SkillList,
    _cut,
)

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
WIDE, NARROW = (160, 40), (80, 24)


def lines(app):
    return [s.text for s in app.screen._compositor.render_strips()]


def on_screen(app, text):
    return any(text in line for line in lines(app))


def find(app, text):
    for y, line in enumerate(lines(app)):
        x = line.find(text)
        if x >= 0:
            return (x, y)
    raise AssertionError(f"{text!r} is not on the screen")


def cols(lst):
    return lst._cols(lst.scrollable_content_region.width)


def cell(lst, i, x):
    """The screen offset of column x on row i of the list."""
    return (lst.region.x + x, lst.region.y + i - int(lst.scroll_offset.y))


def first(lst, kind, test=lambda row: True):
    return next(i for i, r in enumerate(lst.rows) if r.kind == kind and test(r))


def outdated(lst):
    ins = lst._ins
    return lambda r: r.kind == "skill" and views.is_outdated(ins, r.item)


class SlowDemo(DemoAtlas):
    """Demo data whose scan waits for `gate`."""

    def __init__(self):
        super().__init__(now=NOW)
        self.gate = threading.Event()

    def data(self):
        self.gate.wait(5)
        return super().data()


@pytest.fixture
def panels(monkeypatch):
    """The panel regions are stubs; this file tests the list."""
    monkeypatch.setattr("skill_atlas.tui.app.DetailPanel", Static)
    monkeypatch.setattr("skill_atlas.tui.app.SidePanel", Static)


@pytest.fixture
def app(prefs, panels):
    return AtlasApp(DemoAtlas(now=NOW))


@pytest.fixture
def calls(monkeypatch):
    """Replace what the list calls in other modules. Record the calls; jobs reads `states`."""
    seen: list[tuple] = []
    states: dict[str, str] = {}
    flashes: dict[str, float] = {}

    def stub(name, *funcs):
        full = f"skill_atlas.tui.{name}"
        try:
            module = importlib.import_module(full)
        except ModuleNotFoundError:
            module = types.ModuleType(full)
            monkeypatch.setitem(sys.modules, full, module)
        for func in funcs:

            def record(app, *args, _f=func):
                seen.append((_f, *args))

            monkeypatch.setattr(module, func, record, raising=False)
        return module

    jobs = stub("jobs", "toggle", "update", "install", "check_again")
    monkeypatch.setattr(jobs, "state_of", lambda app, n: states.get(n), raising=False)
    monkeypatch.setattr(jobs, "error_of", lambda app, n: "", raising=False)
    monkeypatch.setattr(jobs, "confirming", lambda app: None, raising=False)
    monkeypatch.setattr(jobs, "flashes", lambda app: flashes, raising=False)
    stub("commands", "open_actions")
    stub("screens.reader", "open_reader")
    return types.SimpleNamespace(seen=seen, states=states, flashes=flashes)


@pytest.mark.asyncio
async def test_rows_show_sections_groups_and_skills(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        assert lst.mode == "rows" and not app.query("OptionList")
        assert {"section", "group", "skill", "blank"} <= {r.kind for r in lst.rows}
        group = lst.rows[first(lst, "group")]
        skill = lst.rows[first(lst, "skill")]
        assert on_screen(app, "YOUR SKILLS")
        assert on_screen(app, group.item["label"])
        assert on_screen(app, "/" + (skill.item.get("invoke") or skill.item["name"]))
        assert on_screen(app, "Collapse all")
        assert lst.cursor == lst._stops[0]
        width = lst.scrollable_content_region.width
        assert all(lst.render_line(y).cell_length == width for y in range(10))


@pytest.mark.asyncio
async def test_skeleton_rows_until_the_scan_arrives(prefs, panels):
    atlas = SlowDemo()
    app = AtlasApp(atlas)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        lst = app.query_one(SkillList)
        assert lst.mode == "skeleton" and not lst.rows
        assert on_screen(app, "━━━")
        atlas.gate.set()
        await settle(pilot)
        assert lst.mode == "rows" and lst.rows


@pytest.mark.asyncio
async def test_keys_move_open_and_jump(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        stops = lst._stops
        await pilot.press("j")
        await pilot.pause()
        assert lst.cursor == stops[1]
        assert (app.state.selected or app.state.selected_key) == lst.rows[stops[1]].key
        await pilot.press("k")
        await pilot.pause()
        assert lst.cursor == stops[0]
        await pilot.press("end")
        await pilot.pause()
        top = int(lst.scroll_offset.y)
        assert lst.cursor == stops[-1] and top <= lst.cursor < top + lst.size.height
        await pilot.press("home")
        await pilot.pause()
        assert lst.cursor == stops[0] and lst.scroll_offset.y == 0
        await pilot.press("pagedown")
        await pilot.pause()
        assert lst.cursor >= stops[0] + lst.size.height - 3
        await pilot.press("backslash")
        assert not app.state.detail_open
        await pilot.press("j", "enter")
        await pilot.pause()
        assert app.state.detail_open


@pytest.mark.asyncio
async def test_a_cursor_move_draws_two_lines(app, monkeypatch):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        await pilot.press("j")
        await pilot.pause()
        drawn, dirty = [], []
        draw, refresh = lst._draw, lst.refresh
        monkeypatch.setattr(lst, "_draw", lambda i, *a: drawn.append(i) or draw(i, *a))
        monkeypatch.setattr(lst, "refresh", lambda *r, **k: dirty.extend(r) or refresh(*r, **k))
        old = lst.cursor
        await pilot.press("j")
        await pilot.pause()
        assert sum(r.height for r in dirty) == 2
        assert lst.cursor in drawn and set(drawn) <= {old, lst.cursor}


@pytest.mark.asyncio
async def test_marks_with_keys(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        group = lst.rows[lst.cursor]
        assert group.kind == "group"
        g = lst.cursor
        await pilot.press("m")
        assert app.state.marked == {s["path"] for s in group.item["skills"]}
        assert lst.cursor == lst._stops[lst._stops.index(g) + 1]
        await pilot.press("k", "m")
        assert not app.state.marked
        a = lst.rows[lst.cursor].key
        await pilot.press("m")
        assert app.state.marked == {a} and lst.rows[lst.cursor].key != a
        await pilot.press("k", "shift+j")
        assert app.state.marked == {a, lst.rows[lst.cursor].key}
        await pilot.press("ctrl+a")
        assert app.state.marked == {r.key for r in lst.rows if r.kind == "skill"}
        await pilot.press("escape")
        assert not app.state.marked


@pytest.mark.asyncio
async def test_click_selects_and_a_double_click_opens_the_reader(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        i = first(lst, "skill") + 2
        where = cell(lst, i, cols(lst).name + 2)
        await pilot.click(offset=where)
        await pilot.pause()
        assert lst.cursor == i and app.state.selected == lst.rows[i].key
        await pilot.click(offset=where, times=2)
        await pilot.pause()
        assert ("open_reader", lst.rows[i].key) in calls.seen


@pytest.mark.asyncio
async def test_right_click_and_the_menu_cell_open_the_actions(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        i = first(lst, "skill") + 1
        await pilot.click(offset=cell(lst, i, cols(lst).name + 2), button=3)
        await pilot.pause()
        assert calls.seen[-1] == ("open_actions", lst.rows[i].key)
        assert app.state.selected == lst.rows[i].key
        g = first(lst, "group")
        await pilot.click(offset=cell(lst, g, cols(lst).menu))
        await pilot.pause()
        assert calls.seen[-1] == ("open_actions", lst.rows[g].key)


@pytest.mark.asyncio
async def test_click_the_mark_cell_and_shift_click_a_range(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        a = first(lst, "skill")
        b = a + 3
        await pilot.click(offset=cell(lst, a, 1))
        assert app.state.marked == {lst.rows[a].key}
        await pilot.click(offset=cell(lst, b, 1), shift=True)
        assert app.state.marked == {lst.rows[k].key for k in range(a, b + 1)}
        await pilot.click(offset=cell(lst, b, 1))
        assert lst.rows[b].key not in app.state.marked


@pytest.mark.asyncio
async def test_click_a_switch_toggles_its_row_or_group(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        i = first(lst, "skill") + 1
        await pilot.click(offset=cell(lst, i, cols(lst).sw + 1))
        await pilot.pause()
        assert calls.seen[-1] == ("toggle",) and app.state.selected == lst.rows[i].key
        g = first(lst, "group")
        await pilot.click(offset=cell(lst, g, cols(lst).sw + 1))
        await pilot.pause()
        assert calls.seen[-1] == ("toggle",) and app.state.selected_key == lst.rows[g].key


@pytest.mark.asyncio
async def test_x_on_the_cursor_row_toggles_through_jobs(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("j", "x")
        await pilot.pause()
        assert calls.seen[-1] == ("toggle",)


@pytest.mark.asyncio
async def test_click_the_chevron_folds_and_unfolds_a_group(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        g = first(lst, "group")
        gid = lst.rows[g].key
        before = len(lst.rows)
        await pilot.click(offset=cell(lst, g, cols(lst).chev))
        await pilot.pause()
        assert gid in app.state.collapsed and len(lst.rows) < before
        await pilot.click(offset=cell(lst, g, cols(lst).chev))
        await pilot.pause()
        assert gid not in app.state.collapsed and len(lst.rows) == before


@pytest.mark.asyncio
async def test_group_update_click_updates_its_outdated_skills(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        g = first(lst, "group", lambda r: lst._memo(r) is not None)
        status = lst._memo(lst.rows[g])
        assert status.zone == "update" and status.word.startswith("Update ")
        await pilot.click(offset=cell(lst, g, cols(lst).status + 2))
        await pilot.pause()
        name, names = calls.seen[-1]
        assert name == "update" and len(names) == int(status.word.split()[1])
        assert app.state.selected_key == lst.rows[g].key


@pytest.mark.asyncio
async def test_row_update_status_is_a_click_target(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        i = first(lst, "skill", outdated(lst))
        await pilot.click(offset=cell(lst, i, cols(lst).status))
        await pilot.pause()
        assert calls.seen[-1] == ("update", [views.lock_name(lst.rows[i].item)])


@pytest.mark.asyncio
async def test_collapse_all_and_expand_all(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        ids = set(lst.rows[first(lst, "section")].item["group_ids"])
        await pilot.click(offset=find(app, "Collapse all"))
        await pilot.pause()
        assert ids <= app.state.collapsed and on_screen(app, "Expand all")
        await pilot.click(offset=find(app, "Expand all"))
        await pilot.pause()
        assert not ids & app.state.collapsed


@pytest.mark.asyncio
async def test_fold_keys(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        await pilot.press("j", "j")
        head = lst.rows[lst.cursor].head
        gid = lst.rows[head].key
        await pilot.press("left")
        assert lst.cursor == head
        await pilot.press("left")
        await pilot.pause()
        assert gid in app.state.collapsed
        await pilot.press("right")
        await pilot.pause()
        assert gid not in app.state.collapsed
        await pilot.press("shift+h")
        await pilot.pause()
        every = {g for r in lst.rows if r.kind == "section" for g in r.item["group_ids"]}
        assert every <= app.state.collapsed
        await pilot.press("shift+l")
        await pilot.pause()
        assert not every & app.state.collapsed


@pytest.mark.asyncio
async def test_hover_shows_a_tooltip_and_the_hover_state(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        i = first(lst, "skill") + 1
        await pilot.hover(offset=cell(lst, i, cols(lst).sw + 1))
        await pilot.pause()
        assert lst._hover == (i, "") and "turn" in str(lst.tooltip)
        g = first(lst, "group", lambda r: lst._memo(r) is not None)
        await pilot.hover(offset=cell(lst, g, cols(lst).status + 2))
        await pilot.pause()
        assert lst._hover == (g, "update") and str(lst.tooltip).startswith("Update ")
        await pilot.hover(offset=(0, 0))
        await pilot.pause()
        assert lst._hover is None


@pytest.mark.asyncio
async def test_search_rebuilds_once_per_burst_and_shows_the_empty_state(app, monkeypatch):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        count = []
        real = lst.rebuild
        monkeypatch.setattr(lst, "rebuild", lambda: count.append(1) or real())
        for q in ("z", "zz", "zzz", "zzzq"):
            app.set_state(query=q)
        await pilot.pause(0.3)
        assert len(count) == 1
        assert lst.mode == "empty" and on_screen(app, "No skills match “zzzq”")
        await pilot.click(offset=find(app, "Clear search"))
        await pilot.pause(0.3)
        assert app.state.query == "" and lst.mode == "rows"


@pytest.mark.asyncio
async def test_search_terms_are_highlighted(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        app.set_state(query="market")
        await pilot.pause(0.3)
        i = first(lst, "skill", lambda r: "market" in r.item["name"])
        tint = lst._palette()["atlas-accent-tint"]
        strip = lst._line(i, lst.scrollable_content_region.width)
        lit = "".join(
            s.text for s in strip if s.style and s.style.bgcolor and s.style.bgcolor.name == tint
        )
        assert "market" in lit.lower()


@pytest.mark.asyncio
async def test_new_view_rows_install_and_the_block_actions(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("6")
        await settle(pilot)
        lst = app.query_one(SkillList)
        assert lst.rows[0].item["title"] == "New from your sources"
        a = first(lst, "avail")
        row = lst.rows[a]
        assert on_screen(app, "Install 3 new")
        assert not on_screen(app, "+ new") and not on_screen(app, "+3 new")
        await pilot.click(offset=cell(lst, a, cols(lst).status + 2))
        await pilot.pause()
        assert calls.seen[-1] == ("install", row.repo, [row.item["path"]])
        assert app.state.selected_key == row.key
        await pilot.click(offset=find(app, "Install 3 new"))
        await pilot.pause()
        name, repo, paths = calls.seen[-1]
        assert (name, repo, len(paths)) == ("install", row.repo, 3)


@pytest.mark.asyncio
async def test_click_an_available_header_opens_the_block(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        h = first(lst, "avail-head", lambda r: not r.item["available_open"])
        repo = lst.rows[h].repo
        lst.scroll_to(y=h - 3, animate=False)
        await pilot.pause()
        await pilot.click(offset=cell(lst, h, cols(lst).chev))
        await pilot.pause()
        assert f"+av:{repo}" in app.state.collapsed
        assert any(r.kind == "avail" and r.repo == repo for r in lst.rows)


@pytest.mark.asyncio
async def test_compact_rows_have_no_blank_lines_and_no_spark(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        assert any(r.kind == "blank" for r in lst.rows)
        await pilot.press("c")
        await pilot.pause()
        assert not any(r.kind == "blank" for r in lst.rows)
        assert cols(lst).spark_w == 0


@pytest.mark.asyncio
async def test_columns_drop_in_the_design_order(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        layouts = [lst._layout(w) for w in range(200, 30, -1)]
        assert layouts[0].status_w == STATUS_WIDE
        for c in layouts:
            assert c.name == 10 and c.status + c.status_w + 3 == c.width
            if c.spark_w:
                assert c.count_w and c.status_w >= STATUS_W and c.desc_w
            if c.count_w:
                assert c.status_w >= STATUS_W and c.desc_w
        assert any(c.status_w == 1 and c.desc_w for c in layouts)
        assert layouts[-1].status_w == 1 and not layouts[-1].desc_w


@pytest.mark.asyncio
async def test_one_long_name_does_not_set_the_name_column(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        longest = max(len(r.item["name"]) for r in lst.rows if r.kind == "skill")
        assert lst._name_len < longest
        assert on_screen(app, "/acme-quarterly-")
        assert not on_screen(app, "/acme-quarterly-business-review ")


def test_cut_text_ends_on_a_letter():
    assert _cut("Review Acme REST endpoints", 18) == "Review Acme REST…"
    assert _cut("Plan, launch, or fix", 14) == "Plan, launch…"
    assert _cut("short", 10) == "short"


@pytest.mark.asyncio
async def test_narrow_window_keeps_name_switch_and_status(app):
    async with app.run_test(size=NARROW) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        c = cols(lst)
        assert c.spark_w == 0 and c.status_w > 1 and c.name_w >= 14


@pytest.mark.asyncio
async def test_busy_and_done_rows_from_jobs(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        i = first(lst, "skill", outdated(lst))
        name = views.lock_name(lst.rows[i].item)
        calls.states[name] = "downloading"
        view = {"items": {name: {"state": "downloading"}}, "kind": "update"}
        app.broadcast(lambda: JobChanged(view))
        await pilot.pause()
        status = lst._memo(lst.rows[i]).status
        assert status.spin and status.word == "updating"
        head = lst._memo(lst.rows[lst.rows[i].head])
        assert head.spin and head.word.endswith("of 1")
        calls.states[name] = "done"
        app.broadcast(lambda: JobChanged({**view, "items": {name: {"state": "done"}}}))
        await pilot.pause()
        assert lst._memo(lst.rows[i]).status.word == "updated"


@pytest.mark.asyncio
async def test_rows_flash_when_jobs_names_them(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        i = first(lst, "skill", lambda r: r.item.get("scope") == "personal")
        calls.flashes[lst.rows[i].item["dir_name"]] = time.monotonic()
        app.broadcast(lambda: JobChanged(None))
        await pilot.pause()
        assert lst._flash_step(lst.rows[i]) < FLASH_STEPS
        app.animation_level = "none"
        app.broadcast(lambda: JobChanged(None))
        await pilot.pause()
        assert lst._flash_step(lst.rows[i]) == FLASH_STEPS


@pytest.mark.asyncio
async def test_the_group_header_pins_while_its_rows_scroll(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        g = first(lst, "group", lambda r: len(r.item["skills"]) > 10)
        lst.scroll_to(y=g + 5, animate=False)
        await pilot.pause()
        assert lst._row_at(0) == g
        assert lst.rows[g].item["label"] in lst.render_line(0).text


@pytest.mark.asyncio
async def test_all_harnesses_show_dots_not_switches(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.set_state(harness="all")
        await pilot.pause()
        lst = app.query_one(SkillList)
        cells = lst._memo(lst.rows[first(lst, "skill")])
        assert cells.dots and not cells.switch
        assert on_screen(app, "●")


@pytest.mark.asyncio
async def test_speed_at_2000_skills(prefs, panels):
    app = AtlasApp(DemoAtlas(n=2000, now=NOW))
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        height = lst.scrollable_content_region.height
        rebuilds = []
        for _ in range(5):
            t = time.perf_counter()
            lst.rebuild()
            for y in range(height):
                lst.render_line(y)
            rebuilds.append(time.perf_counter() - t)
        moves = []
        for _ in range(30):
            t = time.perf_counter()
            lst.action_cursor_down()
            for y in range(height):
                lst.render_line(y)
            moves.append(time.perf_counter() - t)
            await pilot.pause()
        rebuild, move = statistics.median(rebuilds), statistics.median(moves)
        print(f"\n2000 skills: rebuild {rebuild * 1000:.1f} ms, cursor move {move * 1000:.2f} ms")
        assert rebuild < 0.15 and move < 0.01


@pytest.mark.asyncio
async def test_a_hidden_selection_is_cleared_so_keys_act_on_the_cursor_row(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        await pilot.press("j")
        await pilot.pause()
        hidden = app.state.selected
        app.set_state(view="issues")
        await pilot.pause()
        assert hidden not in lst._index and app.state.selected is None
        path, key = app.current()
        assert (path or key) == lst.rows[lst.cursor].key


@pytest.mark.asyncio
async def test_a_folded_selection_leaves_the_cursor_on_its_group(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        await pilot.press("j", "j", "j")
        await pilot.pause()
        head = lst.rows[lst.rows[lst.cursor].head]
        await pilot.click(offset=cell(lst, lst.rows.index(head), cols(lst).chev))
        await pilot.pause()
        assert app.state.selected is None and lst.rows[lst.cursor].key == head.key


@pytest.mark.asyncio
async def test_narrow_click_selects_and_a_second_click_opens_the_drawer(prefs, panels):
    app = AtlasApp(DemoAtlas(now=NOW))
    async with app.run_test(size=NARROW) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        i = first(lst, "skill") + 2
        where = cell(lst, i, cols(lst).name + 2)
        await pilot.click(offset=where)
        await pilot.pause()
        assert lst.cursor == i and app.state.selected == lst.rows[i].key
        assert not app.detail_visible
        await pilot.click(offset=where)
        await pilot.pause()
        assert app.detail_visible


@pytest.mark.asyncio
async def test_two_tags_then_plus_n_as_the_web(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        many = first(lst, "skill", lambda r: len(lst._memo(r).more) >= 2)
        cells = lst._memo(lst.rows[many])
        assert cols(lst).status_w == STATUS_W and lst._layout(160).status_w == STATUS_WIDE
        text = lst._line(many, 160).text
        assert cells.status.word in text and cells.more[0].word in text
        assert f"+{len(cells.more) - 1}" in text
        narrow = lst._line(many, 90).text
        assert f"+{len(cells.more)}" in narrow and cells.more[0].word not in narrow


@pytest.mark.asyncio
async def test_plain_tags_are_faint(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        i = first(lst, "skill", lambda r: lst._memo(r).status.word == "you only")
        assert lst._memo(lst.rows[i]).status.color == "atlas-faint"


@pytest.mark.asyncio
async def test_the_menu_cell_shows_on_the_cursor_and_hover_rows(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        width = lst.scrollable_content_region.width
        g = first(lst, "group", lambda r: lst.rows.index(r) != lst.cursor)
        assert "⋯" not in lst._line(g, width).text
        assert "⋯" in lst._line(lst.cursor, width).text
        await pilot.hover(offset=cell(lst, g, cols(lst).name))
        await pilot.pause()
        assert "⋯" in lst._line(g, width).text


@pytest.mark.asyncio
async def test_a_marked_row_keeps_its_color_under_the_pointer(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        i = first(lst, "skill") + 2
        await pilot.click(offset=cell(lst, i, 0))
        assert app.state.marked == {lst.rows[i].key}
        await pilot.hover(offset=cell(lst, i, cols(lst).name))
        await pilot.pause()
        assert lst._hover == (i, "")
        mark = lst._palette()["atlas-mark"]
        assert lst._row_bg(i, lst.rows[i], "", FLASH_STEPS) == mark


@pytest.mark.asyncio
async def test_group_meta_drops_whole_parts(prefs, panels):
    app = AtlasApp(DemoAtlas(now=NOW))
    async with app.run_test(size=NARROW) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        width = lst.scrollable_content_region.width
        for i, row in enumerate(lst.rows):
            label = row.item.get("label", "")
            if row.kind != "group" or len(label) > 12:
                continue
            after = lst._line(i, width).text.split(label, 1)[1]
            assert "…" not in after and not after.rstrip().endswith("·")


@pytest.mark.asyncio
async def test_available_header_never_cuts_the_repo(prefs, panels):
    app = AtlasApp(DemoAtlas(now=NOW))
    async with app.run_test(size=NARROW) as pilot:
        await settle(pilot)
        await pilot.press("6")
        await settle(pilot)
        lst = app.query_one(SkillList)
        h = first(lst, "avail-head")
        text = lst._line(h, lst.scrollable_content_region.width).text
        assert "Available" in text and "…" not in text.split("Available", 1)[1].split("  ")[0]


@pytest.mark.asyncio
async def test_empty_state_actions_move_with_left_and_right(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        app.set_state(query="api-contracts")
        await pilot.pause(0.3)
        assert lst.mode == "empty" and lst.empty["actions"] == ["clear", "show_project"]
        assert on_screen(app, "enter Clear search")
        await pilot.press("right")
        assert on_screen(app, "enter Show project skills") and on_screen(app, "esc Clear search")
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert app.state.show_project and lst.mode == "rows"


@pytest.mark.asyncio
async def test_skeleton_bars_are_glyphs_inside_their_columns(prefs, panels):
    atlas = SlowDemo()
    app = AtlasApp(atlas)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        lst = app.query_one(SkillList)
        c = cols(lst)
        bg = lst._palette()["background"]
        for y in range(2, 8):
            strip = lst.render_line(y)
            assert all(s.style.bgcolor is None or s.style.bgcolor.name == bg for s in strip)
            name = strip.text[c.name : c.desc]
            assert name.rstrip().count("━") <= c.name_w - 2
        atlas.gate.set()
        await settle(pilot)


class NoHarness(DemoAtlas):
    def data(self):
        return {**super().data(), "harnesses": {}, "settings": {}, "skills": [], "count": 0}


@pytest.mark.asyncio
async def test_no_harness_says_where_to_set_config_roots(prefs, panels):
    app = AtlasApp(NoHarness(now=NOW))
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        assert lst.mode == "empty" and lst.empty["title"] == "No agent harness found"
        assert on_screen(app, "Set config_roots in")


@pytest.mark.asyncio
async def test_large_groups_take_two_lines_and_a_gap(app, monkeypatch):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        await pilot.press("c")
        app.set_state(group_size="large")
        await pilot.pause()
        kinds = [r.kind for r in lst.rows]
        heads = [i for i, k in enumerate(kinds) if k == "group"]
        assert all(kinds[i + 1] == "group-sub" for i in heads)
        assert all(kinds[i - 1] in ("blank", "section") for i in heads[1:])
        assert "blank" in kinds
        assert all(lst.rows[i].kind != "group-sub" for i in lst._stops)
        width = lst.scrollable_content_region.width
        g = heads[0]
        meta = lst.rows[g].item["meta"].split(" · ")[0]
        assert meta not in lst._line(g, width).text and meta in lst._line(g + 1, width).text
        await pilot.press("j")
        await pilot.pause()
        dirty = []
        refresh = lst.refresh
        monkeypatch.setattr(lst, "refresh", lambda *r, **k: dirty.extend(r) or refresh(*r, **k))
        await pilot.press("k")
        await pilot.pause()
        assert lst.cursor == g and sum(r.height for r in dirty) == 3
        sub = lst.rows[heads[1]]
        await pilot.click(offset=cell(lst, heads[1] + 1, cols(lst).name + 2))
        await pilot.pause()
        assert lst.cursor == heads[1] and app.state.selected_key == sub.key
        app.set_state(group_size="regular")
        await pilot.pause()
        assert "group-sub" not in {r.kind for r in lst.rows}


@pytest.mark.asyncio
async def test_rebuild_counts_the_search_results(app, monkeypatch):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = app.query_one(SkillList)
        seen = []
        post = lst.post_message
        monkeypatch.setattr(lst, "post_message", lambda m: seen.append(m) or post(m))
        app.set_state(query="market")
        await pilot.pause(0.3)
        ins, st = app.data.insights, app.state.view_state()
        n = sum(1 for s in ins.skills if views.visible(ins, st, s, None))
        assert lst.results == n > 0
        assert [m.n for m in seen if isinstance(m, SkillList.ResultsChanged)] == [n]


@pytest.fixture
def fresh(new_defaults, prefs, panels):
    """An app with no saved prefs: repos fold in the All view, and rows are short."""
    return AtlasApp(DemoAtlas(now=NOW))


def heads(lst):
    return [r for r in lst.rows if r.kind == "group"]


@pytest.mark.asyncio
async def test_repos_start_folded_and_a_search_or_a_filter_view_opens_them(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        assert heads(lst) and not any(r.item["open"] for r in heads(lst))
        assert not any(r.kind == "skill" for r in lst.rows) and on_screen(fresh, "Expand all")
        kinds = [r.kind for r in lst.rows]
        assert ["group", "blank", "group"] not in [kinds[k : k + 3] for k in range(len(kinds))]
        fresh.set_state(query="market")
        await pilot.pause(0.3)
        assert all(r.item["open"] for r in heads(lst)) and first(lst, "skill") >= 0
        fresh.set_state(query="", view="updates")
        await pilot.pause()
        assert all(r.item["open"] for r in heads(lst)) and first(lst, "skill") >= 0


@pytest.mark.asyncio
async def test_an_open_repo_has_a_blank_line_below_it_and_does_not_move(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        await pilot.press("j")
        g = lst.cursor
        await pilot.press("enter")
        await pilot.pause()
        assert lst.cursor == g and lst.rows[g].item["open"]
        kinds = [r.kind for r in lst.rows]
        end = first(lst, "group", lambda r: lst.rows.index(r) > g)
        assert kinds[g - 1] == "group" and kinds[end - 1] == "blank"
        assert kinds[end + 1] == "group"


@pytest.mark.asyncio
async def test_opened_repos_are_saved_and_restored(fresh, prefs):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        gid = lst.rows[lst.cursor].key
        await pilot.press("enter")
        await pilot.pause()
        assert fresh.state.opened == {gid}
    assert json.loads(prefs.read_text())["opened"] == [gid]
    again = AtlasApp(DemoAtlas(now=NOW))
    async with again.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = again.query_one(SkillList)
        assert [r.key for r in heads(lst) if r.item["open"]] == [gid]


@pytest.mark.asyncio
async def test_expand_all_and_collapse_all_read_the_real_folds(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        ids = set(lst.rows[first(lst, "section")].item["group_ids"])
        await pilot.click(offset=find(fresh, "Expand all"))
        await pilot.pause()
        assert ids <= fresh.state.opened and on_screen(fresh, "Collapse all")
        assert all(r.item["open"] for r in heads(lst) if r.key in ids)
        await pilot.click(offset=find(fresh, "Collapse all"))
        await pilot.pause()
        assert not ids & fresh.state.opened and ids <= fresh.state.collapsed
        assert not any(r.item["open"] for r in heads(lst)) and on_screen(fresh, "Expand all")
        await pilot.press("shift+l")
        await pilot.pause()
        assert fresh.state.opened == {"*"} and not ids & fresh.state.collapsed
        assert all(r.item["open"] for r in heads(lst)) and not on_screen(fresh, "Expand all")
        await pilot.press("shift+h")
        await pilot.pause()
        assert not fresh.state.opened and not any(r.item["open"] for r in heads(lst))


@pytest.mark.asyncio
async def test_enter_and_a_click_fold_a_repo_and_keep_it_selected(fresh, calls):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        g = lst.cursor
        gid = lst.rows[g].key
        await pilot.press("enter")
        await pilot.pause()
        assert lst.rows[g].item["open"] and fresh.state.selected_key == gid
        assert lst.cursor_row() is lst.rows[g]
        await pilot.press("j", "left")
        await pilot.pause()
        assert lst.cursor == g
        await pilot.press("enter")
        await pilot.pause()
        assert not lst.rows[g].item["open"] and lst.cursor == g
        hid = lst.rows[first(lst, "group", lambda r: lst.rows.index(r) > g)].key

        def click(x, times=1):
            return pilot.click(offset=cell(lst, lst._index[hid], x), times=times)

        def is_open():
            return lst.rows[lst._index[hid]].item["open"]

        await click(cols(lst).name + 2)
        await pilot.pause()
        assert is_open() and fresh.state.selected_key == hid
        await click(cols(lst).count + cols(lst).count_w - 1)
        await pilot.pause()
        assert not is_open()
        await click(cols(lst).name + 2, times=2)
        await pilot.pause()
        assert is_open()
        await click(cols(lst).menu)
        await pilot.pause()
        assert calls.seen[-1] == ("open_actions", hid) and is_open()


@pytest.mark.asyncio
async def test_a_skill_selected_elsewhere_opens_its_repo(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        g = heads(lst)[1]
        path = g.item["skills"][2]["path"]
        fresh.set_state(selected=path)
        await pilot.pause()
        assert g.key in fresh.state.opened and lst.rows[lst.cursor].key == path


@pytest.mark.asyncio
async def test_the_status_word_shows_on_the_cursor_and_the_hovered_row(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        fresh.set_state(opened=frozenset({"*"}))
        await pilot.pause()
        lst = fresh.query_one(SkillList)
        width = lst.scrollable_content_region.width
        a, b = [i for i, r in enumerate(lst.rows) if outdated(lst)(r)][:2]
        g = lst.rows[a].head
        n = lst._memo(lst.rows[g]).word.split()[1]
        rest = lst._line(a, width).text
        assert "↑" in rest and "update" not in rest
        assert f"↑ {n}" in lst._line(g, width).text and "Update" not in lst._line(g, width).text
        fresh.set_state(selected=lst.rows[a].key)
        await pilot.pause()
        assert lst.cursor == a and "↑ update" in lst._line(a, width).text
        await pilot.hover(offset=cell(lst, b, cols(lst).name + 2))
        await pilot.pause()
        assert lst._hover == (b, "") and "↑ update" in lst._line(b, width).text
        fresh.set_state(selected=None, selected_key=lst.rows[g].key)
        await pilot.pause()
        assert f"u Update {n}" in lst._line(g, width).text
        assert "update" not in lst._line(a, width).text


@pytest.mark.asyncio
async def test_short_rows_leave_the_detail_to_the_panel(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        fresh.set_state(opened=frozenset({"*"}))
        await pilot.pause()
        lst = fresh.query_one(SkillList)
        width = lst.scrollable_content_region.width
        ins, h = lst._ins, lst._harness

        def info(r):
            tags = [t["text"] for t in views.tags(ins, h, r.item)]
            return tags in (["runs code"], ["you only"]) and not views.is_outdated(ins, r.item)

        row = lst.rows[first(lst, "skill", info)]
        tag = views.tags(ins, h, row.item)[0]["text"]
        desc = views.clean_desc(row.item["description"])[:12]
        text = lst._line(lst._index[row.key], width).text
        assert desc not in text and tag not in text and not set("▁▂▃▄▅▆▇█") & set(text)
        assert lst._memo(row).status.word == ""
        fresh.set_state(row_detail=True)
        await pilot.pause()
        text = lst._line(lst._index[row.key], width).text
        assert desc in text and tag in text


@pytest.mark.asyncio
async def test_a_click_on_the_dot_toggles(fresh, calls):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        g = first(lst, "group", lambda r: lst._group_switch(r.item) is not None)
        await pilot.click(offset=cell(lst, g, cols(lst).sw))
        await pilot.pause()
        assert calls.seen[-1] == ("toggle",) and fresh.state.selected_key == lst.rows[g].key
        assert not lst.rows[g].item["open"]
        fresh.set_state(opened=frozenset({"*"}))
        await pilot.pause()
        i = first(lst, "skill", lambda r: lst._memo(r).switch)
        assert lst._line(i, lst.scrollable_content_region.width).text[cols(lst).sw] in "●○"
        await pilot.click(offset=cell(lst, i, cols(lst).sw))
        await pilot.pause()
        assert calls.seen[-1] == ("toggle",) and fresh.state.selected == lst.rows[i].key


@pytest.mark.asyncio
async def test_available_rows_line_up_with_the_short_columns(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        width = lst.scrollable_content_region.width
        c = cols(lst)
        end = c.status + c.status_w
        assert c.name_w <= MINI_MAX and c.menu + 2 < width
        fresh.set_state(opened=frozenset({"*"}))
        await pilot.pause()
        i = first(lst, "skill", lambda r: outdated(lst)(r) and lst.rows.index(r) != lst.cursor)
        assert lst._line(i, width).text[end - 1] == "↑"
        await pilot.press("6")
        await settle(pilot)
        head = lst._line(first(lst, "avail-head"), width).text.rstrip()
        row = lst._line(first(lst, "avail"), width).text.rstrip()
        c = cols(lst)
        end = c.status + c.status_w
        assert head.index("Available") == row.index("/") == c.name
        assert len(head) == len(row) == end and row.endswith("i Install")
