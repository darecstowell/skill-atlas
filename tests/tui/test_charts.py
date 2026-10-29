from datetime import date, timedelta

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult

from skill_atlas.tui.widgets import charts, switch
from skill_atlas.tui.widgets.charts import BarChart, Heatmap
from skill_atlas.tui.widgets.switch import ToggleSwitch

COLORS = {
    "atlas-surface-1": "#121519",
    "atlas-surface-2": "#1a1f23",
    "atlas-surface-3": "#23282d",
    "atlas-text": "#eceff1",
    "atlas-muted": "#999fa6",
    "atlas-faint": "#595e63",
    "atlas-accent": "#6eb9f1",
    "atlas-border": "#23272b",
    "atlas-selection": "#24303a",
    "atlas-on": "#52cd86",
    "atlas-off": "#6d7277",
    "atlas-spark": "#a584dc",
    "atlas-heat-0": "#252a2f",
    "atlas-heat-1": "#1b3b52",
    "atlas-heat-2": "#246089",
    "atlas-heat-3": "#348bc5",
    "atlas-heat-4": "#53bbff",
    "atlas-warn": "#f2b966",
    "atlas-danger": "#fe8b83",
}
TODAY = date(2026, 10, 28)
CONSOLE = Console(color_system="truecolor")


def plain(text: Text) -> str:
    console = Console(record=True, width=80, color_system="truecolor")
    console.print(text, end="")
    return console.export_text()


def colors_of(text: Text) -> list[str | None]:
    """The hex color of each cell."""
    out = []
    for i in range(len(text.plain)):
        color = text.get_style_at_offset(CONSOLE, i).color
        out.append(color.get_truecolor().hex if color else None)
    return out


def tips_of(text: Text) -> list[str | None]:
    return [charts.tip_of(text.get_style_at_offset(CONSOLE, i)) for i in range(len(text.plain))]


def test_every_glyph_is_one_cell():
    glyphs = [
        charts.SPARK,
        charts.BASELINE,
        charts.EIGHTHS,
        charts.SPINNER,
        charts.LINE + charts.LINE_HALF + charts.LINE_TRACK,
        charts.CELL + charts.HOVER_CELL,
        *charts.SWITCH.values(),
        *(glyph for glyph, _, _ in charts.TAGS.values()),
    ]
    assert all(cell_len(g) == 1 for g in "".join(glyphs))


def test_spark_scales_to_peak_and_draws_zero_as_baseline():
    text = charts.spark([0, 1, 2, 4], 4, COLORS)
    assert plain(text) == "▁▃▄▇"
    assert colors_of(text) == [COLORS["atlas-faint"]] + [COLORS["atlas-spark"]] * 3


def test_spark_keeps_newest_weeks_and_pads_short_series():
    assert plain(charts.spark([9, 0, 0, 3], 2, COLORS)) == "▁▇"
    assert plain(charts.spark([3], 3, COLORS)) == "  ▇"


def test_spark_count_is_right_aligned_and_muted():
    text = charts.spark([1, 2], 2, COLORS, count=19, count_width=3)
    assert plain(text) == "▄▇  19"
    assert colors_of(text)[-1] == COLORS["atlas-muted"]
    assert plain(charts.spark([0, 0], 2, COLORS, count=0)) == "▁▁   "
    assert plain(charts.spark([5], 1, COLORS, count=1234)) == "▇ 1.2k"


def test_spark_dim_uses_faint():
    assert set(colors_of(charts.spark([1, 4], 2, COLORS, dim=True))) == {COLORS["atlas-faint"]}


def test_spark_week_tooltips():
    text = charts.spark([0, 2, 4], 3, COLORS, today=TODAY)
    assert tips_of(text) == [
        "Week of Oct 8 · no uses",
        "Week of Oct 15 · 2 uses",
        "Week of Oct 22 · 4 uses",
    ]
    assert tips_of(charts.spark([1], 1, COLORS)) == [None]


