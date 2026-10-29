import re
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from rich.cells import cell_len
from textual.widgets import OptionList, Static

from skill_atlas.core import views
from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui import jobs, keys
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.messages import JobChanged, LoadStarted
from skill_atlas.tui.widgets import viewstrip
from skill_atlas.tui.widgets.skill_list import SkillList
from skill_atlas.tui.widgets.viewstrip import (
    PLACEHOLDER,
    SEARCH,
    SEARCH_WIDE,
    WAIT,
    SearchBox,
    SearchInput,
    ViewChip,
    ViewMenu,
    ViewStrip,
    fit_placeholder,
    open_view_menu,
)

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
HUGE, WIDE, MID, NARROW, TINY = (180, 50), (140, 40), (120, 36), (80, 24), (60, 20)
SHOW_ANOTHER = "Show another view · " + next(k.show for k in keys.KEYS if k.action == "view(1)")


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


def chip_of(app) -> ViewChip:
    return app.query_one(ViewChip)


def chip_text(app) -> str:
    return str(chip_of(app).render())


def row(app) -> str:
    return app.screen._compositor.render_strips()[strip_of(app).region.y].text


def find(app, text):
    y = strip_of(app).region.y
    x = row(app).find(text)
    assert x >= 0, f"{text!r} is not on the strip: {row(app)!r}"
    return (x, y)


def count_text(app) -> str:
    return str(app.query_one("#search-count", Static).content)


def menu_ids(app) -> list[str]:
    menu = app.screen.query_one(OptionList)
    return [menu.get_option_at_index(i).id for i in range(menu.option_count)]


def tab_of(app, view):
    ins, st = app.data.insights, app.state.view_state()
    return next(t for t in views.view_tabs(ins, st) if t["id"] == view)


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
    sec = views.sections(ins, st, app.state.folds())[0]
    return sec["groups"][0]["skills"][0]["path"] if sec["groups"] else sec["rows"][0]["path"]


# Pure helpers


def test_placeholder_cuts_at_a_comma():
    assert fit_placeholder(40) == PLACEHOLDER
    assert fit_placeholder(SEARCH - 4) == "Search skills, sources"
    assert fit_placeholder(14) == "Search skills"
    assert fit_placeholder(5) == ""
    assert cell_len(fit_placeholder(SEARCH_WIDE - 4)) <= SEARCH_WIDE - 4


def test_glyphs_are_one_cell_and_css_uses_tokens_only():
    for glyph in ("▾", "✕", "–", "/"):
        assert cell_len(glyph) == 1
    for cls in (ViewChip, ViewMenu, SearchInput, SearchBox, ViewStrip):
        css = cls.DEFAULT_CSS
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b(?!-)", css)
        assert not re.search(r"\b(reverse|italic|underline|bold|dim|strike|heavy|double)\b", css)


# The view chip


@pytest.mark.asyncio
async def test_one_chip_shows_the_active_view_and_its_count(demo):
    async with demo.run_test(size=HUGE) as pilot:
        await settle(pilot)
        n = tab_of(demo, "all")["count"]
        assert len(demo.query(ViewChip)) == 1
        assert chip_text(demo) == f"All {n} ▾" and f"All {n} ▾" in row(demo)
        for label in ("On", "Off", "Updates", "Issues", "Review"):
            assert not re.search(rf"\b{label} \d", row(demo)), label
        assert chip_of(demo).tooltip == SHOW_ANOTHER
        assert "writes" not in row(demo) and not demo.query("#meta")
        surface = demo.current_theme.variables["atlas-surface-3"].lower()
        assert chip_of(demo).styles.background.hex.lower() == surface


