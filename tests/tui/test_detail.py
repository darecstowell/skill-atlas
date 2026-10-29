import asyncio
import importlib
import sys
import threading
import types
from datetime import datetime

import pytest
from rich.console import Console
from rich.text import Text

from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.widgets import detail_parts
from skill_atlas.tui.widgets.charts import Heatmap
from skill_atlas.tui.widgets.detail import DetailPanel
from skill_atlas.tui.widgets.detail_parts import (
    DetailHints,
    DetailRow,
    DetailSkeleton,
    DetailText,
    HarnessSwitch,
    wid,
    wrap_text,
)

NOW = datetime(2026, 10, 28, 12, 0).astimezone()
TALL = (150, 90)
STORE = "/home/demo/.agents/skills"
COPYWRITING = f"{STORE}/copywriting/SKILL.md"
MARKETING = "src:coreyhaines31/marketingskills"


class Calls(list):
    """What the stubbed feature functions got, as (name, args) pairs."""

    def of(self, name):
        return [args for n, args in self if n == name]


@pytest.fixture
def calls(monkeypatch):
    """Record the calls the panel makes into other owners' modules."""
    got = Calls()
    wanted = {
        "jobs": ("set_switch", "update", "install", "copy", "reveal", "open_github"),
        "screens.reader": ("open_reader",),
        "screens.diff": ("open_diff", "open_compare"),
        "screens.history": ("open_history",),
        "screens.confirm": ("confirm_delete",),
        "screens.link": ("open_link",),
        "commands": ("open_actions", "stop_watching", "dismiss_new"),
    }
    for module, names in wanted.items():
        full = f"skill_atlas.tui.{module}"
        try:
            mod = importlib.import_module(full)
        except Exception:
            mod = types.ModuleType(full)
            monkeypatch.setitem(sys.modules, full, mod)
        for name in names:

            def record(app, *args, _name=name):
                got.append((_name, args))

            monkeypatch.setattr(mod, name, record, raising=False)
    return got


@pytest.fixture
def app(prefs, monkeypatch):
    """The app over fixed demo data, not over SSH."""
    monkeypatch.delenv("SSH_TTY", raising=False)
    return AtlasApp(DemoAtlas(now=NOW))


async def rest(pilot, seconds=0.4):
    """Let the selection settle, the lazy reads finish, and the panel draw them."""
    await settle(pilot)
    await asyncio.sleep(seconds)
    await settle(pilot)


async def pick(pilot, *, path=None, key=None):
    pilot.app.set_state(selected=path, selected_key=key)
    await rest(pilot)
    return pilot.app.query_one(DetailPanel)


def panel_text(app):
    panel = app.query_one(DetailPanel)
    lines = []
    for y, strip in enumerate(app.screen._compositor.render_strips()):
        if panel.region.y <= y < panel.region.bottom:
            lines.append(strip.text[panel.region.x : panel.region.right])
    return "\n".join(lines)


def flat(text):
    return " ".join(text.split())


def by_id(app, key):
    return app.query_one(f"#{wid(key)}")


def hint_offset(bar: DetailHints, label: str) -> tuple[int, int]:
    """The offset inside the bar of the hint whose label is `label`."""
    spots = bar._layout(bar.size.width)
    for h, (row, x, _) in zip(bar.hints, spots, strict=True):
        if h.label == label:
            return (x + 1 + bar.styles.padding.left, row)
    raise AssertionError(f"no hint {label!r} in {[h.label for h in bar.hints]}")


async def click_hint(pilot, key, label):
    bar = by_id(pilot.app, key)
    await pilot.click(bar, offset=hint_offset(bar, label))
    await rest(pilot, 0.1)


