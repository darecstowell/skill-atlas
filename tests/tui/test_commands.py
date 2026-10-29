import importlib
import re
import sys
import types
from datetime import datetime, timezone

import pytest
from textual.binding import Binding
from textual.command import CommandList
from textual.geometry import Offset
from textual.widgets import Input, Static

from skill_atlas.core import views
from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui import commands, keys, theme
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.commands import ActionMenu, AtlasCommands, AtlasPalette, Choices, PaletteClose
from skill_atlas.tui.screens import AtlasModal
from skill_atlas.tui.screens.help import HelpScreen, listed_keys
from skill_atlas.tui.widgets.keybar import Hint, KeyBar

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
WIDE, MID, NARROW = (180, 50), (120, 36), (80, 24)
HARNESS = "claude-code:personal"
COPY = "/home/demo/.agents/skills/copywriting/SKILL.md"
MARKETING = "src:coreyhaines31/marketingskills"
# The feature functions in plan.md "Wave 2 contracts", plus this module's own.
CONTRACT = {
    "jobs": {
        "toggle", "set_switch", "update", "update_all", "install", "install_new", "check_again",
        "undo", "delete", "copy", "copy_prompt", "reveal", "open_github", "toast", "push_undo",
    },
    "screens.reader": {"open_reader"},
    "screens.diff": {"open_diff", "open_compare"},
    "screens.history": {"open_history"},
    "screens.confirm": {"confirm_delete"},
    "screens.profiles": {"open_profiles", "save_profile", "apply_profile"},
    "screens.transfer": {"open_export", "copy_manifest", "open_import", "open_restore"},
    "screens.link": {"open_link", "open_watch"},
    "screens.help": {"open_help"},
    "commands": {"open_actions", "open_palette", "toggle_everywhere", "cycle_sort"},
    "widgets.sidepanel": {"open_display"},
    "widgets.detail": {"toggle_description"},
    "widgets.header": {"open_harness_menu", "show_source_errors"},
    "widgets.bulkbar": {
        "focus_bar", "turn_on", "turn_off", "update", "link", "copy_prompt", "save_profile",
        "delete", "clear", "mark_all",
    },
}  # fmt: skip
FLAGS = {
    "open", "read", "switch", "everywhere", "update", "updates", "diff", "history", "copy",
    "github", "reveal", "link", "delete", "install", "new", "mark", "writable", "watch",
}  # fmt: skip


@pytest.fixture
def app(prefs, monkeypatch):
    """The app over fixed demo data. The panel regions are stubs; this file tests keys and menus."""
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setattr("skill_atlas.tui.app.DetailPanel", Static)
    monkeypatch.setattr("skill_atlas.tui.app.SidePanel", Static)
    return AtlasApp(DemoAtlas(now=NOW))


@pytest.fixture
def calls(monkeypatch):
    """Replace the owners' feature functions, and record each call as (name, *args, *kwargs)."""
    seen: list[tuple] = []
    for target in [f"{m}:{f}" for m, fs in CONTRACT.items() if m != "commands" for f in fs]:
        name, _, func = target.partition(":")
        full = f"skill_atlas.tui.{name}"
        try:
            module = importlib.import_module(full)
        except ModuleNotFoundError:
            module = types.ModuleType(full)
            monkeypatch.setitem(sys.modules, full, module)

        def record(app, *args, _f=func, **kw):
            seen.append((_f, *args, *kw.items()))

        monkeypatch.setattr(module, func, record, raising=False)
    return seen


def text_of(app) -> str:
    return "\n".join(s.text for s in app.screen._compositor.render_strips())


def find(app, text, row=None):
    for y, strip in enumerate(app.screen._compositor.render_strips()):
        x = strip.text.find(text)
        if x >= 0 and row in (None, y):
            return (x, y)
    raise AssertionError(f"{text!r} is not on the screen")


def row_ids(screen) -> list[str]:
    lst = screen.query_one(Choices)
    return [o.id for o in (lst.get_option_at_index(i) for i in range(lst.option_count)) if o.id]


async def start(pilot, **state):
    await settle(pilot)
    if state:
        pilot.app.set_state(**state)
        await settle(pilot)
    return pilot.app


# keys.py