def test_switch_states():
    on, off, muted = COLORS["atlas-on"], COLORS["atlas-off"], COLORS["atlas-muted"]
    assert plain(charts.switch("on", COLORS)) == "━━●"
    assert plain(charts.switch(True, COLORS)) == "━━●"
    assert colors_of(charts.switch("on", COLORS)) == [on, on, on]
    assert plain(charts.switch(False, COLORS)) == "○━━"
    assert colors_of(charts.switch("off", COLORS)) == [muted, off, off]
    assert plain(charts.switch("mixed", COLORS)) == "━◐━"
    assert colors_of(charts.switch("mixed", COLORS)) == [off, on, off]


def test_switch_disabled_and_loading():
    disabled = charts.switch("on", COLORS, disabled=True)
    assert plain(disabled) == "○━━"
    assert colors_of(disabled) == [COLORS["atlas-faint"]] * 3
    assert tips_of(disabled) == [None] * 3
    loading = charts.switch("on", COLORS, loading=True)
    assert plain(loading) == "━━━"
    assert colors_of(loading) == [COLORS["atlas-surface-3"]] * 3


def test_switch_tooltips():
    assert set(tips_of(charts.switch("on", COLORS))) == {"Turn off"}
    assert set(tips_of(charts.switch("mixed", COLORS))) == {"Turn on"}
    assert set(tips_of(charts.switch("off", COLORS, tip="ads: turn on"))) == {"ads: turn on"}


def test_bar_eighths():
    assert plain(charts.bar(5, 10, 10, COLORS)) == "█████     "
    assert plain(charts.bar(55, 100, 10, COLORS)) == "█████▌    "
    assert plain(charts.bar(1, 1000, 4, COLORS)) == "▏   "
    assert plain(charts.bar(0, 10, 4, COLORS)) == "    "
    assert plain(charts.bar(20, 10, 4, COLORS)) == "████"
    assert plain(charts.bar(3, 0, 3, COLORS)) == "   "
    text = charts.bar(1, 2, 2, COLORS, color="atlas-warn")
    assert colors_of(text)[0] == COLORS["atlas-warn"]


def test_progress_fills_half_cells_on_a_thin_track():
    accent, track = COLORS["atlas-accent"], COLORS["atlas-border"]
    half = charts.progress(0.5, 10, COLORS)
    assert plain(half) == "━━━━━─────"
    assert colors_of(half) == [accent] * 5 + [track] * 5
    assert plain(charts.progress(0.25, 10, COLORS)) == "━━╸───────"
    assert plain(charts.progress(0.01, 10, COLORS)) == "╸─────────"
    assert plain(charts.progress(0, 6, COLORS)) == "──────"
    assert colors_of(charts.progress(1, 4, COLORS)) == [accent] * 4


def test_progress_indeterminate_slides():
    first = colors_of(charts.progress(None, 20, COLORS, frame=5))
    later = colors_of(charts.progress(None, 20, COLORS, frame=10))
    assert len(first) == 20
    assert first.count(COLORS["atlas-accent"]) == 5
    assert first != later


def test_tags_use_the_design_glyphs():
    expected = {
        "update": "↑ update",
        "new": "+ new",
        "edited": "± edited",
        "similar": "≈ similar",
        "diverged": "≠ diverged",
        "issues": "! issues",
        "error": "✗ error",
        "failed": "✗ failed",
        "risk": "✗ high risk",
        "updated": "✓ updated",
    }
    assert set(expected) == set(charts.TAGS)
    for kind, out in expected.items():
        assert plain(charts.tag(kind, COLORS)) == out
    assert colors_of(charts.tag("update", COLORS))[0] == COLORS["atlas-accent"]
    assert colors_of(charts.tag("risk", COLORS))[0] == COLORS["atlas-danger"]
    assert colors_of(charts.tag("similar", COLORS))[0] == COLORS["atlas-warn"]
    assert colors_of(charts.tag("updated", COLORS))[0] == COLORS["atlas-on"]