@pytest.mark.asyncio
async def test_a_skill_shows_its_header_cards_and_sections(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        text = panel_text(app)
        for want in (
            "coreyhaines31/marketingskills",
            "/copywriting",
            "~/.agents/skills/copywriting/SKILL.md",
            "↑ update",
            "Type /copywriting",
            "Loads it when it fits",
            "Update available",
            "5 files changed",
            "See changes",
            "LOADED BY",
            "Claude Code · personal",
            "no switch",
            "USAGE · 26 WEEKS",
            "Delete…",
        ):
            assert want in text, want
        assert "★ 9.8k" in text
        assert "! 1 diverged copy" in text
        assert "LOADED BY" in text and "On in" not in text
        assert "History (" not in text and "5 snapshots" in text


@pytest.mark.asyncio
async def test_click_a_loaded_by_switch_writes_that_harness(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        row = by_id(app, "lb:codex")
        assert isinstance(row, HarnessSwitch) and row.on
        await pilot.click(row, offset=(row.size.width - 4, 0))
        await rest(pilot, 0.1)
        assert calls.of("set_switch") == [("codex", ["copywriting"], False, "skill")]
        await pilot.click(row, offset=(4, 0))
        await rest(pilot, 0.1)
        assert calls.of("set_switch")[-1] == ("codex", ["copywriting"], True, "skill")
        assert app.focused is by_id(app, "lb:codex")


@pytest.mark.asyncio
async def test_space_and_x_toggle_the_focused_switch(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        row = by_id(app, "lb:gemini-cli")
        row.focus()
        await pilot.press("space")
        await rest(pilot, 0.1)
        assert calls.of("set_switch") == [("gemini-cli", ["copywriting"], True, "skill")]
        await pilot.press("x")
        await rest(pilot, 0.1)
        assert calls.of("set_switch")[-1] == ("gemini-cli", ["copywriting"], False, "skill")


@pytest.mark.asyncio
async def test_a_harness_without_a_switch_says_so(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        row = by_id(app, "lb:cursor")
        assert row.disabled and not row.focusable and row.tooltip == "no switch"


@pytest.mark.asyncio
async def test_click_a_section_label_folds_it_and_saves_it(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        await pilot.click(by_id(app, "h:skill.lb"))
        await rest(pilot, 0.1)
        assert "skill.lb" in app.state.folded
        assert not app.query(f"#{wid('lb:codex')}")
        assert "On in 5 of 6" in panel_text(app)
        await pilot.click(by_id(app, "h:skill.lb"))
        await rest(pilot, 0.1)
        assert "+skill.lb" in app.state.folded and "skill.lb" not in app.state.folded
        assert app.query(f"#{wid('lb:codex')}")


@pytest.mark.asyncio
async def test_enter_on_a_folded_section_opens_it(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        head = by_id(app, "h:skill.ovl")
        head.focus()
        await pilot.press("enter")
        await rest(pilot, 0.1)
        assert "+skill.ovl" in app.state.folded
        text = panel_text(app)
        assert "Copies" in text and "~/.claude-work/skills/copywriting" in text
        assert "That copy is newer" in text or "This copy is newer" in text
        assert app.focused is by_id(app, "h:skill.ovl")


@pytest.mark.asyncio
async def test_update_card_hints_run_their_actions(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        await click_hint(pilot, "upd:copywriting", "Update")
        await click_hint(pilot, "upd:copywriting", "See changes")
        assert [h.label for h in by_id(app, "upd:copywriting").hints] == ["See changes", "Update"]
        assert calls.of("update") == [(["copywriting"],)]
        assert calls.of("open_diff") == [("copywriting",)]


@pytest.mark.asyncio
async def test_header_hints_read_copy_and_more(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        bar = by_id(app, "acts")
        assert [(h.key, h.label) for h in bar.hints] == [
            ("v", "Read"),
            ("", "Copy /copywriting"),
            ("o", "GitHub ↗"),
            ("shift+r", "Reveal"),
            ("", "⋯"),
        ]
        for label in ("Read", "Copy /copywriting", "GitHub ↗", "Reveal", "⋯"):
            await click_hint(pilot, "acts", label)
        assert calls.of("open_reader") == [(COPYWRITING,)]
        assert calls.of("copy") == [("/copywriting", "/copywriting")]
        assert calls.of("open_github")[0][0].startswith("https://github.com/")
        assert calls.of("reveal") == [(COPYWRITING,)]
        assert calls.of("open_actions") == [(COPYWRITING,)]


@pytest.mark.asyncio
async def test_reveal_hides_over_ssh(app, monkeypatch):
    monkeypatch.setenv("SSH_TTY", "/dev/ttys001")
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        labels = [h.label for h in by_id(app, "acts").hints]
        assert "Reveal" not in labels and "Read" in labels


@pytest.mark.asyncio
async def test_delete_asks_through_the_confirm_screen(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        await click_hint(pilot, "delete", "Delete…")
        assert calls.of("confirm_delete") == [(["copywriting"],)]


@pytest.mark.asyncio
async def test_keys_in_the_panel_are_the_app_keys(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        assert {b.key for b in DetailPanel.BINDINGS} == {"down,j", "up,k"}
        by_id(app, "crumb").focus()
        await pilot.press("d", "h", "delete")
        await rest(pilot, 0.1)
        assert calls.of("open_diff") == [()]
        assert calls.of("open_history") == [()]
        assert calls.of("confirm_delete") == [()]


@pytest.mark.asyncio
async def test_tab_enters_the_panel_and_arrows_move_between_controls(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        panel = app.query_one(DetailPanel)
        app.main.query_one("#list").focus()
        for _ in range(8):
            await pilot.press("tab")
            if app.focused is not None and panel in app.focused.ancestors:
                break
        assert app.focused is by_id(app, "crumb")
        await pilot.press("down")
        assert app.focused is by_id(app, "switch")
        await pilot.press("down")
        bar = by_id(app, "acts")
        assert app.focused is bar and bar.cursor == 0
        await pilot.press("down")
        assert app.focused is bar and bar.cursor == 1
        await pilot.press("up", "up")
        assert app.focused is by_id(app, "switch")
        await pilot.press("up")
        assert app.focused is by_id(app, "crumb")
        await pilot.press("enter")
        await rest(pilot, 0.1)
        assert app.state.selected is None and app.state.selected_key == MARKETING


@pytest.mark.asyncio
async def test_focus_stays_on_a_switch_when_the_data_changes(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        row = by_id(app, "lb:codex")
        row.focus()
        await app.fetch(app.atlas.toggle, "codex", "skill", ["copywriting"], False)
        app.reload(["scan"])
        await rest(pilot, 0.1)
        now = by_id(app, "lb:codex")
        assert app.focused is now and not now.on


@pytest.mark.asyncio
async def test_security_loads_through_fetch_when_opened(app, monkeypatch):
    fetched = []
    fetch = AtlasApp.fetch

    async def counted(self, fn, *args):
        fetched.append(getattr(fn, "__name__", ""))
        return await fetch(self, fn, *args)

    monkeypatch.setattr(AtlasApp, "fetch", counted)
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        risky = f"{STORE}/repo-bootstrap/SKILL.md"
        await pick(pilot, path=risky)
        assert "security" not in fetched
        assert "✗ 2 high findings" in panel_text(app)
        await pilot.click(by_id(app, "h:skill.sec"))
        await rest(pilot)
        assert fetched.count("security") == 1
        text = panel_text(app)
        assert "✗ high" in text and "Runs downloaded code" in text
        assert "heuristic scan" in text


@pytest.mark.asyncio
async def test_a_slow_read_shows_a_skeleton_and_a_fast_one_does_not(app, monkeypatch):
    made = []
    init = DetailSkeleton.__init__

    def counted(self, el):
        made.append(el)
        init(self, el)

    monkeypatch.setattr(DetailSkeleton, "__init__", counted)
    gate = threading.Event()
    history = app.atlas.history

    def slow(name):
        gate.wait(5)
        return history(name)

    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        app.set_state(folded=frozenset({"+skill.hist"}))
        await pick(pilot, path=f"{STORE}/ai-seo/SKILL.md")
        assert not made and "Before an update" in panel_text(app)
        monkeypatch.setattr(app.atlas, "history", slow)
        app.set_state(selected=COPYWRITING)
        await pilot.pause(0.22)
        assert not made, "no skeleton before the read has run 150 ms"
        await pilot.pause(0.25)
        await pilot.pause()
        assert made and app.query(DetailSkeleton)
        gate.set()
        await rest(pilot, 0.6)
        assert not app.query(DetailSkeleton)
        assert len([r for r in app.query(DetailRow) if r.spec.id.startswith("snap:")]) == 5


@pytest.mark.asyncio
async def test_a_new_selection_starts_at_the_top_without_animation(app):
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        panel = await pick(pilot, path=COPYWRITING)
        panel.scroll_end(animate=False)
        await settle(pilot)
        assert panel.scroll_y > 0
        app.set_state(selected=f"{STORE}/ai-seo/SKILL.md")
        await pilot.pause()
        await pilot.pause()
        assert panel.scroll_y == 0
        assert not app.animator.is_being_animated(panel, "scroll_y")


@pytest.mark.asyncio
async def test_problems_show_level_message_and_hint(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=f"{STORE}/notes-helper/SKILL.md")
        text = panel_text(app)
        assert "problem" in text and "to fix" in text
        assert "✗ Error" in text or "! Warning" in text


@pytest.mark.asyncio
async def test_a_long_description_shows_more_on_click(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        ins = app.data.insights
        s = next(x for x in ins.skills if len(x.get("description") or "") > 420)
        await pick(pilot, path=s["path"])
        assert "Show more" in panel_text(app)
        await click_hint(pilot, "more", "Show more")
        await rest(pilot, 0.1)
        assert "Show less" in panel_text(app)


@pytest.mark.asyncio
async def test_similar_rows_open_the_other_skill(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        app.set_state(folded=frozenset({"+skill.ovl"}))
        await pick(pilot, path=f"{STORE}/copy-editing/SKILL.md")
        rows = [r for r in app.query(DetailRow) if r.spec.id.startswith("sim:")]
        assert rows and "%" in panel_text(app)
        await pilot.click(rows[0])
        await rest(pilot, 0.1)
        assert app.state.selected == rows[0].spec.act.args[0]


@pytest.mark.asyncio
async def test_a_group_shows_its_source_and_actions(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, key=MARKETING)
        text = panel_text(app)
        for want in (
            "coreyhaines31/marketingskills",
            "30 of 37 on",
            "★ 9.8k",
            "Update 8",
            "you only",
        ):
            assert want in text, want
        assert "SKILLS" not in text
        await click_hint(pilot, "acts", "Update 8")
        names = calls.of("update")[0][0]
        assert len(names) == 8 and "copywriting" in names
        assert [h.label for h in by_id(app, "acts").hints][-2:] == ["GitHub ↗", "⋯"]
        await click_hint(pilot, "acts", "GitHub ↗")
        assert calls.of("open_github") == [("https://github.com/coreyhaines31/marketingskills",)]


@pytest.mark.asyncio
async def test_group_switch_turns_only_the_skills_that_change(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, key=MARKETING)
        switch = by_id(app, "switch")
        assert switch.mixed and not switch.on
        await pilot.click(switch)
        await rest(pilot, 0.1)
        _harness, names, on, kind = calls.of("set_switch")[0]
        assert on and kind == "skill" and len(names) == 7


@pytest.mark.asyncio
async def test_a_watched_source_can_stop_watching_and_dismiss_new(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        repo = next(r for r in app.data.updates["watched"])
        await pick(pilot, key=f"src:{repo}")
        assert "Watching" in panel_text(app)
        await click_hint(pilot, "acts", "Stop watching")
        assert calls.of("stop_watching") == [(repo,)]
        fresh = next(r for r, items in app.data.available.items() if any(a["new"] for a in items))
        await pick(pilot, key=f"src:{fresh}")
        await click_hint(pilot, "acts", "Dismiss new")
        assert calls.of("dismiss_new") == [(fresh,)]


@pytest.mark.asyncio
async def test_an_available_skill_loads_its_description_and_installs(app, calls):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        repo, items = next((r, a) for r, a in app.data.available.items() if a)
        a = next(x for x in items if not x.get("taken"))
        await pick(pilot, key=f"a:{repo}:{a['path']}")
        text = panel_text(app)
        assert f"/{a['name']}" in text and "Not installed" in text and "Available" in text
        assert f"Installsinto~/.agents/skills/{a['name']}" in "".join(text.split())
        desc = app.atlas.available(repo, [a["path"]])["skills"][a["path"]]["description"]
        assert flat(desc)[:30] in flat(text)
        await click_hint(pilot, "install", "Install")
        assert calls.of("install") == [(repo, [a["path"]])]
        await click_hint(pilot, "acts", "Read")
        assert calls.of("open_reader") == [()]


@pytest.mark.asyncio
async def test_the_close_cell_shows_the_inventory_again(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        await pilot.click(app.query_one(detail_parts.CloseX))
        await rest(pilot, 0.1)
        assert app.state.selected is None and app.state.selected_key is None


@pytest.mark.asyncio
async def test_hover_shows_the_glyph_tooltip(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        bar = by_id(app, "acts")
        await pilot.hover(bar, offset=hint_offset(bar, "⋯"))
        await pilot.pause()
        assert bar.tooltip == "More actions · ctrl+k"


@pytest.mark.asyncio
async def test_a_short_window_folds_all_but_loaded_by(app):
    async with app.run_test(size=(120, 24)) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        assert app.query(f"#{wid('lb:codex')}")
        assert "▸ USAGE" in panel_text(app) or not app.query(detail_parts.HeatView)


def test_wrap_breaks_long_words_after_path_marks():
    text = Text("Installs into ~/.agents/skills/migrate-to-shoehorn")
    lines = [t.plain for t in wrap_text(text, 30)]
    assert lines == ["Installs into", "~/.agents/skills/migrate-to-", "shoehorn"]
    assert [t.plain for t in wrap_text(Text("abcdefghij"), 4)] == ["abcd", "efgh", "ij"]


def heights(app):
    return [(w.id, w.region.height) for w in app.query_one(DetailPanel).children]


@pytest.mark.asyncio
async def test_no_height_changes_when_the_scrollbar_shows_or_reads_land(app):
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot)
        app.set_state(selected=f"{STORE}/notes-helper/SKILL.md")
        await pilot.pause(0.05)
        await pilot.pause()
        first = heights(app)
        await rest(pilot, 0.8)
        assert app.query_one(DetailPanel).styles.scrollbar_gutter == "stable"
        assert heights(app) == first
        assert app.query_one(".path", DetailText).region.height == 1
        app.set_state(selected=COPYWRITING)
        await pilot.pause(0.05)
        await pilot.pause()
        early = heights(app)
        await rest(pilot, 0.8)
        assert heights(app) == early, "the diff line and the card hold their rows"


@pytest.mark.asyncio
async def test_a_failed_diff_keeps_its_row(app, monkeypatch):
    def broken(name):
        raise RuntimeError("no network")

    monkeypatch.setattr(app.atlas, "diff", broken)
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        assert "Could not get the changes: no network." in flat(panel_text(app))


@pytest.mark.asyncio
async def test_risk_and_problems_show_in_the_meta_line(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=f"{STORE}/repo-bootstrap/SKILL.md")
        assert "✗ high risk" in app.query_one(".meta", DetailText).spec.text.plain
        await pick(pilot, path=f"{STORE}/notes-helper/SKILL.md")
        assert "issue" in app.query_one(".meta", DetailText).spec.text.plain


@pytest.mark.asyncio
async def test_descriptions_are_muted_and_clamped_by_lines(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        ins = app.data.insights
        s = next(x for x in ins.skills if len(x.get("description") or "") > 420)
        await pick(pilot, path=s["path"])
        desc = app.query_one(".desc", DetailText)
        assert desc.region.height == 6 and desc.spec.text.plain.endswith("…")
        con = Console()
        path = app.query_one(".path", DetailText).spec.text
        assert desc.spec.text.get_style_at_offset(con, 0) == path.get_style_at_offset(con, 0)
        assert by_id(app, "more").hints[0].key == "shift+m"
        await pilot.press("M")
        await rest(pilot, 0.1)
        assert app.query_one(".desc", DetailText).region.height > 6


@pytest.mark.asyncio
async def test_a_short_window_puts_who_on_one_line_and_clamps_to_three(app):
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        app.set_state(selected=f"{STORE}/ai-seo/SKILL.md")
        app.show_detail(True)
        await rest(pilot)
        assert "Type /ai-seo · Loads it when it fits" in panel_text(app)
        assert app.query_one(".desc", DetailText).region.height <= 3


@pytest.mark.asyncio
async def test_group_tiles_have_a_row_gap_and_three_columns(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, key=MARKETING)
        stats = app.query_one("#b-stats DetailText", DetailText).spec.text.plain.split("\n")
        assert len(stats) == 5 and stats[2] == ""
        assert stats[0].split() == ["30", "7", "8"] and stats[1].split()[0] == "on"


@pytest.mark.asyncio
async def test_the_heatmap_takes_arrow_keys_in_the_panel(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        heat = app.query_one(Heatmap)
        assert heat in app.query_one(DetailPanel).controls()
        heat.focus()
        await pilot.pause()
        assert heat.render().plain.split("\n")[-1].startswith("Wed, Oct 28")
        await pilot.press("left")
        assert heat.render().plain.split("\n")[-1].startswith("Wed, Oct 21")
        for _ in range(3):
            await pilot.press("up")
        assert app.focused is heat
        await pilot.press("up")
        assert app.focused is not heat and app.focused in app.query_one(DetailPanel).controls()


@pytest.mark.asyncio
async def test_the_current_harness_row_has_a_background(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        await pick(pilot, path=COPYWRITING)
        cur = next(w for w in app.query(HarnessSwitch) if w.has_class("-current"))
        other = next(w for w in app.query(HarnessSwitch) if not w.has_class("-current"))
        assert cur.styles.background != other.styles.background


@pytest.mark.asyncio
async def test_focus_goes_to_the_control_at_the_same_place_when_its_control_goes(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        panel = await pick(pilot, path=COPYWRITING)
        panel._refocus("d-gone", 0, 4)
        await pilot.pause()
        assert app.focused is panel.controls()[4]
        panel._refocus("d-gone", 0, 999)
        await pilot.pause()
        assert app.focused is panel.controls()[-1]


@pytest.mark.asyncio
async def test_tab_into_the_panel_never_animates_a_scroll(app):
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        app.animation_level = "basic"
        panel = await pick(pilot, path=COPYWRITING)
        panel.scroll_end(animate=False)
        await settle(pilot)
        app.main.query_one("#list").focus()
        for _ in range(8):
            await pilot.press("tab")
            assert not app.animator.is_being_animated(panel, "scroll_y")
            if app.focused is not None and panel in app.focused.ancestors:
                break
        await pilot.pause()
        assert not app.animator.is_being_animated(panel, "scroll_y")
        assert panel.scroll_y == 0 and app.focused is by_id(app, "crumb")


@pytest.mark.asyncio
async def test_a_new_selection_waits_for_the_list_and_skips_same_redraws(app):
    async with app.run_test(size=TALL) as pilot:
        await settle(pilot)
        panel = await pick(pilot, path=COPYWRITING)
        app.set_state(selected=f"{STORE}/ai-seo/SKILL.md")
        await pilot.pause(0.005)
        assert panel._target == ("skill", COPYWRITING), "the list paints first"
        await rest(pilot, 0.8)
        assert panel._target == ("skill", f"{STORE}/ai-seo/SKILL.md")
        drawn = panel._last
        app.set_state(palette=app.state.palette)
        panel.schedule(dirty=False)
        await rest(pilot, 0.1)
        assert panel._last == drawn


@pytest.mark.asyncio
async def test_opening_a_section_scrolls_its_body_into_view(app):
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        app.set_state(folded=frozenset({"skill.lb", "skill.use"}))
        panel = await pick(pilot, path=COPYWRITING)
        head = by_id(app, "h:skill.facts")
        panel.scroll_to_widget(head, animate=False, top=False)
        await settle(pilot)
        await pilot.click(head)
        await rest(pilot, 0.2)
        body = app.query_one(f"#{wid('b:skill.facts', 'b')}")
        assert body.region.height > 0
        assert body.region.bottom <= panel.region.bottom or body.region.y < panel.region.bottom - 2
