import threading
import types
from datetime import datetime, timezone

import pytest
from textual import events
from textual.widgets import Markdown, Static

from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.screens import reader
from skill_atlas.tui.screens.reader import (
    FrontMatter,
    ModeSwitch,
    Outline,
    RawView,
    ReaderDoc,
    ReaderPage,
    ReaderScreen,
    open_reader,
)
from skill_atlas.tui.widgets.skill_list import SkillList
from skill_atlas.tui.widgets.toast import current

NOW = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
WIDE, NARROW = (140, 40), (90, 30)
TRACKED, LOCAL = "a11y-refactor", "acme-design-tokens"


@pytest.fixture
def app(tmp_path):
    return AtlasApp(DemoAtlas(now=NOW), prefs=tmp_path / "tui.json")


@pytest.fixture
def calls(monkeypatch):
    """A stand-in jobs module that records each call."""
    seen: list[tuple] = []
    fake = types.ModuleType("skill_atlas.tui.jobs")
    for name in ("copy", "open_github", "reveal"):
        setattr(fake, name, lambda app, *args, _n=name: seen.append((_n, *args)))
    monkeypatch.setitem(__import__("sys").modules, "skill_atlas.tui.jobs", fake)
    return seen


def skill(app, name):
    return next(s for s in app.data.skills if s["name"] == name and s["scope"] == "personal")


def screen_text(app):
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


def find(app, text):
    for y, strip in enumerate(app.screen._compositor.render_strips()):
        x = strip.text.find(text)
        if x >= 0:
            return (x, y)
    raise AssertionError(f"{text!r} is not on the screen")


async def click_text(pilot, app, text, widget, dx=0):
    """Click on text the screen shows, as a click on the widget under it."""
    x, y = find(app, text)
    region = app.screen.query_one(widget).region
    await pilot.click(widget, offset=(x + dx - region.x, y - region.y))


def landed(screen, index):
    page = screen.query_one(ReaderPage)
    return page.scroll_y == min(screen._top(screen._heads()[index]) - 1, page.max_scroll_y)


async def open_on(pilot, app, name=TRACKED):
    await settle(pilot)
    open_reader(app, skill(app, name)["path"])
    await settle(pilot)
    assert isinstance(app.screen, ReaderScreen)
    return app.screen


# Opening, header, and body