def test_tag_label_color_and_compact_tooltip():
    text = charts.tag("issues", COLORS, label="2 issues", color="atlas-danger")
    assert plain(text) == "! 2 issues"
    assert colors_of(text)[0] == COLORS["atlas-danger"]
    assert tips_of(text) == [None] * len(text)
    compact = charts.tag("diverged", COLORS, compact=True)
    assert plain(compact) == "≠"
    assert tips_of(compact) == ["≠ diverged"]
    assert tips_of(charts.tag("edited", COLORS, compact=True, tip="Changed after install.")) == [
        "Changed after install."
    ]


def test_renderers_tolerate_missing_tokens():
    assert plain(charts.switch("on", {})) == "━━●"
    assert colors_of(charts.spark([1], 1, {})) == [None]


class ChartsApp(App[None]):
    def __init__(self, *widgets) -> None:
        super().__init__()
        self.widgets = widgets
        self.events: list = []

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return COLORS

    def compose(self) -> ComposeResult:
        yield from self.widgets

    def on_toggle_switch_changed(self, event: ToggleSwitch.Changed) -> None:
        assert event.control is event.switch
        self.events.append(event.on)

    def on_bar_chart_selected(self, event: BarChart.Selected) -> None:
        assert event.control is event.chart
        self.events.append((event.index, event.label))


def lines(widget) -> list[str]:
    return widget.render().plain.split("\n")


def bg_at(widget, row: int) -> str | None:
    text = widget.render().split("\n")[row]
    color = text.get_style_at_offset(CONSOLE, 0).bgcolor
    return color.get_truecolor().hex if color else None


async def unfocused(pilot) -> None:
    """ChartsApp focuses the heatmap at start; the caption then shows the cursor day."""
    pilot.app.set_focus(None)
    await pilot.pause()


def usage() -> dict[str, int]:
    return {(TODAY - timedelta(days=i)).isoformat(): i % 5 for i in range(0, 120, 3)}


@pytest.mark.asyncio
async def test_heatmap_grid_labels_and_caption():
    heatmap = Heatmap(usage(), today=TODAY)
    async with ChartsApp(heatmap).run_test(size=(80, 12)) as pilot:
        await unfocused(pilot)
        rows = lines(heatmap)
        assert len(rows) == Heatmap.HEIGHT == heatmap.size.height
        assert heatmap.shown_weeks == 26
        assert [r[:3] for r in rows[1:8]] == ["   ", "Mon", "   ", "Wed", "   ", "Fri", "   "]
        assert rows[1].count("■") == 26
        assert rows[7].count("■") == 25
        assert "Oct" in rows[0]
        total, active = sum(usage().values()), sum(1 for n in usage().values() if n)
        assert rows[8].startswith(f"{total} uses on {active} days")
        assert rows[8].endswith("less ■ ■ ■ ■ ■ more")


def test_heat_grid_drops_gaps_then_day_names_then_weeks():
    assert charts.heat_grid(55) == (4, 2, 26)
    assert charts.heat_grid(54) == (4, 1, 26)
    assert charts.heat_grid(30) == (4, 1, 26)
    assert charts.heat_grid(29) == (0, 1, 26)
    assert charts.heat_grid(20) == (0, 1, 20)


@pytest.mark.asyncio
async def test_heatmap_drops_gaps_before_weeks_and_legend_words():
    heatmap = Heatmap(usage(), today=TODAY)
    async with ChartsApp(heatmap).run_test(size=(30, 12)) as pilot:
        await unfocused(pilot)
        assert heatmap.shown_weeks == 26
        rows = lines(heatmap)
        assert all(len(r) <= 30 for r in rows)
        assert rows[1].count("■") == 26 and "■ ■" not in rows[1]
        assert "less" not in rows[8]
        assert rows[8].endswith("■ ■ ■ ■ ■")


