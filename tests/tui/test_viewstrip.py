import re
import threading
import time
from datetime import datetime, timezone

import pytest
from rich.cells import cell_len
from textual.widgets import OptionList, Static

from skill_atlas.core import views
from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.messages import LoadStarted
from skill_atlas.tui.widgets import viewstrip
from skill_atlas.tui.widgets.skill_list import SkillList
from skill_atlas.tui.widgets.viewstrip import (
    PLACEHOLDER,
    SEARCH,
    SEARCH_WIDE,
    WAIT,
    SearchBox,
    SearchInput,
    ViewMenu,
    ViewStrip,
    ViewTab,
    fit_placeholder,
    window,
)

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
HUGE, WIDE, MID, NARROW = (180, 50), (140, 40), (120, 36), (80, 24)


class SwitchAtlas(DemoAtlas):
    """One harness with a per-skill switch and `n` skills. Add names to `off` to turn them off."""

    def __init__(self, n: int = 100, usage: str = "ready"):
        super().__init__(n=20, now=NOW)
        self.n = n
        self.off: list[str] = []
        self.status = usage
        self.gate: threading.Event | None = None

    def data(self):
        if self.gate is not None:
            self.gate.wait(5)
        harness = {
            "name": "Codex",
            "label": "Codex",
            "home": "/stub",
            "switch": "codex",
            "config": "",
            "store": True,
        }
        skills = [
            {
                "name": f"skill-{i:03d}",
                "dir_name": f"skill-{i:03d}",
                "description": f"Stub skill number {i}.",
                "scope": "personal",
                "path": f"/stub/skills/skill-{i:03d}/SKILL.md",
                "dir": f"/stub/skills/skill-{i:03d}",
                "harnesses": ["codex"],
                "origin": {"source": "acme/skills"},
                "problems": [],
                "security": {"level": "none"},
                "tokens_listed": 40,
            }
            for i in range(self.n)
        ]
        settings = {"codex": {"path": "/stub/.codex/config.toml", "off": list(self.off)}}
        return {
            "harnesses": {"codex": harness},
            "settings": settings,
            "skills": skills,
            "count": len(skills),
            "home": "/stub",
        }

    def usage(self):
        return {"status": self.status, "skills": {}, "counters": {}, "first_day": None}

    def updates(self, refresh=False):
        return {"skills": {}, "errors": {}, "available": {}, "watched": []}


@pytest.fixture(autouse=True)
def panel_stand_ins(monkeypatch):
    """Other builders own the panels; stand-ins keep these tests on the strip."""
    for name in ("SidePanel", "DetailPanel"):
        monkeypatch.setattr(f"skill_atlas.tui.app.{name}", type(name, (Static,), {}))


@pytest.fixture
def demo(prefs):
    return AtlasApp(DemoAtlas(now=NOW))


def strip_of(app) -> ViewStrip:
    return app.main.query_one(ViewStrip)


def row(app) -> str:
    return app.screen._compositor.render_strips()[strip_of(app).region.y].text


def find(app, text):
    y = strip_of(app).region.y
    x = row(app).find(text)
    assert x >= 0, f"{text!r} is not on the strip: {row(app)!r}"
    return (x, y)


def shown_tabs(app) -> list[str]:
    return [t.view for t in app.query(ViewTab) if t.display]


def count_text(app) -> str:
    return str(app.query_one("#search-count", Static).content)


async def until(pilot, check, timeout: float = 10.0) -> bool:
    """Wait for check() to pass; the list counts on its own timer, which load can slow."""
    end = time.monotonic() + timeout
    while not check():
        if time.monotonic() > end:
            return False
        await pilot.pause(0.05)
    return True


def first_result(app):
    ins, st = app.data.insights, app.state.view_state()
    sec = views.sections(ins, st, app.state.collapsed)[0]
    return sec["groups"][0]["skills"][0]["path"] if sec["groups"] else sec["rows"][0]["path"]


# Pure helpers


def test_placeholder_cuts_at_a_comma():
    assert fit_placeholder(40) == PLACEHOLDER
    assert fit_placeholder(SEARCH - 4) == "Search skills, sources"
    assert fit_placeholder(14) == "Search skills"
    assert fit_placeholder(5) == ""
    assert cell_len(fit_placeholder(SEARCH_WIDE - 4)) <= SEARCH_WIDE - 4


