import sys
import types
from datetime import datetime, timezone

import pytest

from skill_atlas.core import views
from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui import state, theme
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.messages import DataChanged
from skill_atlas.tui.widgets import sidepanel
from skill_atlas.tui.widgets.sidepanel import (
    ALL_CLEAR,
    Check,
    Choice,
    Pane,
    SideChart,
    SidePanel,
    Stat,
    open_display,
    section_open,
    with_section,
)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
TALL, SHORT = (140, 40), (120, 26)


@pytest.fixture
def app(prefs):
    return AtlasApp(DemoAtlas(now=NOW))


@pytest.fixture
def calls(monkeypatch):
    """Stub modules for profiles, transfer, and help. Each call lands in the returned list."""
    seen: list[tuple] = []

    def stub(module: str, *names: str) -> None:
        mod = types.ModuleType(module)
        for name in names:

            async def fn(app, *args, _name=name):
                seen.append((_name, *args))

            setattr(mod, name, fn)
        monkeypatch.setitem(sys.modules, module, mod)

    stub("skill_atlas.tui.screens.profiles", "apply_profile", "save_profile", "open_profiles")
    stub(
        "skill_atlas.tui.screens.transfer",
        "open_export",
        "copy_manifest",
        "open_import",
        "open_restore",
    )
    stub("skill_atlas.tui.screens.help", "open_help")
    return seen


def text_of(widget) -> str:
    return "\n".join(line.plain for line in widget.lines(widget.size.width or 48))


def words(widget) -> str:
    """The widget's text with its wrapping and padding taken out."""
    return " ".join(text_of(widget).split())


async def click(pilot, selector: str, offset=(3, 0)) -> None:
    """Scroll the widget into view, then click it."""
    widget = pilot.app.query_one(selector)
    widget.scroll_visible(animate=False)
    await pilot.pause()
    await pilot.click(selector, offset=offset)
    await settle(pilot)


async def open_section(pilot, key: str) -> Pane:
    app = pilot.app
    app.set_state(folded=with_section(app.state.folded, key, True))
    await settle(pilot)
    return app.query_one("#side-" + key.replace(".", "-"), Pane)


def test_a_saved_choice_wins_over_the_default():
    folded = frozenset()
    assert section_open(folded, "inv.use", True)
    assert not section_open(folded, "inv.cost", False)
    folded = with_section(folded, "inv.use", False)
    assert folded == {"inv.use"} and not section_open(folded, "inv.use", True)
    folded = with_section(folded, "inv.use", True)
    assert folded == {"inv.use:open"} and section_open(folded, "inv.use", False)


