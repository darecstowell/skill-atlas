from datetime import datetime, timezone

import pytest
from textual.widgets import Static

from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.widgets.skill_list import (
    FOLDED_TOAST,
    MINI_MAX,
    MINI_MIN,
    SkillList,
)

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
WIDE = (160, 40)


@pytest.fixture
def fresh(new_defaults, prefs, monkeypatch):
    """Real defaults, with stub panels: repos fold in the All view, and rows are short."""
    monkeypatch.setattr("skill_atlas.tui.app.DetailPanel", Static)
    monkeypatch.setattr("skill_atlas.tui.app.SidePanel", Static)
    return AtlasApp(DemoAtlas(now=NOW))


def width(lst):
    return lst.scrollable_content_region.width


def index(lst, kind, test=lambda row: True):
    return next(i for i, r in enumerate(lst.rows) if r.kind == kind and test(r))


def text(lst, i, w=None):
    return lst._line(i, w or width(lst)).text


@pytest.mark.asyncio
async def test_a_long_repo_label_is_cut_before_its_meta_drops(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        i = index(lst, "group", lambda r: r.item["label"].startswith("rorkai/"))
        meta = lst.rows[i].item["meta"]
        assert meta in text(lst, i)
        line = text(lst, i, 60)
        assert "…" in line and meta in line and lst.rows[i].item["label"] not in line


@pytest.mark.asyncio
async def test_short_rows_have_no_monogram_and_the_section_labels_the_counts(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        c = lst._cols(width(lst))
        g = lst.rows[index(lst, "group")]
        line = text(lst, lst.rows.index(g))
        assert line[c.chev] == "▸" and line[c.chev + 1] == " "
        assert line[c.name :].startswith(g.item["label"])
        sec = text(lst, index(lst, "section"))
        assert sec[c.count + c.count_w - 4 : c.count + c.count_w] == "uses"


@pytest.mark.asyncio
async def test_the_fold_link_sits_by_the_title_and_expands_while_any_repo_is_folded(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        s = index(lst, "section")
        sec = lst.rows[s].item
        head = f"{sec['title'].upper()} {sec['count']}  "
        assert f"{head}Expand all" in text(lst, s)
        await pilot.press("enter")
        await pilot.pause()
        assert f"{head}Expand all" in text(lst, s)
        fresh.set_state(opened=frozenset(sec["group_ids"]))
        await pilot.pause()
        assert f"{head}Collapse all" in text(lst, s)


@pytest.mark.asyncio
async def test_status_and_count_sit_near_the_names_on_a_wide_window(fresh):
    async with fresh.run_test(size=(220, 40)) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        c = lst._cols(width(lst))
        assert MINI_MIN <= c.name_w == lst._mini_len <= MINI_MAX
        assert c.menu + 2 < width(lst) - 40


@pytest.mark.asyncio
async def test_rare_statuses_show_their_word_and_updates_hide_in_the_updates_view(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        fresh.set_state(opened=frozenset({"*"}))
        await pilot.pause()
        lst = fresh.query_one(SkillList)
        i = index(lst, "skill", lambda r: lst._memo(r).status.glyph == "≈")
        assert i != lst.cursor and "≈ similar" in text(lst, i)
        fresh.set_state(view="updates")
        await pilot.pause()
        lst.action_last()
        await pilot.pause()
        g = index(lst, "group", lambda r: lst._memo(r) is not None)
        k = index(lst, "skill", lambda r: lst._memo(r).status.glyph == "↑")
        assert lst.cursor not in (g, k)
        assert "↑" not in text(lst, g) and "↑" not in text(lst, k)
        assert "↑" in lst._memo(lst.rows[k]).status.glyph
        e = index(lst, "skill", lambda r: r.item.get("local_edits"))
        assert e != lst.cursor and "± edited" in text(lst, e)


@pytest.mark.asyncio
async def test_the_mark_cell_shows_only_on_the_cursor_row(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        fresh.set_state(opened=frozenset({"*"}))
        await pilot.pause()
        lst = fresh.query_one(SkillList)
        a, b = [i for i, r in enumerate(lst.rows) if r.kind == "skill"][:2]
        fresh.set_state(marked={lst.rows[a].key})
        await pilot.pause()
        assert text(lst, a)[1] == "◆" and text(lst, b)[1] == " "
        fresh.set_state(selected=lst.rows[b].key)
        await pilot.pause()
        assert text(lst, b)[1] == "◇"


@pytest.mark.asyncio
async def test_clearing_a_search_keeps_the_selected_skills_repo_open(fresh):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        fresh.set_state(query="music")
        await pilot.pause(0.3)
        i = index(lst, "skill")
        gid, path = lst.rows[i].gid, lst.rows[i].key
        fresh.set_state(selected=path)
        await pilot.pause()
        fresh.set_state(query="")
        await pilot.pause(0.3)
        assert gid in fresh.state.opened and lst.rows[lst.cursor].key == path


@pytest.mark.asyncio
async def test_descriptions_on_with_every_repo_folded_says_to_open_one(fresh, monkeypatch):
    async with fresh.run_test(size=WIDE) as pilot:
        await settle(pilot)
        lst = fresh.query_one(SkillList)
        said: list[str] = []
        monkeypatch.setattr(lst, "_toast", said.append)
        fresh.set_state(row_detail=True)
        await pilot.pause()
        assert said == [FOLDED_TOAST]
        fresh.set_state(row_detail=False)
        await pilot.press("enter")
        fresh.set_state(row_detail=True)
        await pilot.pause()
        assert said == [FOLDED_TOAST]