@pytest.mark.asyncio
async def test_heatmap_caption_drops_the_note_then_takes_its_own_line():
    days = usage()
    total, active = sum(days.values()), sum(1 for n in days.values() if n)
    wide = Heatmap(days, today=TODAY, note="in saved sessions")
    narrow = Heatmap(days, today=TODAY, note="in saved sessions")
    async with ChartsApp(wide).run_test(size=(80, 24)) as pilot:
        await unfocused(pilot)
        assert lines(wide)[8].startswith(f"{total} uses on {active} days in saved sessions")
    async with ChartsApp(narrow).run_test(size=(24, 24)) as pilot:
        await unfocused(pilot)
        rows = lines(narrow)
        assert narrow.size.height == len(rows) == Heatmap.HEIGHT + 1
        assert rows[8] == f"{total} uses on {active} days"
        assert rows[9] == "less ■ ■ ■ ■ ■ more"


@pytest.mark.asyncio
async def test_heatmap_empty_and_caption():
    heatmap = Heatmap({}, today=TODAY)
    async with ChartsApp(heatmap).run_test(size=(80, 12)) as pilot:
        await unfocused(pilot)
        assert lines(heatmap)[8].startswith("No uses in the last 26 weeks")
        heatmap.caption = "Reading sessions…"
        await pilot.pause()
        assert lines(heatmap)[8].startswith("Reading sessions…")


@pytest.mark.asyncio
async def test_heatmap_hover_shows_the_day_in_caption_and_tooltip():
    heatmap = Heatmap({TODAY.isoformat(): 3}, today=TODAY)
    async with ChartsApp(heatmap).run_test(size=(80, 12)) as pilot:
        await unfocused(pilot)
        dow = (TODAY.weekday() + 1) % 7
        await pilot.hover(Heatmap, offset=(4 + 2 * 25, 1 + dow))
        assert heatmap.tooltip == "Wed, Oct 28 · 3 uses"
        rows = lines(heatmap)
        assert rows[8].startswith("Wed, Oct 28 · 3 uses")
        assert rows[1 + dow][4 + 2 * 25] == charts.HOVER_CELL
        await pilot.hover(Heatmap, offset=(4 + 2 * 24, 1))
        assert heatmap.tooltip == "Sun, Oct 18 · no uses"
        await pilot.hover(Heatmap, offset=(0, 0))
        assert heatmap.tooltip is None
        assert lines(heatmap)[8].startswith("3 uses on 1 day")


@pytest.mark.asyncio
async def test_heatmap_arrow_keys_move_a_cursor_day():
    heatmap = Heatmap({TODAY.isoformat(): 3}, today=TODAY)
    async with ChartsApp(heatmap).run_test(size=(80, 12)) as pilot:
        heatmap.focus()
        await pilot.pause()
        dow = (TODAY.weekday() + 1) % 7
        assert lines(heatmap)[8].startswith("Wed, Oct 28 · 3 uses")
        assert lines(heatmap)[1 + dow][4 + 2 * 25] == charts.HOVER_CELL
        await pilot.press("left")
        assert lines(heatmap)[8].startswith("Wed, Oct 21 · no uses")
        await pilot.press("up", "up", "up")
        assert lines(heatmap)[8].startswith("Sun, Oct 18")
        await pilot.press("up")
        assert lines(heatmap)[8].startswith("Sun, Oct 18"), "the top row stays; the key goes on"
        await pilot.press("right")
        assert lines(heatmap)[8].startswith("Sun, Oct 25")
        await pilot.press("down", "down", "down", "down")
        assert lines(heatmap)[8].startswith("Wed, Oct 28"), "no day after today"
        app = pilot.app
        app.set_focus(None)
        await pilot.pause()
        assert lines(heatmap)[8].startswith("3 uses on 1 day")