def test_no_key_is_bound_twice_in_one_place():
    for where in keys.WHERE:
        names = [n for k in keys.KEYS if k.where == where for n in k.keys.split(",")]
        assert len(names) == len(set(names)), where


def test_no_key_takes_a_terminal_shortcut():
    taken = {n for k in keys.KEYS for n in k.keys.split(",")}
    assert not taken & {"ctrl+c", "ctrl+z", "ctrl+s", "ctrl+q"}


def test_each_run_names_an_owner_function_from_the_contract():
    for k in keys.KEYS:
        action = k.action.removeprefix("app.")
        if action.startswith("run("):
            module, _, func = action[5:-2].partition(":")
            assert func in CONTRACT.get(module, ()), k.action


def test_keys_need_only_known_flags_and_the_bar_names_real_keys():
    assert {k.needs for k in keys.KEYS if k.needs} <= FLAGS
    for context in keys.BAR:
        assert [k.name for k in keys.bar(context)]
    assert [label for _, label in keys.bar_labels("panel")][:3] == ["run", "next", "back to list"]
    from skill_atlas.tui.app import DIGIT_VIEWS

    assert [keys.view_key(v) for v in DIGIT_VIEWS] == [str(n) for n in range(1, 10)]
    assert keys.view_key("similar") == keys.view_key("diverged") == ""


def test_the_changes_rows_match_the_diff_and_history_bindings():
    from skill_atlas.tui.screens.diff import DiffDialog, DiffScreen, Rows
    from skill_atlas.tui.screens.history import HistoryScreen

    bound = {
        name: b.action
        for cls in (Rows, DiffDialog, DiffScreen, HistoryScreen)
        for b in cls.BINDINGS
        if isinstance(b, Binding)
        for name in b.key.split(",")
    }
    rows = [k for k in keys.KEYS if k.where == "changes"]
    assert len(rows) == 12 and not any(k.palette for k in rows if k.help)
    for k in rows:
        for name in k.keys.split(","):
            assert bound.get(name) == k.action, name
    assert (keys.CHANGES, "[ ]", "Show the previous or next file") in keys.help_rows()
    assert keys.key("r").where == "reader" and keys.key("u").where == "app"


def test_help_rows_and_bindings_read_the_table():
    rows = keys.help_rows()
    assert ("Skill", "d", "See changes") in rows and ("App", "?", "All shortcuts") in rows
    palette = next(b for b in keys.bindings("app") if b.key == "ctrl+p")
    assert palette.priority and palette.action == "run('commands:open_palette')"
    assert "fold_all" in keys.actions("list") and "run" in keys.actions("app")


# The key bar


def test_hints_drop_from_the_right_but_help_and_quit_stay():
    hints = [Hint(k, label) for k, label in keys.bar_labels("list")]
    full = sum(h.width + 1 for h in hints) - 1
    assert KeyBar.fit(hints, full) == hints
    short = KeyBar.fit(hints, 30)
    assert [h.key.name for h in short[-2:]] == ["question_mark", "q"]
    assert short[0].key.name == "j" and sum(h.width + 1 for h in short) - 1 <= 30
    assert [h.key.name for h in KeyBar.fit(hints, 5)] == ["question_mark", "q"]


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [NARROW, MID, WIDE])
async def test_the_bar_fits_one_line_and_totals_show_from_160_columns(app, size):
    async with app.run_test(size=size) as pilot:
        await start(pilot, selected=COPY)
        bar = app.query_one(KeyBar)
        line = text_of(app).splitlines()[-1]
        assert bar.region.height == 1 and "? help" in line and "q quit" in line
        assert ("in context" in line) == (size[0] >= 160)


@pytest.mark.asyncio
async def test_the_bar_follows_the_selection_the_marks_and_the_search(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot, selected=COPY)
        bar = app.query_one(KeyBar)
        names = [h.key.name for h in bar.hints()]
        assert names[:4] == ["j", "enter", "x", "u"] and "i" not in names
        app.set_state(selected=None, selected_key=f"a:mattpocock/skills:{_avail_path(app)}")
        await settle(pilot)
        assert "i" in [h.key.name for h in bar.hints()]
        app.set_state(marked={COPY})
        await settle(pilot)
        assert "esc clear" in text_of(app).splitlines()[-1]
        app.set_state(marked=frozenset())
        await pilot.press("slash")
        assert "esc leave search" in text_of(app).splitlines()[-1]