def test_window_keeps_the_active_tab_in_view():
    widths = [10] * 8
    assert window(widths, 0, 40) == (0, 3)
    i, j = window(widths, 7, 40)
    assert i <= 7 < j and j == 8
    i, j = window(widths, 4, 40)
    assert i <= 4 < j


def test_glyphs_are_one_cell_and_css_uses_tokens_only():
    for glyph in ("‹", "›", "✕", "–", "·", "/"):
        assert cell_len(glyph) == 1
    for cls in (viewstrip.ViewTab, viewstrip.ViewEdge, ViewMenu, SearchInput, SearchBox, ViewStrip):
        css = cls.DEFAULT_CSS
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b(?!-)", css)
        assert not re.search(r"\b(reverse|italic|underline|bold|dim|strike|heavy|double)\b", css)


# Tabs


@pytest.mark.asyncio
async def test_tabs_follow_the_view_rules_with_counts(demo):
    async with demo.run_test(size=HUGE) as pilot:
        await settle(pilot)
        ins, st = demo.data.insights, demo.state.view_state()
        assert shown_tabs(demo) == views.shown_views(ins, st)
        text = row(demo)
        for tab in views.view_tabs(ins, st):
            assert re.search(rf"{tab['label']} +{tab['count']}\b", text), tab
        assert demo.query_one("#tab-all").has_class("-active")
        assert "Skills with SKILL.md problems" in str(demo.query_one("#tab-issues").tooltip)
        assert "Press 5" in str(demo.query_one("#tab-issues").tooltip)
        assert "Press 9" in str(demo.query_one("#tab-review").tooltip)
        assert re.search(r"Updates \d+ +Issues \d+ +New \d+", text)