@pytest.mark.asyncio
async def test_barchart_truncates_labels_and_aligns_numbers():
    chart = BarChart([("/grill-me", 70), ("/a-very-long-skill-name-indeed", 5)])
    async with ChartsApp(chart).run_test(size=(40, 4)) as pilot:
        rows = lines(chart)
        assert len(rows) == 2 == chart.size.height
        assert rows[1].startswith("/a-very-long-skill-name-i…")
        assert all(len(r) == 40 for r in rows)
        assert [r[-2:] for r in rows] == ["70", " 5"]
        assert rows[0].count("━") > 0 and "╸" in rows[1]
        bar = chart.render().split("\n")[0]
        at = bar.plain.index("━")
        assert (
            bar.get_style_at_offset(CONSOLE, at).color.get_truecolor().hex == COLORS["atlas-spark"]
        )
        chart.rows = []
        await pilot.pause()
        assert chart.render().plain == "Nothing to show yet."


@pytest.mark.asyncio
async def test_barchart_formats_and_drops_bars_when_narrow():
    chart = BarChart([("/a", 270), ("/bb", 12)], fmt=lambda v: f"≈{v:.0f}")
    async with ChartsApp(chart).run_test(size=(12, 4)):
        assert lines(chart) == ["/a      ≈270", "/bb      ≈12"]


@pytest.mark.asyncio
async def test_barchart_hover_tooltip_only_for_cut_labels():
    chart = BarChart([("/grill-me", 70), ("/a-very-long-skill-name-indeed", 5)])
    async with ChartsApp(chart).run_test(size=(40, 4)) as pilot:
        await pilot.hover(BarChart, offset=(2, 1))
        assert chart.tooltip == "/a-very-long-skill-name-indeed · 5"
        assert bg_at(chart, 1) == COLORS["atlas-surface-2"]
        assert bg_at(chart, 0) is None
        await pilot.hover(BarChart, offset=(2, 0))
        assert chart.tooltip is None
        assert bg_at(chart, 0) == COLORS["atlas-surface-2"]


@pytest.mark.asyncio
async def test_barchart_click_selects_a_row():
    chart = BarChart([("/grill-me", 70), ("/caveman", 66)])
    app = ChartsApp(chart)
    async with app.run_test(size=(40, 4)) as pilot:
        await pilot.mouse_down(BarChart, offset=(30, 1))
        assert bg_at(chart, 1) == COLORS["atlas-surface-3"]
        await pilot.mouse_up(BarChart, offset=(30, 1))
        await pilot.click(BarChart, offset=(30, 1))
        await pilot.pause()
        assert app.events == [(1, "/caveman")]
        assert bg_at(chart, 1) == COLORS["atlas-surface-2"]


@pytest.mark.asyncio
async def test_toggle_by_key_and_click():
    sw = ToggleSwitch()
    app = ChartsApp(sw)
    async with app.run_test() as pilot:
        sw.focus()
        await pilot.press("space")
        assert sw.on
        await pilot.press("enter")
        assert not sw.on
        await pilot.click(ToggleSwitch)
        await pilot.pause()
        assert sw.on
        assert app.events == [True, False, True]


@pytest.mark.asyncio
async def test_switch_takes_clicks_one_cell_past_each_side():
    sw = ToggleSwitch()
    app = ChartsApp(sw)
    async with app.run_test() as pilot:
        assert sw.region.width == 5
        await pilot.click(ToggleSwitch, offset=(0, 0))
        await pilot.click(ToggleSwitch, offset=(4, 0))
        await pilot.pause()
        assert app.events == [True, False]