def _avail_path(app) -> str:
    return next(a["path"] for a in app.data.available["mattpocock/skills"] if a.get("new"))


@pytest.mark.asyncio
async def test_hover_and_press_mark_a_hint_and_it_runs_on_mouse_up(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        bar = app.query_one(KeyBar)
        y = MID[1] - 1
        x, _ = find(app, "c compact" if False else "/ search", row=y)
        await pilot.hover(offset=(x, y))
        assert bar._shown[bar._hover].key.name == "slash"
        await pilot.mouse_down(offset=(x, y))
        assert bar._pressed == bar._hover
        await pilot.mouse_up(offset=(x, y))
        await pilot.pause()
        assert isinstance(app.focused, Input) and bar._pressed is None


@pytest.mark.asyncio
async def test_a_press_that_moves_to_another_hint_does_not_run(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        y = MID[1] - 1
        search, _ = find(app, "/ search", row=y)
        quit_x, _ = find(app, "q quit", row=y)
        await pilot.mouse_down(offset=(quit_x, y))
        await pilot.mouse_up(offset=(search, y))
        await pilot.pause()
        assert app.is_running and not isinstance(app.focused, Input)


@pytest.mark.asyncio
async def test_key_hints_off_hides_the_bar(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        app.set_state(key_hints=False)
        await settle(pilot)
        assert not app.query_one(KeyBar).display


@pytest.mark.asyncio
async def test_a_running_update_shows_on_its_hint(app):
    from skill_atlas.tui.messages import JobChanged

    async with app.run_test(size=MID) as pilot:
        await start(pilot, selected=COPY)
        bar = app.query_one(KeyBar)
        bar.post_message(JobChanged({"kind": "update", "done": False, "items": {}}))
        await pilot.pause()
        assert any(h.busy and h.label == "Updating…" for h in bar.hints())
        bar.post_message(JobChanged(None))
        await pilot.pause()
        assert not any(h.busy for h in bar.hints()) and bar._timer is None


# Help


@pytest.mark.asyncio
async def test_question_mark_opens_help_and_closes_it(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpScreen)
        shown = text_of(app)
        assert "Keyboard shortcuts" in shown and "MOVE" in shown and "See changes" in shown
        await pilot.press("tab")
        assert isinstance(app.screen, HelpScreen) and isinstance(app.focused, Input)
        await pilot.press("question_mark")
        assert not isinstance(app.screen, HelpScreen)
        await pilot.press("question_mark")
        await pilot.press("escape")
        assert not isinstance(app.screen, HelpScreen)


@pytest.mark.asyncio
async def test_help_lists_every_row_and_filters(app):
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        await pilot.press("question_mark")
        help_screen = app.screen
        assert len(row_ids(help_screen)) == len(listed_keys())
        assert ("9", "Show skills to review") in [row[2:] for row in listed_keys()]
        await pilot.press(*"github")
        listed = [keys.KEYS[int(i)].help for i in row_ids(help_screen)]
        assert set(listed) == {"Open on GitHub", "Link to GitHub…"}
        await pilot.press(*"zzz")
        assert "No keys match “githubzzz”" in text_of(app)


@pytest.mark.asyncio
async def test_enter_on_a_filtered_help_row_runs_its_key(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        await pilot.press("question_mark", *"compact", "enter")
        await settle(pilot)
        assert not isinstance(app.screen, HelpScreen) and app.state.compact


@pytest.mark.asyncio
async def test_click_a_help_row_runs_it_and_the_close_cell_closes(app):
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        await pilot.press("question_mark", *"rows")
        await pilot.click(offset=find(app, "Compact rows"))
        await settle(pilot)
        assert not isinstance(app.screen, HelpScreen) and app.state.compact
        await pilot.press("question_mark")
        await pilot.click(offset=find(app, "✕"))
        assert not isinstance(app.screen, HelpScreen)
        await pilot.press("question_mark")
        await pilot.click(offset=(1, 1))
        assert not isinstance(app.screen, HelpScreen)


# The command palette


@pytest.mark.asyncio
async def test_ctrl_p_opens_the_atlas_palette_with_the_selection_color(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        await pilot.press("ctrl+p")
        await settle(pilot)
        assert isinstance(app.screen, AtlasPalette)
        lst = app.screen.query_one(CommandList)
        style = lst.get_component_rich_style("option-list--option-highlighted")
        want = theme.colors(app)["atlas-selection"]
        assert style.bgcolor is not None and style.bgcolor.triplet.hex == want.lower()
        await pilot.press("escape")
        assert not isinstance(app.screen, AtlasPalette)
        await pilot.press("ctrl+p")
        await settle(pilot)
        await pilot.click(PaletteClose, offset=(1, 0))
        await settle(pilot)
        assert not isinstance(app.screen, AtlasPalette)


@pytest.mark.asyncio
async def test_palette_lists_actions_views_harnesses_and_display(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot, selected=COPY)
        entries = {e.title: e for e in AtlasCommands(app.screen).commands()}
        assert entries["See changes"].key == "d" and entries["Update"].key == "u"
        assert entries["Show skills to review"].key == "9" and entries["Show issues"].key == "5"
        assert "Switch to all harnesses" in entries and "Use the Stone palette" in entries
        assert "Show project skills" in entries and "Sort by most used" in entries
        assert entries["Use full motion"].note == "current" and "Turn off motion" in entries
        assert "Reload" in entries and "Quit" in entries and "Keys" not in entries
        assert "Install an available skill" not in entries
        assert "Compare with its other copy" in entries
        assert (
            "Export the skill set to a file…" in entries
            and "Import a skill set from a file…" in entries
        )


@pytest.mark.asyncio
async def test_palette_goes_to_a_skill_by_fuzzy_name(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot, view="off")
        await pilot.press("ctrl+p", *"go to copywrit")
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        assert app.state.selected == COPY and app.state.view == "all"


@pytest.mark.asyncio
async def test_palette_runs_a_command_on_click(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        await pilot.press("ctrl+p", *"show updates")
        await settle(pilot)
        await pilot.click(offset=find(app, "Show updates"))
        await settle(pilot)
        assert app.state.view == "updates" and not isinstance(app.screen, AtlasPalette)


class Probe(AtlasModal[None]):
    """A dialog with the modal keys, as AtlasModal binds them."""

    BINDINGS = keys.bindings("modal")

    def compose(self):
        yield Static("Probe")


@pytest.mark.asyncio
async def test_q_closes_a_dialog_types_in_a_field_and_quits_from_the_main_screen(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot)
        app.push_screen(Probe())
        await settle(pilot)
        await pilot.press("q")
        await settle(pilot)
        assert len(app.screen_stack) == 1 and app.return_code is None
        await pilot.press("question_mark", "q")
        await settle(pilot)
        assert isinstance(app.screen, HelpScreen) and app.screen.query_one(Input).value == "q"
        await pilot.press("escape")
        await settle(pilot)
        await pilot.press("q")
        await settle(pilot)
        assert app.return_code == 0


@pytest.mark.asyncio
async def test_shift_m_and_the_header_commands_call_their_owners(app, calls):
    async with app.run_test(size=MID) as pilot:
        await start(pilot, selected=COPY)
        await pilot.press("M")
        await settle(pilot)
        assert ("toggle_description",) in calls
        entries = {e.title: e for e in AtlasCommands(app.screen).commands()}
        assert entries["Show unchecked sources"].note == "1"
        await entries["Switch harness"].run()
        await entries["Show unchecked sources"].run()
        assert ("open_harness_menu",) in calls and ("show_source_errors",) in calls


@pytest.mark.asyncio
async def test_marks_bring_the_bulk_commands_and_tab_goes_to_the_bulk_bar(app):
    from skill_atlas.tui.widgets.bulkbar import BulkBar
    from skill_atlas.tui.widgets.skill_list import SkillList

    async with app.run_test(size=MID) as pilot:
        await start(pilot, selected=COPY)
        titles = [e.title for e in AtlasCommands(app.screen).commands()]
        assert "Mark all shown skills" in titles and "Clear marks" not in titles
        app.set_state(marked=frozenset({COPY}))
        await settle(pilot)
        titles = [e.title for e in AtlasCommands(app.screen).commands()]
        assert titles[: len(commands.BULK)] == [t for t, _ in commands.BULK]
        app.query_one(SkillList).focus()
        await pilot.press("tab")
        await settle(pilot)
        assert isinstance(app.focused, BulkBar)
        entries = {e.title: e for e in AtlasCommands(app.screen).commands()}
        await entries["Clear marks"].run()
        await settle(pilot)
        assert not app.state.marked


# The action menu


@pytest.mark.asyncio
async def test_ctrl_k_opens_the_menu_for_an_outdated_skill(app, calls, monkeypatch):
    downloads = []
    monkeypatch.setattr(app.atlas, "diff", lambda *a: downloads.append(a))
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot, selected=COPY)
        await pilot.press("ctrl+k")
        await settle(pilot)
        menu = app.screen
        assert isinstance(menu, ActionMenu)
        ids = row_ids(menu)
        assert ids[:4] == ["open", "read", "switch", "everywhere"] and ids[-1] == "delete"
        assert {"update", "diff", "history", "compare", "copy", "copy_path", "reveal"} <= set(ids)
        shown = text_of(app)
        top = menu.query_one("#top")
        assert menu.query_one("#filter").parent is top and menu.query_one(Choices).region.y == (
            top.region.bottom
        )
        assert "Actions · /copywriting" in shown and "Update · " not in shown and not downloads
        assert re.search(r"History · \d+ versions?", shown) and "Move to Trash…" in shown
        assert "Turn off in Claude Code · personal" in shown
        await pilot.click(offset=find(app, "See changes"))
        await settle(pilot)
        assert ("open_diff", "copywriting") in calls and not isinstance(app.screen, ActionMenu)


@pytest.mark.asyncio
async def test_typing_a_key_in_the_menu_puts_its_action_first(app, calls):
    async with app.run_test(size=MID) as pilot:
        await start(pilot, selected=COPY)
        await pilot.press("ctrl+k", "u", "enter")
        await settle(pilot)
        assert ("update", ["copywriting"]) in calls


@pytest.mark.asyncio
async def test_menu_keys_move_and_close(app, calls):
    async with app.run_test(size=MID) as pilot:
        await start(pilot, selected=COPY)
        await pilot.press("ctrl+k")
        menu = app.screen
        lst = menu.query_one(Choices)
        await pilot.press("down", "down")
        assert lst.highlighted == 2
        await pilot.press("end")
        assert lst.get_option_at_index(lst.highlighted).id == "delete"
        await pilot.press("home")
        assert lst.highlighted == 0
        await pilot.press("tab")
        assert not isinstance(app.screen, ActionMenu)
        await pilot.press("ctrl+k")
        await pilot.press("escape")
        assert not isinstance(app.screen, ActionMenu)
        await pilot.press("ctrl+k")
        await pilot.click(offset=find(app, "✕"))
        assert not isinstance(app.screen, ActionMenu)


@pytest.mark.asyncio
async def test_the_menu_opens_beside_its_anchor_and_stays_on_screen(app):
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot, selected=COPY)
        for at in (Offset(4, 3), Offset(170, 48), Offset(0, 0)):
            commands.open_actions(app, COPY, at=at)
            await settle(pilot)
            box = app.screen.query_one("#box").region
            assert app.screen.region.contains_region(box), at
            assert box.y > at.y or box.bottom <= at.y, at
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_right_click_on_a_row_opens_its_menu(app):
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        x, y = find(app, "/copywriting")
        await pilot.click(offset=(x + 2, y), button=3)
        await settle(pilot)
        assert isinstance(app.screen, ActionMenu) and app.screen.target.key == COPY


@pytest.mark.asyncio
async def test_group_menu_has_group_actions(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        commands.open_actions(app, MARKETING)
        await settle(pilot)
        assert app.state.selected_key == MARKETING
        ids = row_ids(app.screen)
        assert ids[0] == "open" and {"switch", "update", "github", "delete"} <= set(ids)
        assert re.search(r"Turn (on|off) all 37 in Claude Code · personal", text_of(app))
        await pilot.click(offset=find(app, "Open on GitHub"))
        await settle(pilot)
        assert ("open_github", "https://github.com/coreyhaines31/marketingskills") in calls


@pytest.mark.asyncio
async def test_available_and_new_skills_offer_install_and_dismiss(app, calls):
    async with app.run_test(size=WIDE) as pilot:
        await start(pilot)
        key = f"a:mattpocock/skills:{_avail_path(app)}"
        commands.open_actions(app, key)
        await settle(pilot)
        assert row_ids(app.screen) == ["open", "read", "install", "dismiss", "github"]
        await pilot.press("escape")
        commands.open_actions(app, "src:mattpocock/skills")
        await settle(pilot)
        assert {"new", "dismiss"} <= set(row_ids(app.screen))
        await pilot.press(*"install", "enter")
        await settle(pilot)
        installed = next(c for c in calls if c[0] == "install")
        assert installed[1] == "mattpocock/skills" and len(installed[2]) == 3


@pytest.mark.asyncio
async def test_over_ssh_the_menu_has_no_reveal(app, monkeypatch):
    monkeypatch.setenv("SSH_TTY", "/dev/ttys001")
    async with app.run_test(size=MID) as pilot:
        await start(pilot, selected=COPY)
        await pilot.press("ctrl+k")
        assert "reveal" not in row_ids(app.screen)
        assert "reveal" not in commands.flags(app)


@pytest.mark.asyncio
async def test_flags_follow_the_marks(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot, selected=COPY)
        assert {"open", "update", "diff", "switch", "mark"} <= commands.flags(app)
        plugin = next(
            s["path"]
            for s in app.data.skills
            if s.get("scope") == "plugin" and s.get("status") != "stale" and views.loads(HARNESS, s)
        )
        app.set_state(marked={plugin})
        await settle(pilot)
        have = commands.flags(app)
        assert "copy" in have and "update" not in have and "delete" not in have


@pytest.mark.asyncio
async def test_watch_hides_in_the_new_view_and_ctrl_k_uses_the_cursor_row(app):
    async with app.run_test(size=MID) as pilot:
        await start(pilot, view="new")
        assert "watch" not in commands.flags(app) and "writable" in commands.flags(app)
        app.set_state(view="all", selected=None, selected_key=None)
        await settle(pilot)
        assert "watch" in commands.flags(app)
        await pilot.press("ctrl+k")
        await settle(pilot)
        path, item = app.current()
        assert isinstance(app.screen, ActionMenu) and app.screen.target.key == (path or item)


# Commands with no other owner


@pytest.mark.asyncio
async def test_s_cycles_the_sort_and_toasts(app):
    async with app.run_test(size=MID, notifications=True) as pilot:
        await start(pilot)
        await pilot.press("s")
        await settle(pilot)
        assert app.state.sort == "uses" and "Sorted by most used." in text_of(app)


@pytest.mark.asyncio
async def test_shift_x_turns_a_skill_off_in_every_harness(app, calls):
    async with app.run_test(size=MID) as pilot:
        await start(pilot, selected=COPY)
        await pilot.press("X")
        await settle(pilot)
        switched = [c for c in calls if c[0] == "set_switch"]
        assert len(switched) == 1 and len(switched[0][1]) > 1 and switched[0][3] is False


@pytest.mark.asyncio
async def test_stop_watching_and_dismiss_call_the_core(app):
    async with app.run_test(size=MID, notifications=True) as pilot:
        await start(pilot)
        said = []
        real = app.atlas.watch

        def fail(*a):
            raise ValueError("run `gh auth login`")

        app.atlas.watch = fail
        commands.toast, keep = (lambda _app, text, **kw: said.append(str(text))), commands.toast
        await commands.stop_watching(app, "vercel-labs/agent-skills")
        commands.toast, app.atlas.watch = keep, real
        assert said == [f"Could not stop watching: run gh auth login. {commands.LOCK_FIX}"]
        await commands.stop_watching(app, "vercel-labs/agent-skills")
        await settle(pilot)
        assert "vercel-labs/agent-skills" not in app.data.updates["watched"]
        assert "Stopped watching vercel-labs/agent-skills." in text_of(app)
        await pilot.press("z")
        await settle(pilot)
        assert "vercel-labs/agent-skills" in app.data.updates["watched"]
        await commands.dismiss_new(app, "mattpocock/skills")
        await settle(pilot)
        assert not views.new_in(app.data.insights, "mattpocock/skills")