@pytest.mark.asyncio
async def test_the_stats_and_title_come_from_views(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        ins, harness = app.data.insights, app.state.harness
        inv = views.inventory(ins, harness)
        for name in ("on", "off", "updates", "untracked", "duplicates", "edited"):
            assert app.query_one(f"#side-stat-{name}", Stat).value == inv[name]
        title = text_of(app.query_one("#side-title"))
        assert "Inventory" in title and app.data.harnesses[harness]["label"] in title


@pytest.mark.asyncio
async def test_needs_attention_lists_each_item_with_its_glyph(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        ins = app.data.insights
        assert ins.missing == 1
        items = views.attention(ins, app.state.view_state())
        assert {i["key"] for i in items} >= {"a-store", "a-sec", "a-miss"}
        for item in items:
            row = app.query_one(f"#side-{item['key']}")
            text = text_of(row)
            glyph = "✗" if item["tone"] == "danger" else "!"
            assert text.lstrip().startswith(glyph)
            assert item["detail"].split()[0] in text


@pytest.mark.asyncio
async def test_show_them_opens_the_view_with_the_mouse(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await click(pilot, "#side-a-sec")
        assert app.state.view == "review"
        await click(pilot, "#side-a-prob")
        assert app.state.view == "issues"


@pytest.mark.asyncio
async def test_the_keyboard_tabs_in_and_moves_with_up_and_down(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pilot.press("tab")
        assert app.focused.id == "side-inv-attn-head"
        await pilot.press("down")
        first = app.focused.id
        await pilot.press("j", "k")
        assert app.focused.id == first
        await pilot.press("up")
        assert app.focused.id == "side-inv-attn-head"
        while app.focused.id != "side-a-prob":
            await pilot.press("down")
        await pilot.press("enter")
        await settle(pilot)
        assert app.state.view == "issues"
        await pilot.press("escape")
        assert app.focused is app.query_one("#list")


@pytest.mark.asyncio
async def test_store_problems_fold_open_under_their_row(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        problems = app.data.scan["health"]["problems"]
        assert not app.query("#side-health-0")
        await click(pilot, "#side-a-store")
        shown = [w for w in app.query("Line") if (w.id or "").startswith("side-health-")]
        assert len(shown) == len(problems)
        assert problems[0]["message"].split()[0] in text_of(app.query_one("#side-health-0"))
        assert app.focused.id == "side-a-store"
        await pilot.press("space")
        await settle(pilot)
        assert not app.query("#side-health-0")
        assert app.focused.id == "side-a-store"


@pytest.mark.asyncio
async def test_restore_runs_from_the_row_and_the_skill_set(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        assert "Restore it" in text_of(app.query_one("#side-a-miss"))
        await click(pilot, "#side-a-miss")
        await open_section(pilot, "inv.set")
        await click(pilot, "#side-set-restore", offset=(1, 0))
        assert calls == [("open_restore",), ("open_restore",)]


@pytest.mark.asyncio
async def test_a_section_folds_and_the_app_remembers_it(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        use = app.query_one("#side-inv-use", Pane)
        assert use.open and app.query("#side-top")
        await click(pilot, "#side-inv-use-head")
        assert "inv.use" in app.state.folded and not use.open
        uses = views.inventory(app.data.insights, app.state.harness)["uses"]
        assert views.uses_text(uses) in text_of(use.head)
        app.query_one("#side-inv-use-head").focus()
        await pilot.press("enter")
        await settle(pilot)
        assert "inv.use:open" in app.state.folded and use.open


@pytest.mark.asyncio
async def test_a_folded_section_that_needs_you_shows_a_flag(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        attn = app.query_one("#side-inv-attn", Pane)
        assert "things to check" not in text_of(attn.head)
        await click(pilot, "#side-inv-attn-head")
        head = text_of(attn.head)
        assert "✗" in head and "things to check" in head
        assert "!" in text_of(app.query_one("#side-inv-ovl-head"))


@pytest.mark.asyncio
async def test_a_short_window_starts_every_section_folded(app):
    async with app.run_test(size=SHORT) as pilot:
        await settle(pilot)
        assert not any(p.open for p in app.query(Pane))
        await click(pilot, "#side-inv-use-head")
        assert app.query_one("#side-inv-use", Pane).open
        assert not app.query("#side-heat")
        assert "uses on" in text_of(app.query_one("#side-inv-use-body").children[1])


@pytest.mark.asyncio
async def test_a_top_used_row_selects_its_skill(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        ins = app.data.insights
        top = views.top_used(ins, views.loaded_skills(ins, app.state.harness))
        chart = app.query_one("#side-top", SideChart)
        assert [n for _, n in chart.rows] == [views.uses(ins, s) for s in top]
        chart.scroll_visible(animate=False)
        await pilot.hover("#side-top", offset=(4, 1))
        assert chart.tooltip == f"Show /{top[1].get('invoke') or top[1]['name']}"
        await click(pilot, "#side-top", offset=(4, 1))
        assert app.state.selected == top[1]["path"]
        assert not app.query_one(SidePanel).display


@pytest.mark.asyncio
async def test_the_keyboard_moves_through_a_chart_and_picks_a_row(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        chart = app.query_one("#side-top", SideChart)
        app.query_one("#side-inv-use-head").focus()
        # The heatmap takes the keys between the head and the chart; it moves by day.
        for _ in range(10):
            await pilot.press("down")
            if app.focused is chart:
                break
        assert app.focused is chart and chart.cursor == 0
        await pilot.press("down", "down")
        assert chart.cursor == 2
        await pilot.press("up", "up", "up")
        assert app.focused is app.query_one("#side-heat")
        await pilot.press("down", "down", "space")
        await settle(pilot)
        ins = app.data.insights
        top = views.top_used(ins, views.loaded_skills(ins, app.state.harness))
        assert app.state.selected == top[1]["path"]


class Indexing(DemoAtlas):
    def usage(self):
        return {"status": "indexing", "error": None, "progress": [40, 120], "skills": {}}


class Broken(DemoAtlas):
    def usage(self):
        raise OSError("the sessions folder is locked")

    def profiles(self):
        raise OSError("profiles.json is not valid JSON")


@pytest.mark.asyncio
async def test_usage_shows_its_progress_while_it_reads(prefs):
    app = AtlasApp(Indexing(now=NOW))
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        body = app.query_one("#side-inv-use-body")
        assert "Reading your agent sessions… 40 of 120" in words(body.children[0])
        await click(pilot, "#side-inv-use-head")
        assert "Reading sessions…" in text_of(app.query_one("#side-inv-use-head"))


@pytest.mark.asyncio
async def test_usage_and_profiles_show_their_failures(prefs):
    app = AtlasApp(Broken(now=NOW))
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        body = app.query_one("#side-inv-use-body")
        assert words(body.children[0]) == "✗ Could not read usage: the sessions folder is locked."
        await click(pilot, "#side-inv-use-head")
        assert "✗ Could not read usage" in text_of(app.query_one("#side-inv-use-head"))
        prof = await open_section(pilot, "inv.prof")
        assert "Could not read the profiles." in text_of(prof.body.children[0])
        assert app.query("#side-prof-retry")


@pytest.mark.asyncio
async def test_nothing_to_do_shows_the_web_copy(app, monkeypatch):
    monkeypatch.setattr(views, "attention", lambda ins, st: [])
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        assert words(app.query_one("#side-a-ok")) == f"✓ {ALL_CLEAR}"
        await click(pilot, "#side-inv-attn-head")
        assert "Nothing to do" in text_of(app.query_one("#side-inv-attn-head"))


@pytest.mark.asyncio
async def test_context_cost_rows_select_a_skill_or_a_harness(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.cost")
        cost = views.context_cost(app.data.insights, app.state.harness)
        chart = app.query_one("#side-cost-top", SideChart)
        assert chart.texts == [views.approx(s["tokens_listed"]) for s in cost["top"]]
        await click(pilot, "#side-cost-top", offset=(4, 0))
        assert app.state.selected == cost["top"][0]["path"]
        app.set_state(selected=None, harness="all")
        await settle(pilot)
        per = views.context_cost(app.data.insights, "all")["per_harness"]
        chart = app.query_one("#side-cost-per", SideChart)
        assert chart.texts[0] == f"{views.approx(per[0]['total'])} · {per[0]['count']} on"
        assert "Pick a harness" in text_of(app.query_one("#side-inv-cost-body").children[2])
        await click(pilot, "#side-cost-per", offset=(4, 1))
        assert app.state.harness == per[1]["id"]


@pytest.mark.asyncio
async def test_overlap_and_security_open_their_views(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.ovl")
        await click(pilot, "#side-ovl-similar", offset=(1, 0))
        assert app.state.view == "similar"
        await click(pilot, "#side-ovl-diverged", offset=(1, 0))
        assert app.state.view == "diverged"
        await open_section(pilot, "inv.sec")
        await click(pilot, "#side-sec-review")
        assert app.state.view == "review"


@pytest.mark.asyncio
async def test_profiles_apply_save_and_manage(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.prof")
        names = [p["name"] for p in app.atlas.profiles()["profiles"]]
        row = text_of(app.query_one("#side-prof-0"))
        assert names[0] in row and "Apply…" in row and " on · " in row
        await click(pilot, "#side-prof-1")
        app.query_one("#side-prof-0").focus()
        await pilot.press("enter")
        await settle(pilot)
        await click(pilot, "#side-prof-save")
        await click(pilot, "#side-prof-manage")
        assert calls == [
            ("apply_profile", names[1]),
            ("apply_profile", names[0]),
            ("save_profile",),
            ("open_profiles",),
        ]


@pytest.mark.asyncio
async def test_skill_set_buttons_run_transfer(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.set")
        for name in ("export", "copy", "import"):
            await click(pilot, f"#side-set-{name}", offset=(1, 0))
        assert calls == [("open_export",), ("copy_manifest",), ("open_import",)]


@pytest.mark.asyncio
async def test_display_changes_apply_at_once_with_the_mouse(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.disp")
        mode = app.query_one("#side-disp-mode", Choice)
        mode.scroll_visible(animate=False)
        await pilot.pause()
        y, x0, _, _ = next(h for h in mode._hits if h[3] == "light")
        await click(pilot, "#side-disp-mode", offset=(x0 + 1, y))
        assert app.state.mode == "light" and app.theme == "atlas-light"
        swatches = app.query_one("#side-disp-palette", Choice)
        y, x0, _, _ = next(h for h in swatches._hits if h[3] == "sage")
        await pilot.hover("#side-disp-palette", offset=(x0 + 1, y))
        assert swatches.tooltip == "Sage"
        await click(pilot, "#side-disp-palette", offset=(x0 + 1, y))
        assert app.state.palette == "sage" and app.theme == "sage-light"
        sort = app.query_one("#side-disp-sort", Choice)
        y, x0, _, _ = next(h for h in sort._hits if h[3] == "cost")
        await click(pilot, "#side-disp-sort", offset=(x0 + 1, y))
        assert app.state.sort == "cost"
        for setting in ("compact", "show_project", "show_stale", "key_hints"):
            before = getattr(app.state, setting)
            await click(pilot, "#side-disp-" + setting.replace("_", "-"))
            assert getattr(app.state, setting) is not before
        motion = app.query_one("#side-disp-motion", Choice)
        assert [v for v, _ in motion.options] == list(state.MOTIONS)
        y, x0, _, _ = next(h for h in motion._hits if h[3] == "off")
        await click(pilot, "#side-disp-motion", offset=(x0 + 1, y))
        assert app.state.motion == "off" and app.animation_level == "none"


@pytest.mark.asyncio
async def test_display_changes_apply_at_once_with_the_keys(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.disp")
        app.query_one("#side-disp-group", Choice).focus()
        await pilot.press("right")
        assert app.state.group_by == "type"
        await pilot.press("enter")
        assert app.state.group_by == "source"
        await pilot.press("down", "left")
        assert app.state.sort == views.SORTS[-1]
        await pilot.press("down", "right")
        assert app.state.group_size == "large"
        await pilot.press("down", "right")
        assert app.state.motion == "reduced"
        await pilot.press("down", "space")
        assert app.state.compact
        assert isinstance(app.focused, Check)


@pytest.mark.asyncio
async def test_open_display_shows_the_panel_and_focuses_display(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        path = app.data.skills[0]["path"]
        app.set_state(selected=path)
        await settle(pilot)
        await open_display(app)
        await settle(pilot)
        assert app.state.selected is None
        assert app.query_one("#side-inv-disp", Pane).open
        assert app.focused.id == "side-inv-disp-head"
        assert section_open(app.state.folded, "inv.disp", False)


@pytest.mark.asyncio
async def test_open_display_opens_the_drawer_when_narrow(app):
    async with app.run_test(size=(90, 30)) as pilot:
        await settle(pilot)
        assert not app.detail_visible
        await open_display(app)
        await settle(pilot)
        assert app.detail_visible and app.focused.id == "side-inv-disp-head"


@pytest.mark.asyncio
async def test_the_keys_hint_opens_help(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await click(pilot, "#side-keys")
        assert calls == [("open_help",)]


@pytest.mark.asyncio
async def test_the_panel_waits_while_a_skill_is_selected(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        panel = app.query_one(SidePanel)
        app.set_state(selected=app.data.skills[0]["path"])
        await settle(pilot)
        app.set_state(harness="all")
        await settle(pilot)
        assert panel._dirty
        app.set_state(selected=None)
        await settle(pilot)
        assert not panel._dirty
        assert "All harnesses" in text_of(app.query_one("#side-title"))


def test_every_panel_glyph_is_one_cell():
    from rich.cells import cell_len

    for glyph in (*sidepanel.GLYPHS.values(), "▌", "▾", "▸", "●", "–"):
        assert cell_len(glyph) == 1


@pytest.mark.asyncio
async def test_links_are_muted_until_their_row_has_focus(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        row = app.query_one("#side-a-prob")
        assert row.tone("link").color == row.tone("muted").color
        row.focus()
        await pilot.pause()
        assert row.tone("link").color == row.tone("accent").color


@pytest.mark.asyncio
async def test_a_link_never_breaks_across_lines(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        row = app.query_one("#side-use-unused")
        for width in range(30, 60):
            lines = [line.plain.strip() for line in row.lines(width)]
            assert any("Show them" in line for line in lines), width
            assert not any(line.endswith("Show") for line in lines), width


@pytest.mark.asyncio
async def test_choice_options_wrap_inside_the_value_column(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.disp")
        sort = app.query_one("#side-disp-sort", Choice)
        assert len(sort.lines(40)) == 2
        starts = {y: min(x for yy, x, _, _ in sort._hits if yy == y) for y, *_ in sort._hits}
        assert starts == {0: 2 + sidepanel.LABEL_W, 1: 2 + sidepanel.LABEL_W}
        assert len(sort.lines(60)) == 1


@pytest.mark.asyncio
async def test_each_open_section_has_one_blank_row_around_it(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.disp")
        attn, use = app.query_one("#side-inv-attn"), app.query_one("#side-inv-use")
        folded, disp = app.query_one("#side-inv-set"), app.query_one("#side-inv-disp")
        keys = app.query_one("#side-keys")
        assert use.virtual_region.y - attn.virtual_region.bottom == 1
        assert disp.virtual_region.y - folded.virtual_region.bottom == 1
        assert keys.virtual_region.y - disp.virtual_region.bottom == 1


@pytest.mark.asyncio
async def test_the_drawer_has_an_edge_and_the_docked_panel_does_not(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        assert app.query_one(SidePanel).styles.border_left[0] in ("", "none")
    async with AtlasApp(DemoAtlas(now=NOW)).run_test(size=(90, 30)) as pilot:
        await settle(pilot)
        await open_display(pilot.app)
        await settle(pilot)
        assert pilot.app.query_one(SidePanel).styles.border_left[0] == "solid"


@pytest.mark.asyncio
async def test_switches_follow_the_theme(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.disp")
        check = app.query_one("#side-disp-key-hints", Check)
        dark = check.palette()["atlas-on"]
        app.set_state(mode="light")
        await settle(pilot)
        assert check.palette()["atlas-on"] == theme.colors(app)["atlas-on"] != dark


@pytest.mark.asyncio
async def test_display_marks_when_hidden_skills_show(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        head = app.query_one("#side-inv-disp-head")
        assert "Atlas · Dark" in text_of(head)
        app.set_state(show_project=True)
        await settle(pilot)
        assert "Project skills on" in text_of(head)
        app.set_state(show_stale=True)
        await settle(pilot)
        assert "Project, old versions on" in text_of(head)


@pytest.mark.asyncio
async def test_skill_set_says_what_import_asks_for(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        set_ = await open_section(pilot, "inv.set")
        assert words(set_.body.children[-1]) == sidepanel.IMPORT_NOTE


@pytest.mark.asyncio
async def test_the_details_panel_check_hides_the_panel(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.disp")
        assert app.query_one("#side-disp-panel", Check).on
        await click(pilot, "#side-disp-panel")
        assert not app.state.detail_open and not app.detail_visible
        assert app.focused is app.query_one("#list")
    async with AtlasApp(DemoAtlas(now=NOW)).run_test(size=(90, 30)) as pilot:
        await settle(pilot)
        await open_display(pilot.app)
        await settle(pilot)
        pilot.app.query_one("#side-disp-panel").focus()
        await pilot.press("space")
        await settle(pilot)
        assert not pilot.app.detail_visible


@pytest.mark.asyncio
async def test_the_system_theme_keeps_the_swatches_on_the_shown_shade(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.disp")
        mode = app.query_one("#side-disp-mode", Choice)
        assert [v for v, _ in mode.options] == ["system", "light", "dark"]
        y, x0, _, _ = next(h for h in mode._hits if h[3] == "system")
        await click(pilot, "#side-disp-mode", offset=(x0 + 1, y))
        assert app.state.mode == "system"
        shade = "dark" if app.current_theme.dark else "light"
        swatch = app.query_one("#side-disp-palette", Choice).option("sage", "Sage")
        want = theme.THEMES[f"sage-{shade}"].variables["atlas-accent"]
        assert swatch.style.color.get_truecolor().hex == want


@pytest.mark.asyncio
async def test_a_click_on_collections_sets_the_group_size(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await open_section(pilot, "inv.disp")
        size = app.query_one("#side-disp-size", Choice)
        assert [v for v, _ in size.options] == list(state.GROUP_SIZES)
        y, x0, _, _ = next(h for h in size._hits if h[3] == "large")
        await click(pilot, "#side-disp-size", offset=(x0 + 1, y))
        assert app.state.group_size == "large"


@pytest.mark.asyncio
async def test_a_click_on_a_folded_head_scrolls_the_section_into_view(app):
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot)
        side = app.query_one(SidePanel)
        head = app.query_one("#side-inv-disp-head")
        side.scroll_to_widget(head, animate=False, top=False)
        await pilot.pause()
        await click(pilot, "#side-inv-disp-head")
        await settle(pilot)
        body = app.query_one("#side-inv-disp-body")
        assert body.children and side.region.contains_region(body.children[0].region)
        assert side.region.contains_region(head.region)


@pytest.mark.asyncio
async def test_data_changes_redraw_once_after_a_short_wait(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        side = app.query_one(SidePanel)
        draws = []
        real = side.draw

        async def count(only=None):
            draws.append(only)
            await real(only)

        side.draw = count
        for _ in range(5):
            side.post_message(DataChanged(frozenset({"usage"})))
        await pilot.pause()
        assert draws == []
        await settle(pilot)
        assert draws == [None]


@pytest.mark.asyncio
async def test_focus_from_tab_scrolls_the_panel_without_animation(app):
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot)
        app.animation_level = "basic"
        side = app.query_one(SidePanel)
        keys = app.query_one("#side-keys")
        app.query_one("#side-inv-attn-head").focus()
        await pilot.pause()
        keys.focus()
        await pilot.pause()
        assert not app.animator.is_being_animated(side, "scroll_y")
        assert side.region.contains_region(keys.region)