@pytest.mark.asyncio
async def test_switch_hover_pressed_and_tooltip():
    sw = ToggleSwitch(on=True, label="Codex")
    app = ChartsApp(sw)
    async with app.run_test() as pilot:
        assert sw.tooltip == "Codex: turn off"
        assert sw.has_focus
        assert sw.styles.background.hex == COLORS["atlas-selection"].upper()
        app.set_focus(None)
        await pilot.hover(ToggleSwitch)
        assert sw.mouse_hover
        assert sw.styles.background.hex == COLORS["atlas-surface-2"].upper()
        await pilot.mouse_down(ToggleSwitch)
        assert sw.has_class("-pressed")
        assert sw.styles.background.hex == COLORS["atlas-surface-3"].upper()
        assert sw.on
        await pilot.mouse_up(ToggleSwitch)
        assert not sw.has_class("-pressed")
        sw.on = False
        assert sw.tooltip == "Codex: turn on"
        assert ToggleSwitch().tooltip == "Turn on"


@pytest.mark.asyncio
async def test_setting_on_in_code_is_silent():
    sw = ToggleSwitch(on=True, show_state=True)
    app = ChartsApp(sw)
    async with app.run_test() as pilot:
        assert sw.render().plain == "━━● on "
        sw.on = False
        await pilot.pause()
        assert app.events == []
        assert sw.render().plain == "○━━ off"


@pytest.mark.asyncio
async def test_disabled_switch_ignores_input():
    sw = ToggleSwitch(on=True, disabled=True)
    app = ChartsApp(sw)
    async with app.run_test() as pilot:
        await pilot.click(ToggleSwitch)
        sw.focus()
        await pilot.press("space")
        await pilot.pause()
        assert sw.on
        assert app.events == []
        assert not sw.has_focus
        assert sw.tooltip == "no switch"
        assert sw.render().plain == "○━━"


@pytest.mark.asyncio
async def test_disabled_switch_shows_its_reason_not_a_state():
    sw = ToggleSwitch(on=True, show_state=True, disabled=True)
    other = ToggleSwitch(on=True, show_state=True, disabled=True, reason="read-only")
    async with ChartsApp(sw, other).run_test() as pilot:
        assert sw.render().plain == "○━━ no switch"
        assert sw.tooltip == "no switch"
        assert other.render().plain == "○━━ read-only"
        assert other.tooltip == "read-only"
        assert set(colors_of(sw.render())) == {COLORS["atlas-faint"]}
        sw.disabled = False
        await pilot.pause()
        assert sw.render().plain == "━━● on "
        assert sw.tooltip == "Turn off"
        assert sw.region.width == len("━━● on ") + 2


@pytest.mark.asyncio
async def test_click_shows_one_moving_frame(monkeypatch):
    monkeypatch.setattr(switch, "MOVE_SECONDS", 30)
    sw = ToggleSwitch()
    app = ChartsApp(sw)
    async with app.run_test() as pilot:
        app.animation_level = "full"
        await pilot.click(ToggleSwitch)
        assert sw.on
        assert sw.render().plain == "━●━"
        sw.on = False
        assert sw.render().plain == "○━━"


@pytest.mark.asyncio
async def test_moving_frame_settles():
    sw = ToggleSwitch()
    app = ChartsApp(sw)
    async with app.run_test() as pilot:
        app.animation_level = "full"
        await pilot.click(ToggleSwitch)
        await pilot.pause(switch.MOVE_SECONDS + 0.1)
        assert sw.render().plain == "━━●"


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["basic", "none"])
async def test_no_moving_frame_below_full_motion(level, monkeypatch):
    monkeypatch.setattr(switch, "MOVE_SECONDS", 30)
    sw = ToggleSwitch()
    app = ChartsApp(sw)
    async with app.run_test() as pilot:
        app.animation_level = level
        await pilot.click(ToggleSwitch)
        assert sw.render().plain == "━━●"


@pytest.mark.asyncio
async def test_keys_never_animate(monkeypatch):
    monkeypatch.setattr(switch, "MOVE_SECONDS", 30)
    sw = ToggleSwitch()
    app = ChartsApp(sw)
    async with app.run_test() as pilot:
        app.animation_level = "full"
        sw.focus()
        await pilot.press("space")
        assert sw.render().plain == "━━●"