@pytest.mark.asyncio
async def test_digit_keys_change_the_chip(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("3")
        assert demo.state.view == "off"
        assert re.fullmatch(rf"Off {tab_of(demo, 'off')['count']} +▾", chip_text(demo))
        await pilot.press("9")
        assert demo.state.view == "review"
        assert chip_text(demo).startswith("Review ")
        assert "Skills with high-risk patterns" in str(chip_of(demo).tooltip)
        await pilot.press("1")
        assert chip_text(demo).startswith("All ")
        assert demo.focused is demo.query_one("#list")


@pytest.mark.asyncio
async def test_hover_press_and_click_the_chip_opens_the_view_menu(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        chip = chip_of(demo)
        assert chip.styles.background_tint.a == 0
        await pilot.hover(chip)
        await pilot.pause()
        assert chip.mouse_hover and chip.styles.background_tint.a > 0
        await pilot.mouse_down(chip)
        assert chip.has_class("-pressed") and chip.styles.background_tint.a > 0.1
        await pilot.mouse_up(chip)
        assert not chip.has_class("-pressed")
        await pilot.click(chip, button=3)
        await pilot.pause()
        assert not isinstance(demo.screen, ViewMenu)

        await pilot.click(chip)
        await pilot.pause()
        assert isinstance(demo.screen, ViewMenu)
        ids = menu_ids(demo)
        shown = {*views.shown_views(demo.data.insights, demo.state.view_state()), *viewstrip.MORE}
        assert ids == [v for v, _, _ in views.VIEWS if v in shown]
        menu = demo.screen.query_one(OptionList)
        assert menu.region.x == chip.region.x and menu.region.y == chip.region.bottom
        assert menu.highlighted == ids.index("all")
        lines = [s.text for s in demo.screen._compositor.render_strips()]
        n = tab_of(demo, "updates")["count"]
        assert any(re.search(rf"Updates +{n} +4 ", line) for line in lines)
        await pilot.click(OptionList, offset=(2, 1 + ids.index("review")))
        await pilot.pause()
        assert not isinstance(demo.screen, ViewMenu)
        assert demo.state.view == "review" and chip_text(demo).startswith("Review ")


@pytest.mark.asyncio
async def test_menu_keys_pick_a_view_or_close(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.click(ViewChip)
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert demo.state.view == "off"
        await pilot.click(ViewChip)
        await pilot.pause()
        await pilot.press("9")
        await pilot.pause()
        assert demo.state.view == "review"
        await pilot.click(ViewChip)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(demo.screen, ViewMenu) and demo.state.view == "review"
        await pilot.click(ViewChip)
        await pilot.pause()
        await pilot.click(offset=(WIDE[0] - 5, WIDE[1] - 3))
        await pilot.pause()
        assert not isinstance(demo.screen, ViewMenu) and demo.state.view == "review"


@pytest.mark.asyncio
async def test_the_menu_opens_by_key(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await demo.action_run("widgets.viewstrip:open_view_menu")
        await pilot.pause()
        assert isinstance(demo.screen, ViewMenu)
        await pilot.press("escape")
        await pilot.pause()
        open_view_menu(demo)
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        assert demo.state.view == "updates" and not isinstance(demo.screen, ViewMenu)


@pytest.mark.asyncio
async def test_the_menu_offers_costly_similar_and_diverged_with_counts(demo):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.click(ViewChip)
        await pilot.pause()
        assert set(viewstrip.MORE) <= set(menu_ids(demo))
        lines = [s.text for s in demo.screen._compositor.render_strips()]
        for view, label, _ in views.VIEWS:
            if view in viewstrip.MORE:
                st = replace(demo.state.view_state(), view=view)
                n = len(views.visible_skills(demo.data.insights, st))
                assert n and any(re.search(rf"{label} +{n} ", line) for line in lines), view
        await pilot.press("escape")
        demo.set_state(view="similar")
        await pilot.pause()
        n = len(views.visible_skills(demo.data.insights, demo.state.view_state()))
        assert chip_text(demo) == f"Similar {n} ▾"


@pytest.mark.asyncio
async def test_an_empty_view_leaves_the_menu_but_shows_while_active(prefs):
    app = AtlasApp(SwitchAtlas(n=12))
    async with app.run_test(size=HUGE) as pilot:
        await settle(pilot)
        await pilot.click(ViewChip)
        await pilot.pause()
        assert not {"similar", "diverged"} & set(menu_ids(app))
        await pilot.press("escape")
        app.set_state(view="similar")
        await pilot.pause()
        assert chip_text(app) == "Similar 0 ▾"
        assert chip_of(app).tooltip == SHOW_ANOTHER
        await pilot.click(ViewChip)
        await pilot.pause()
        assert "similar" in menu_ids(app)
        await pilot.press("escape")
        app.set_state(view="all")
        await pilot.pause()
        assert chip_text(app).startswith("All ")


# Update all


@pytest.mark.asyncio
async def test_the_updates_view_offers_update_all_and_names_the_skills_it_skips(demo, monkeypatch):
    ran = []
    monkeypatch.setattr(jobs, "update_all", lambda app: ran.append(app.state.harness))
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        button = demo.query_one("#update-all")
        assert not button.display and "Update" not in row(demo)
        await pilot.press("4")
        await pilot.pause()
        n, edited = viewstrip.update_plan(demo)
        assert n and edited == 1 and n + edited == tab_of(demo, "updates")["count"]
        assert button.display and str(button.render()) == f"Update {n}"
        assert "Skips 1 you edited" in row(demo)
        key = next(k.show for k in keys.KEYS if k.action == viewstrip.UPDATE_ALL)
        assert button.tooltip == f"Update each skill you did not edit · {key}"
        assert chip_of(demo).region.right < button.region.x
        assert button.region.right < demo.query_one(SearchBox).region.x
        await pilot.click(button, button=3)
        assert ran == []
        await pilot.click(button)
        await pilot.pause()
        assert ran == [demo.state.harness]
        items = {"a": {"state": "queued"}}
        demo.broadcast(lambda: JobChanged({"kind": "update", "done": False, "items": items}))
        await pilot.pause()
        assert not button.display and "Skips" not in row(demo)
        demo.broadcast(lambda: JobChanged(None))
        await pilot.pause()
        assert button.display
        await pilot.press("1")
        await pilot.pause()
        assert not button.display and "Skips" not in row(demo)


@pytest.mark.asyncio
async def test_update_all_reads_all_with_no_skips_and_hides_with_no_target(demo, monkeypatch):
    async with demo.run_test(size=WIDE) as pilot:
        await settle(pilot)
        demo.set_state(view="updates")
        await pilot.pause()
        button, note = demo.query_one("#update-all"), demo.query_one("#update-note")
        monkeypatch.setattr(viewstrip, "update_plan", lambda app: (3, 0))
        strip_of(demo)._draw()
        await pilot.pause()
        assert str(button.render()) == "Update all" and not note.display
        monkeypatch.setattr(viewstrip, "update_plan", lambda app: (0, 2))
        strip_of(demo)._draw()
        await pilot.pause()
        assert not button.display and "Skills you edited update one at a time" in row(demo)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [NARROW, TINY])
async def test_update_all_fits_a_narrow_strip(demo, size):
    async with demo.run_test(size=size) as pilot:
        await settle(pilot)
        demo.set_state(view="updates")
        await pilot.pause()
        button = demo.query_one("#update-all")
        assert button.display
        assert button.region.right <= demo.query_one(SearchBox).region.x
        assert "Update" in row(demo)


@pytest.mark.asyncio
async def test_the_chip_holds_its_width_when_a_count_loses_a_digit(prefs):
    atlas = SwitchAtlas(n=100)
    app = AtlasApp(atlas)
    async with app.run_test(size=HUGE) as pilot:
        await settle(pilot)
        app.set_state(view="on")
        await pilot.pause()
        assert chip_text(app) == "On 100 ▾"
        width = chip_of(app).size.width
        atlas.off = ["skill-000"]
        app.reload(["scan"])
        await settle(pilot)
        assert chip_text(app) == "On 99  ▾" and chip_of(app).size.width == width


@pytest.mark.asyncio
async def test_unused_waits_until_usage_is_read(prefs):
    app = AtlasApp(SwitchAtlas(n=12, usage="indexing"))
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.click(ViewChip)
        await pilot.pause()
        ids = menu_ids(app)
        menu = app.screen.query_one(OptionList)
        assert menu.get_option_at_index(ids.index("unused")).disabled
        await pilot.click(OptionList, offset=(2, 1 + ids.index("unused")))
        await pilot.pause()
        assert app.state.view == "all"
        await pilot.press("escape")
        await pilot.pause()
        app.set_state(view="unused")
        await pilot.pause()
        assert re.fullmatch(r"Unused – +▾", chip_text(app))
        assert WAIT in str(chip_of(app).tooltip)


@pytest.mark.asyncio
async def test_the_chip_shows_a_dash_before_the_scan(prefs):
    atlas = SwitchAtlas(n=12)
    atlas.gate = threading.Event()
    app = AtlasApp(atlas)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        assert re.fullmatch(r"All – +▾", chip_text(app))
        await pilot.click(ViewChip)
        await pilot.pause()
        assert menu_ids(app) == list(viewstrip.FIRST)
        await pilot.press("escape")
        atlas.gate.set()
        await settle(pilot)
        assert chip_text(app) == "All 12 ▾"


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
        assert box.region.right == WIDE[0] - 1
        await pilot.resize_terminal(*HUGE)
        await settle(pilot)
        assert box.size.width == SEARCH_WIDE
        assert demo.query_one(SearchInput).placeholder == PLACEHOLDER
        await pilot.resize_terminal(*NARROW)
        await settle(pilot)
        assert box.has_class("-folded") and box.size.width == 3


# Back to All (P47)


@pytest.mark.asyncio
async def test_show_all_from_an_empty_list_focuses_the_chip_and_its_keys_work(prefs):
    app = AtlasApp(SwitchAtlas(n=12))
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.set_state(view="issues")
        await pilot.pause()
        assert app.focused is app.query_one("#list")
        app.set_state(view="all")
        await pilot.pause()
        chip = chip_of(app)
        assert app.focused is chip
        focus = app.current_theme.variables["atlas-selection"].lower()
        assert chip.styles.background.hex.lower() == focus
        await pilot.press("right")
        assert app.state.view == "on" and app.focused is chip
        await pilot.press("left")
        assert app.state.view == "all" and app.focused is chip
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ViewMenu)
        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.state.view == "on" and app.focused is chip
        await pilot.press("space")
        await pilot.pause()
        assert isinstance(app.screen, ViewMenu)
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused is chip
        await pilot.press("down")
        assert app.focused is app.query_one("#list")
        assert not any(isinstance(w, ViewChip) for w in app.screen.focus_chain)


@pytest.mark.asyncio
async def test_show_all_skills_click_in_the_empty_list_focuses_the_chip(prefs):
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
        assert app.focused is chip_of(app)


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
@pytest.mark.parametrize("size", [NARROW, TINY])
async def test_narrow_widths_keep_the_chip_and_fold_the_search(demo, size):
    async with demo.run_test(size=size) as pilot:
        await settle(pilot)
        strip, box, chip = strip_of(demo), demo.query_one(SearchBox), chip_of(demo)
        demo.set_state(view="review")
        await pilot.pause()
        assert chip_text(demo).startswith("Review ") and "Review" in row(demo)
        assert box.has_class("-folded") and box.size.width == 3
        assert chip.region.right < box.region.x and box.region.right == size[0] - 1
        await pilot.click(chip)
        await pilot.pause()
        assert isinstance(demo.screen, ViewMenu)
        assert demo.screen.query_one(OptionList).region.right <= size[0]
        await pilot.press("1")
        await pilot.pause()
        assert demo.state.view == "all"
        await pilot.click(SearchBox)
        assert strip.has_class("-open") and demo.focused is demo.query_one(SearchInput)
        assert not demo.query_one("#views").display
        await pilot.press(*"seo")
        await pilot.click("#list")
        assert not strip.has_class("-open") and box.has_class("-folded")
        assert "seo" in row(demo) and "All" in row(demo) and "▾" in row(demo)
        await pilot.click("#search-clear")
        assert demo.state.query == "" and box.size.width == 3


@pytest.mark.asyncio
async def test_narrow_slash_and_esc_open_and_close_the_search(demo):
    async with demo.run_test(size=NARROW) as pilot:
        await settle(pilot)
        strip = strip_of(demo)
        await pilot.press("slash")
        assert strip.has_class("-open") and "▾" not in row(demo)
        await pilot.press("escape")
        assert not strip.has_class("-open")
        assert demo.focused is demo.query_one("#list")
        assert chip_text(demo) in row(demo)


# Marks


@pytest.mark.asyncio
async def test_the_strip_hides_for_marks_and_comes_back_current(prefs):
    atlas = SwitchAtlas(n=100)
    app = AtlasApp(atlas)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.set_state(view="on")
        await pilot.pause()
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
        assert chip_text(app) == "On 98  ▾" and "On 98  ▾" in row(app)
        assert app.query_one(SearchInput).value == "skill"


# Performance


@pytest.mark.asyncio
async def test_typing_and_load_starts_do_not_redraw_the_chip(demo, monkeypatch):
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
async def test_counts_come_from_the_shared_memo(demo, monkeypatch):
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