@pytest.mark.asyncio
async def test_v_reads_the_selected_skill(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        s = skill(app, TRACKED)
        app.set_state(selected=s["path"])
        await pilot.press("v")
        await settle(pilot)
        screen = app.screen
        assert isinstance(screen, ReaderScreen)
        shown = screen_text(app)
        assert f"/{TRACKED}" in shown
        assert f"~/.agents/skills/{TRACKED}/SKILL.md" in shown
        assert "ON THIS PAGE" in shown
        assert "description" in shown and "Formatted" in shown and "Markdown" in shown
        doc = screen.query_one(ReaderDoc)
        assert not doc.source.startswith("---")
        assert screen.query_one(FrontMatter).display
        titles = [t for _, t in screen.query_one(Outline).entries]
        assert titles[:3] == ["When to use", "Workflow", "1. Draft the change"]
        assert app.focused is screen.query_one(ReaderPage)


@pytest.mark.asyncio
async def test_v_with_no_selection_reads_the_cursor_row(app, monkeypatch):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.set_state(selected=None, selected_key=None)
        path = skill(app, TRACKED)["path"]
        monkeypatch.setattr(app, "current", lambda: (path, None))
        await pilot.press("v")
        await settle(pilot)
        assert isinstance(app.screen, ReaderScreen) and app.screen.target.path == path


@pytest.mark.asyncio
async def test_nothing_selected_says_what_to_do(app):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        app.set_state(selected=None, selected_key="src:nowhere")
        open_reader(app)
        await settle(pilot)
        assert not isinstance(app.screen, ReaderScreen)
        shown = current(app)
        assert shown is not None
        assert str(shown.text).startswith("Move to a skill, then press v"), "information: no glyph"


@pytest.mark.asyncio
async def test_esc_q_and_the_close_cell_close_and_focus_returns(app):
    async with app.run_test(size=WIDE) as pilot:
        for how in ("escape", "q", "click"):
            await open_on(pilot, app)
            if how == "click":
                await pilot.click("#close")
            else:
                await pilot.press(how)
            await settle(pilot)
            assert app.is_running and not isinstance(app.screen, ReaderScreen), how
            assert app.focused is app.query_one(SkillList)


# Formatted and Markdown


@pytest.mark.asyncio
async def test_r_and_clicks_switch_between_formatted_and_markdown(app):
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_on(pilot, app)
        raw, doc = screen.query_one(RawView), screen.query_one(ReaderDoc)
        await pilot.press("r")
        await pilot.pause()
        assert raw.display and not doc.display and screen.query_one(ModeSwitch).raw
        assert not screen.query_one(Outline).display
        assert not screen.query_one("#outline-hint").display
        find(app, " 1  ---")
        assert "name:" in screen_text(app)
        await pilot.click(ModeSwitch, offset=(2, 0))
        await pilot.pause()
        assert doc.display and not raw.display
        await pilot.click(ModeSwitch, offset=(15, 0))
        await pilot.pause()
        assert raw.display


@pytest.mark.asyncio
async def test_markdown_view_numbers_lines_and_wraps_under_the_text(app):
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_on(pilot, app)
        await pilot.press("r")
        await pilot.pause()
        raw = screen.query_one(RawView)
        rows = raw.rows(raw.size.width)
        text = app.atlas.skill_text(skill(app, TRACKED)["path"])
        assert [n for n, _ in rows if n] == list(range(1, len(text.rstrip("\n").split("\n")) + 1))
        wrapped = [i for i, (n, _) in enumerate(rows) if n == 0]
        assert wrapped, "the description line wraps at 80 columns"
        assert raw.render_line(wrapped[0]).text.startswith(" " * (raw.digits + 2))


@pytest.mark.asyncio
async def test_short_windows_tighten_h2_and_tables_have_row_rules_only(app):
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_on(pilot, app)
        h2 = screen.query_one(ReaderDoc).query("MarkdownH2").first()
        assert screen.has_class("-short") and h2.styles.margin.top == 1
        assert h2.styles.margin.bottom == 0 and h2.styles.border_bottom[0] == "solid"
        table = screen.query_one("MarkdownTableContent")
        assert table.styles.keyline[0] == "none"
        header = table.query(".header").first()
        assert header.styles.text_style.bold and header.styles.border_bottom[0] == "solid"
        assert all(c.styles.border_bottom[0] == "solid" for c in table.query(".cell"))
        await pilot.resize_terminal(120, 36)
        await pilot.pause()
        assert not screen.has_class("-short") and h2.styles.margin.top == 2


def test_markdown_syntax_takes_the_palette():
    lines = reader.highlight(
        ["---", "name: x", "---", "# Title", "Use `code` and [a link](x.md).", "```", "# no", "```"]
    )
    styles = [{(s.start, s.end, str(s.style)) for s in c.spans} for c in lines]
    assert (0, 4, "$atlas-text") in styles[1] and (4, 5, "$atlas-faint") in styles[1]
    assert (0, 1, "$atlas-faint") in styles[3] and (1, 7, "bold $atlas-text") in styles[3]
    assert (5, 9, "$atlas-text") in styles[4] and (16, 22, "$atlas-accent") in styles[4]
    assert styles[6] == {(0, 4, "$atlas-text")}


# Keys and the mouse


@pytest.mark.asyncio
async def test_scroll_keys_move_at_once(app):
    async with app.run_test(size=(100, 24)) as pilot:
        screen = await open_on(pilot, app)
        page = screen.query_one(ReaderPage)
        await pilot.press("j", "j", "down")
        assert page.scroll_y == 3
        await pilot.press("k")
        assert page.scroll_y == 2
        await pilot.press("space")
        assert page.scroll_y > 2 + page.size.height // 2
        before = page.scroll_y
        await pilot.press("b")
        assert page.scroll_y < before
        await pilot.press("G")
        assert page.scroll_y == page.max_scroll_y > 0
        await pilot.press("g")
        assert page.scroll_y == 0
        await pilot.press("end")
        assert page.scroll_y == page.max_scroll_y


@pytest.mark.asyncio
async def test_wheel_and_scrollbar_drag_scroll_the_page(app):
    async with app.run_test(size=(100, 24)) as pilot:
        screen = await open_on(pilot, app)
        page = screen.query_one(ReaderPage)
        await pilot._post_mouse_events([events.MouseScrollDown], page, offset=(20, 5))
        await settle(pilot)
        assert page.scroll_y > 0
        page.scroll_home(animate=False)
        await pilot.pause()
        bar = page.vertical_scrollbar
        assert page.show_vertical_scrollbar
        await pilot.mouse_down(bar, offset=(0, 1))
        await pilot._post_mouse_events([events.MouseMove], bar, offset=(0, 12), button=1)
        await pilot.mouse_up(bar, offset=(0, 12))
        await settle(pilot)
        assert page.scroll_y > 0


@pytest.mark.asyncio
async def test_outline_click_jumps_and_the_cursor_follows_the_scroll(app):
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_on(pilot, app)
        outline, page = screen.query_one(Outline), screen.query_one(ReaderPage)
        index = [t for _, t in outline.entries].index("Checklist")
        await click_text(pilot, app, "Checklist", Outline)
        await pilot.pause()
        assert landed(screen, index) and page.scroll_y > 0
        assert outline.cursor == index and app.focused is page
        page.scroll_home(animate=False)
        await pilot.pause()
        assert outline.cursor == 0
        page.scroll_end(animate=False)
        await pilot.pause()
        assert outline.cursor == len(outline.entries) - 1


@pytest.mark.asyncio
async def test_outline_keys_move_and_enter_jumps(app):
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_on(pilot, app)
        outline, page = screen.query_one(Outline), screen.query_one(ReaderPage)
        await pilot.press("tab")
        assert app.focused is outline
        await pilot.press("j", "j")
        assert outline.cursor == 2 and page.scroll_y == 0
        assert outline.render_line(outline.TOP + 2).text.startswith("▌")
        await pilot.press("enter")
        await pilot.pause()
        assert landed(screen, 2) and page.scroll_y > 0
        assert app.focused is outline
        await pilot.press("G")
        assert outline.cursor == len(outline.entries) - 1


@pytest.mark.asyncio
async def test_outline_hides_when_narrow_and_t_or_a_click_shows_it(app):
    async with app.run_test(size=NARROW) as pilot:
        screen = await open_on(pilot, app)
        outline, hint = screen.query_one(Outline), screen.query_one("#outline-hint")
        assert not outline.display and hint.display
        await pilot.press("t")
        assert outline.display and app.focused is outline and hint.has_class("-on")
        await pilot.click("#outline-hint")
        await pilot.pause()
        assert not outline.display and app.focused is screen.query_one(ReaderPage)
        await pilot.resize_terminal(*WIDE)
        await pilot.pause()
        assert not outline.display, "the choice holds until the reader closes"


@pytest.mark.asyncio
async def test_hover_lights_an_outline_row(app):
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_on(pilot, app)
        outline = screen.query_one(Outline)
        x, y = find(app, "Options")
        await pilot.hover(Outline, offset=(x - outline.region.x, y - outline.region.y))
        assert outline.hover == [t for _, t in outline.entries].index("Options")


# Copy, GitHub, Reveal


@pytest.mark.asyncio
async def test_copy_github_and_reveal_by_key_and_by_click(app, calls, monkeypatch):
    monkeypatch.delenv("SSH_TTY", raising=False)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_on(pilot, app)
        s = skill(app, TRACKED)
        text = app.atlas.skill_text(s["path"])
        url = f"https://github.com/kestrel-dev/claude-skills/blob/HEAD/skills/{TRACKED}/SKILL.md"
        await pilot.press("y", "o", "R")
        for target in ("#copy", "#github", "#reveal"):
            await pilot.click(target)
        await pilot.pause()
        want = [("copy", text, "the Markdown"), ("open_github", url), ("reveal", s["path"])]
        assert calls == want * 2
        assert screen.is_current


@pytest.mark.asyncio
async def test_local_skill_has_no_github_and_ssh_hides_reveal(app, calls, monkeypatch):
    monkeypatch.setenv("SSH_TTY", "/dev/ttys001")
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_on(pilot, app, LOCAL)
        assert not screen.query_one("#github").display
        assert not screen.query_one("#reveal").display
        await pilot.press("o", "R")
        assert calls == []


@pytest.mark.asyncio
async def test_links_open_on_github_and_anchors_jump(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_on(pilot, app)
        doc, page = screen.query_one(ReaderDoc), screen.query_one(ReaderPage)
        await pilot.press("G")
        await pilot.pause()
        await click_text(pilot, app, "Guide", ReaderDoc, dx=1)
        await pilot.pause()
        base = f"https://github.com/kestrel-dev/claude-skills/blob/HEAD/skills/{TRACKED}"
        assert calls[-1] == ("open_github", f"{base}/references/guide.md")
        page.scroll_home(animate=False)
        await pilot.pause()
        doc.post_message(Markdown.LinkClicked(doc, "#workflow"))
        await pilot.pause()
        assert landed(screen, [t for _, t, _ in screen.toc].index("Workflow"))
        assert page.scroll_y > 0


def test_links_map_like_the_web():
    base = ("acme/skills", "skills/tool")
    assert reader.resolve("https://x.dev/a", base) == "https://x.dev/a"
    assert reader.resolve("#top", None) == "#top"
    assert reader.resolve("javascript:alert(1)", base) is None
    assert reader.resolve("//evil.dev/x", base) is None
    assert reader.resolve("refs/a.md", None) is None
    assert (
        reader.resolve("../other/b.md#part", base)
        == "https://github.com/acme/skills/blob/HEAD/skills/other/b.md#part"
    )
    tokens = reader._parser(None)().parse("![logo](img.png) [doc](doc.md) <b>raw</b>")
    kinds = [c.type for c in tokens[1].children or []]
    assert "image" not in kinds and "link_open" not in kinds and "html_inline" not in kinds
    assert "<b>raw</b>" in "".join(c.content for c in tokens[1].children or [])


# Available skills and states


@pytest.mark.asyncio
async def test_available_skill_reads_its_text_through_the_core(app, monkeypatch):
    seen = []
    real = app.atlas.available_text

    def spy(repo, path):
        seen.append((repo, path))
        return real(repo, path)

    monkeypatch.setattr(app.atlas, "available_text", spy)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        repo, items = next((r, a) for r, a in app.data.available.items() if a)
        a = items[0]
        app.set_state(selected=None, selected_key=f"a:{repo}:{a['path']}")
        await pilot.press("v")
        await settle(pilot)
        screen = app.screen
        assert isinstance(screen, ReaderScreen) and seen == [(repo, a["path"])]
        assert screen.text == real(repo, a["path"]) and screen.query_one(FrontMatter).display
        assert f"/{a['name']}" in screen_text(app)
        assert f"{repo} · {a['path']}" in screen_text(app)
        assert not screen.query_one("#reveal").display
        assert screen.query_one("#github").display


@pytest.mark.asyncio
async def test_the_markdown_choice_is_saved(app):
    async with app.run_test(size=WIDE) as pilot:
        await open_on(pilot, app)
        await pilot.press("r", "escape")
        assert app.state.reader_raw
        screen = await open_on(pilot, app)
        assert screen.query_one(RawView).display and screen.query_one(ModeSwitch).raw


@pytest.mark.asyncio
async def test_a_read_error_names_the_reason(app, monkeypatch):
    def gone(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(app.atlas, "skill_text", gone)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_on(pilot, app)
        note = screen.query_one("#note", Static)
        assert note.display and note.has_class("-error")
        assert "✗ Could not load the file: the file is gone." in screen_text(app)
        assert screen.query_one("#copy").disabled


@pytest.mark.asyncio
async def test_an_empty_file_says_so(app, monkeypatch):
    monkeypatch.setattr(app.atlas, "skill_text", lambda path: "")
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_on(pilot, app)
        assert "This SKILL.md is empty" in screen_text(app)
        assert not screen.query_one(FrontMatter).display
        assert not screen.query_one("#outline-hint").display


@pytest.mark.asyncio
async def test_skeleton_shows_after_300ms_while_the_file_loads(app, monkeypatch):
    gate = threading.Event()
    real = app.atlas.skill_text

    def slow(path):
        gate.wait(5)
        return real(path)

    monkeypatch.setattr(app.atlas, "skill_text", slow)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        open_reader(app, skill(app, TRACKED)["path"])
        await pilot.pause()
        screen = app.screen
        state = screen.query_one("#state", Static)
        assert not state.display and screen.query_one("#copy").disabled
        await pilot.pause(0.2)
        assert not state.display, "fast reads show no indicator"
        await pilot.pause(0.2)
        assert state.display and "Loading…" in screen_text(app)
        gate.set()
        await settle(pilot)
        assert not state.display and screen.loaded
        assert not screen.query_one("#copy").disabled


def test_frontmatter_parses_like_the_web():
    pairs, body = reader.split_front(
        '---\nname: "tool"\ndescription: >\n  One\n  two\nnotes: |\n  a\n  b\n---\n# Hi\n'
    )
    assert pairs == [("name", "tool"), ("description", "One two"), ("notes", "a\nb")]
    assert body == "# Hi\n"
    assert reader.split_front("# No frontmatter") == ([], "# No frontmatter")


@pytest.mark.asyncio
async def test_a_read_only_build_shows_the_first_lines_and_says_so(app, monkeypatch):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        monkeypatch.setattr(app.data.insights, "writable", False)
        s = skill(app, TRACKED)
        open_reader(app, s["path"])
        await settle(pilot)
        screen = app.screen
        assert screen.text == s["body_preview"]
        assert reader.READ_ONLY in screen_text(app)
        assert not screen.query_one("#note").has_class("-error")
        assert not screen.query_one("#reveal").display