@pytest.mark.asyncio
async def test_click_a_tab_and_press_it_with_the_mouse(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.click(offset=find(demo, "Off"))
        assert demo.state.view == "off"
        assert demo.query_one("#tab-off").has_class("-active")
        assert not demo.query_one("#tab-all").has_class("-active")
        await pilot.mouse_down("#tab-updates")
        assert demo.query_one("#tab-updates").has_class("-pressed")
        await pilot.mouse_up("#tab-updates")
        assert not demo.query_one("#tab-updates").has_class("-pressed")
        await pilot.hover("#tab-on")
        await pilot.pause()
        assert demo.query_one("#tab-on").mouse_hover


@pytest.mark.asyncio
async def test_digit_keys_move_the_active_tab(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("3")
        assert demo.state.view == "off"
        assert demo.query_one("#tab-off").has_class("-active")
        await pilot.press("9")
        assert demo.state.view == "review"
        assert demo.query_one("#tab-review").has_class("-active")
        await pilot.press("1")
        assert demo.query_one("#tab-all").has_class("-active")


@pytest.mark.asyncio
async def test_a_hidden_view_shows_while_it_is_active(demo):
    async with demo.run_test(size=HUGE) as pilot:
        await settle(pilot)
        assert "costly" not in shown_tabs(demo) and "similar" not in shown_tabs(demo)
        demo.set_state(view="similar")
        await pilot.pause()
        assert "similar" in shown_tabs(demo)
        assert re.search(r"Similar +Review", row(demo))
        assert "Press" not in str(demo.query_one("#tab-similar").tooltip)
        demo.set_state(view="all")
        await pilot.pause()
        assert "similar" not in shown_tabs(demo)


@pytest.mark.asyncio
async def test_counts_hold_their_cells_when_a_digit_changes(prefs):
    atlas = SwitchAtlas(n=100)
    app = AtlasApp(atlas)
    async with app.run_test(size=HUGE) as pilot:
        await settle(pilot)
        assert re.search(r"On 100 +Off +0\b", row(app))
        before = {label: find(app, label)[0] for label in ("On", "Off", "Updates", "Unused")}
        atlas.off = ["skill-000"]
        app.reload(["scan"])
        await settle(pilot)
        assert re.search(r"On +99 +Off +1\b", row(app))
        after = {label: find(app, label)[0] for label in before}
        assert after == before


@pytest.mark.asyncio
async def test_unused_waits_until_usage_is_read(prefs):
    app = AtlasApp(SwitchAtlas(n=12, usage="indexing"))
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        unused = app.query_one("#tab-unused", ViewTab)
        assert unused.has_class("-waiting")
        assert re.search(r"Unused +–", row(app))
        assert WAIT in str(unused.tooltip)
        await pilot.click("#tab-unused")
        assert app.state.view == "all"


@pytest.mark.asyncio
async def test_tabs_show_dashes_before_the_scan(prefs):
    atlas = SwitchAtlas(n=12)
    atlas.gate = threading.Event()
    app = AtlasApp(atlas)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        assert shown_tabs(app) == list(viewstrip.FIRST)
        assert re.search(r"All +– +On +– +Off +–", row(app))
        atlas.gate.set()
        await settle(pilot)
        assert re.search(r"All +12 +On +12", row(app))


# Meta notes


@pytest.mark.asyncio
async def test_meta_says_where_the_switches_write(demo):
    async with demo.run_test(size=HUGE) as pilot:
        await settle(pilot)
        notes = views.header_meta(demo.data.insights, demo.state.harness)
        assert " · ".join(notes) in row(demo)
        demo.set_state(harness="all")
        await pilot.pause()
        assert "pick a harness to switch skills" in row(demo)


@pytest.mark.asyncio
async def test_meta_drops_when_the_row_is_short(demo):
    async with demo.run_test(size=NARROW) as pilot:
        await settle(pilot)
        assert not demo.query_one("#meta").display
        assert "writes" not in row(demo)


# Search: keys


@pytest.mark.asyncio
async def test_slash_focuses_the_search_and_selects_the_old_text(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        box = demo.query_one(SearchInput)
        await pilot.press("slash", *"seo")
        assert demo.focused is box and demo.state.query == "seo"
        await pilot.press("enter")
        assert demo.focused is not box
        await pilot.press("slash")
        assert demo.focused is box
        assert (box.selection.start, box.selection.end) == (0, 3)
        await pilot.press(*"ads")
        assert box.value == "ads" and demo.state.query == "ads"


@pytest.mark.asyncio
async def test_typing_filters_at_once_and_counts_the_results(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("slash", *"seo")
        assert demo.state.query == "seo"
        ins, st = demo.data.insights, demo.state.view_state()
        n = len(views.visible_skills(ins, st))
        n += sum(len(views.avail_shown(ins, st, r)) for r in demo.data.available)
        assert await until(pilot, lambda: count_text(demo) in (str(n), views.plural(n, "result")))
        assert demo.query_one(SearchBox).has_class("-filled")


@pytest.mark.asyncio
async def test_esc_clears_the_text_then_leaves_the_box(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        box = demo.query_one(SearchInput)
        await pilot.press("slash", *"seo", "escape")
        assert box.value == "" and demo.state.query == ""
        assert demo.focused is box
        await pilot.press("escape")
        assert demo.focused is demo.query_one("#list")


@pytest.mark.asyncio
async def test_enter_and_down_go_to_the_first_result(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("slash", *"seo", "enter")
        assert demo.focused is demo.query_one("#list")
        assert demo.state.selected == first_result(demo)
        demo.set_state(selected=None)
        await pilot.press("slash", "down")
        assert demo.focused is demo.query_one("#list")
        assert demo.state.selected == first_result(demo)


@pytest.mark.asyncio
async def test_enter_with_no_result_keeps_the_selection(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        before = demo.state.selected
        await pilot.press("slash", *"zzzqqq", "enter")
        assert demo.state.selected == before
        assert await until(pilot, lambda: count_text(demo) in ("0", "0 results"))


@pytest.mark.asyncio
async def test_a_query_set_elsewhere_shows_in_the_box(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        demo.set_state(query="ads")
        await pilot.pause()
        assert demo.query_one(SearchInput).value == "ads"
        demo.set_state(query="")
        await pilot.pause()
        assert demo.query_one(SearchInput).value == ""
        assert not demo.query_one(SearchBox).has_class("-filled")


# Search: mouse


@pytest.mark.asyncio
async def test_mouse_clicks_the_box_and_the_clear_cell(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.click("#search-icon")
        box = demo.query_one(SearchInput)
        assert demo.focused is box
        await pilot.press(*"seo")
        await pilot.click("#list")
        assert demo.focused is not box and demo.state.query == "seo"
        clear = demo.query_one("#search-clear")
        await pilot.mouse_down(clear)
        assert clear.has_class("-pressed")
        await pilot.mouse_up(clear)
        assert not clear.has_class("-pressed")
        await pilot.click(offset=find(demo, "✕"))
        assert box.value == "" and demo.state.query == ""
        assert demo.focused is not box


@pytest.mark.asyncio
async def test_the_count_comes_from_the_list(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        demo.set_state(query="skill")
        await pilot.pause()
        strip_of(demo).on_skill_list_results_changed(SkillList.ResultsChanged(7))
        assert count_text(demo) in ("7", "7 results")
        demo.set_state(query="")
        assert await until(pilot, lambda: count_text(demo) == "")


@pytest.mark.asyncio
async def test_box_width_follows_the_window(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        box = demo.query_one(SearchBox)
        assert box.size.width == SEARCH and not box.has_class("-folded")
        assert demo.query_one(SearchInput).placeholder == "Search skills, sources"
        await pilot.resize_terminal(*HUGE)
        await settle(pilot)
        assert box.size.width == SEARCH_WIDE
        assert demo.query_one(SearchInput).placeholder == PLACEHOLDER


# Back to All (P47)


@pytest.mark.asyncio
async def test_show_all_from_an_empty_list_focuses_the_all_tab(prefs):
    app = AtlasApp(SwitchAtlas(n=12))
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.set_state(view="issues")
        await pilot.pause()
        assert app.focused is app.query_one("#list")
        app.set_state(view="all")
        await pilot.pause()
        tab = app.query_one("#tab-all", ViewTab)
        assert app.focused is tab
        await pilot.press("right")
        assert app.state.view == "on" and app.focused is app.query_one("#tab-on")
        await pilot.press("left")
        assert app.state.view == "all" and app.focused is tab
        await pilot.press("down")
        assert app.focused is app.query_one("#list")
        assert not any(isinstance(w, ViewTab) for w in app.screen.focus_chain)


@pytest.mark.asyncio
async def test_show_all_skills_click_in_the_empty_list_focuses_the_tab(prefs):
    app = AtlasApp(SwitchAtlas(n=12))
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.set_state(view="issues")
        await settle(pilot)
        lines = [s.text for s in app.screen._compositor.render_strips()]
        y = next(i for i, line in enumerate(lines) if "Show all skills" in line)
        await pilot.click(offset=(lines[y].find("Show all skills") + 2, y))
        await pilot.pause()
        assert app.state.view == "all"
        assert app.focused is app.query_one("#tab-all")


@pytest.mark.asyncio
async def test_a_digit_from_a_list_with_rows_keeps_focus_in_the_list(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("3")
        await pilot.press("1")
        assert demo.state.view == "all"
        assert demo.focused is demo.query_one("#list")


# Narrow


@pytest.mark.asyncio
async def test_narrow_search_folds_to_a_cell_and_takes_the_row(demo):
    async with demo.run_test(size=NARROW) as pilot:
        await settle(pilot)
        strip, box = strip_of(demo), demo.query_one(SearchBox)
        assert box.has_class("-folded") and box.size.width == 3
        await pilot.click(SearchBox)
        assert strip.has_class("-open") and demo.focused is demo.query_one(SearchInput)
        assert not demo.query_one("#tabs").display
        await pilot.press(*"seo")
        await pilot.click("#list")
        assert not strip.has_class("-open") and box.has_class("-folded")
        assert "seo" in row(demo) and "All" in row(demo)
        await pilot.click("#search-clear")
        assert demo.state.query == "" and box.size.width == 3


@pytest.mark.asyncio
async def test_narrow_slash_and_esc_open_and_close_the_search(demo):
    async with demo.run_test(size=NARROW) as pilot:
        await settle(pilot)
        strip = strip_of(demo)
        await pilot.press("slash")
        assert strip.has_class("-open")
        await pilot.press("escape")
        assert not strip.has_class("-open")
        assert demo.focused is demo.query_one("#list")


@pytest.mark.asyncio
async def test_narrow_tabs_keep_the_active_one_in_view(demo):
    async with demo.run_test(size=NARROW) as pilot:
        await settle(pilot)
        assert demo.query_one("#edge-right").display
        assert not demo.query_one("#edge-left").display
        demo.set_state(view="review")
        await pilot.pause()
        assert demo.query_one("#tab-review").display
        assert demo.query_one("#edge-left").display
        assert "Review" in row(demo)


@pytest.mark.asyncio
async def test_edge_opens_a_menu_of_every_view_mouse(demo):
    async with demo.run_test(size=NARROW) as pilot:
        await settle(pilot)
        await pilot.click("#edge-right")
        await pilot.pause()
        assert isinstance(demo.screen, ViewMenu)
        menu = demo.screen.query_one(OptionList)
        ids = [menu.get_option_at_index(i).id for i in range(menu.option_count)]
        assert ids == views.shown_views(demo.data.insights, demo.state.view_state())
        lines = [s.text for s in demo.screen._compositor.render_strips()]
        assert any(re.search(r"Review +\d+ +9 ", line) for line in lines)
        await pilot.click(OptionList, offset=(2, 1 + ids.index("review")))
        await pilot.pause()
        assert not isinstance(demo.screen, ViewMenu)
        assert demo.state.view == "review"


@pytest.mark.asyncio
async def test_menu_keys_pick_a_view_or_close(demo):
    async with demo.run_test(size=NARROW) as pilot:
        await settle(pilot)
        await pilot.click("#edge-right")
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert demo.state.view == "off"
        await pilot.click("#edge-right")
        await pilot.pause()
        await pilot.press("9")
        await pilot.pause()
        assert demo.state.view == "review"
        await pilot.click("#edge-left")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(demo.screen, ViewMenu) and demo.state.view == "review"


# Marks


@pytest.mark.asyncio
async def test_the_strip_hides_for_marks_and_comes_back_current(prefs):
    atlas = SwitchAtlas(n=100)
    app = AtlasApp(atlas)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        y = strip_of(app).region.y
        await pilot.press("slash", *"skill")
        app.set_state(marked={app.data.skills[0]["path"]})
        await pilot.pause()
        assert not strip_of(app).display
        assert app.focused is app.query_one("#list")
        await pilot.press("slash")
        assert app.focused is app.query_one("#list")
        atlas.off = ["skill-000", "skill-001"]
        app.reload(["scan"])
        await settle(pilot)
        app.set_state(marked=frozenset())
        await pilot.pause()
        assert strip_of(app).display and strip_of(app).region.y == y
        assert re.search(r"On +98 +Off +2\b", row(app))
        assert app.query_one(SearchInput).value == "skill"


# Performance


@pytest.mark.asyncio
async def test_typing_and_load_starts_do_not_redraw_the_tabs(demo, monkeypatch):
    draws = []
    real = ViewStrip._draw
    monkeypatch.setattr(ViewStrip, "_draw", lambda self: draws.append(1) or real(self))
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        draws.clear()
        await pilot.press("slash", *"seo", "backspace", "escape")
        await pilot.pause()
        demo.broadcast(lambda: LoadStarted("usage"))
        await pilot.pause()
        assert draws == []


@pytest.mark.asyncio
async def test_tab_counts_come_from_the_shared_memo(demo, monkeypatch):
    calls = []
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        real = demo.data.counts
        monkeypatch.setattr(demo.data, "counts", lambda st: calls.append(st) or real(st))
        await pilot.press("2")
        await pilot.pause()
        assert calls and calls[-1].harness == demo.state.harness


@pytest.mark.asyncio
async def test_a_key_in_the_search_is_cheap_at_2000_skills(prefs):
    app = AtlasApp(DemoAtlas(n=2000, now=NOW))
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("slash")
        strip = strip_of(app)
        app.set_state(query="co")
        start = time.perf_counter()
        strip._fit()
        strip.show_results()
        assert time.perf_counter() - start < 0.05
