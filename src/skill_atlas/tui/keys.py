"""Every key binding in one table. The app, the key bar, the help, and the palette read it."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from textual.binding import Binding, BindingType

WHERE = ("app", "list", "reader", "modal", "changes")
REVEAL = "Reveal in Finder" if sys.platform == "darwin" else "Reveal in the file manager"
CHANGES = "Changes and history"


@dataclass(frozen=True)
class Key:
    """keys: Textual key names. where: the widget that binds it ("changes" rows are for the
    help; screens/diff.py and history.py bind them).

    show: the key as people read it. needs: a flag from commands.flags() that the key needs;
    the key bar and the palette leave the key out without it.
    """

    keys: str
    action: str
    label: str
    help: str
    group: str
    where: str
    show: str = ""
    needs: str = ""
    palette: bool = True
    priority: bool = False

    @property
    def name(self) -> str:
        """The first Textual key name. BAR and key() use it."""
        return self.keys.split(",")[0]

    @property
    def short(self) -> str:
        """The first key in show, for the key bar, the palette, and the action menu."""
        return self.show.split(", ")[0]


KEYS: tuple[Key, ...] = (
    # Move
    Key("j,down", "cursor_down", "move", "Move between skills", "Move", "list", "j/k",
        palette=False),
    Key("k,up", "cursor_up", "", "", "Move", "list"),
    Key("pagedown", "page_down", "", "Move one page down or up", "Move", "list", "pgdn/pgup",
        palette=False),
    Key("pageup", "page_up", "", "", "Move", "list"),
    Key("home", "first", "", "Go to the top or the end", "Move", "list", "home/end",
        palette=False),
    Key("end", "last", "", "", "Move", "list"),
    Key("enter", "select", "open", "Open details, or expand or collapse a repo", "Move", "list",
        "enter", needs="open"),
    Key("left", "fold", "", "Fold the group", "Move", "list", "left", needs="open"),
    Key("right", "unfold", "", "Unfold the group", "Move", "list", "right", needs="open"),
    Key("H,shift+h", "fold_all", "", "Fold all groups", "Move", "list", "shift+h"),
    Key("L,shift+l", "unfold_all", "", "Unfold all groups", "Move", "list", "shift+l"),
    Key("tab", "app.run('widgets.bulkbar:focus_bar')", "",
        "Move between the list, the panel, and the search", "Move", "list", "tab", palette=False),
    # Skill
    Key("x,space", "run('jobs:toggle')", "toggle", "Turn on or off", "Skill", "app", "x, space",
        needs="switch"),
    Key("X,shift+x", "run('commands:toggle_everywhere')", "", "Turn on or off in every harness",
        "Skill", "app", "shift+x", needs="everywhere"),
    Key("u", "run('jobs:update')", "update", "Update", "Skill", "app", "u", needs="update"),
    Key("U,shift+u", "run('jobs:update_all')", "update all", "Update all", "Skill", "app",
        "shift+u", needs="updates"),
    Key("i", "run('jobs:install')", "install", "Install an available skill", "Skill", "app", "i",
        needs="install"),
    Key("I,shift+i", "run('jobs:install_new')", "", "Install new skills", "Skill", "app",
        "shift+i", needs="new"),
    Key("v", "run('screens.reader:open_reader')", "read", "Read the whole SKILL.md", "Skill",
        "app", "v", needs="read"),
    Key("d", "run('screens.diff:open_diff')", "changes", "See changes", "Skill", "app", "d",
        needs="diff"),
    Key("h", "run('screens.history:open_history')", "history", "History", "Skill", "app", "h",
        needs="history"),
    Key("y", "run('jobs:copy_prompt')", "copy", "Copy as prompt", "Skill", "app", "y",
        needs="copy"),
    Key("o", "run('jobs:open_github')", "github", "Open on GitHub", "Skill", "app", "o",
        needs="github"),
    Key("R,shift+r", "run('jobs:reveal')", "reveal", REVEAL, "Skill", "app", "shift+r",
        needs="reveal"),
    Key("l", "run('screens.link:open_link')", "link", "Link to GitHub…", "Skill", "app", "l",
        needs="link"),
    Key("delete,backspace", "run('screens.confirm:confirm_delete')", "delete",
        "Move to Trash…", "Skill", "app", "delete", needs="delete"),
    Key("ctrl+k", "run('commands:open_actions')", "actions", "Actions for the skill", "Skill",
        "app", "ctrl+k", needs="open"),
    Key("M,shift+m", "run('widgets.detail:toggle_description')", "",
        "Show more or less of the description", "Skill", "app", "shift+m", needs="read"),
    Key("z", "run('jobs:undo')", "undo", "Undo", "Skill", "app", "z"),
    # Marks
    Key("m", "mark", "mark", "Mark for bulk actions", "Marks", "list", "m", needs="mark"),
    Key("J,shift+j", "extend_down", "", "Extend the marks down or up", "Marks", "list",
        "shift+j/k", palette=False),
    Key("K,shift+k", "extend_up", "", "", "Marks", "list"),
    Key("ctrl+a", "mark_all", "", "Mark all shown", "Marks", "list", "ctrl+a",
        needs="writable", palette=False),
    # View
    Key("slash", "search", "search", "Search", "View", "app", "/"),
    Key("1", "view(1)", "", "Show a view", "View", "app", "1–9", palette=False),
    *(Key(str(n), f"view({n})", "", "", "View", "app") for n in range(2, 10)),
    Key("left_square_bracket", "harness(-1)", "", "Show the previous or next harness", "View",
        "app", "[ ]", palette=False),
    Key("right_square_bracket", "harness(1)", "", "", "View", "app"),
    Key("s", "run('commands:cycle_sort')", "sort", "Sort by name, uses, recent, or cost", "View",
        "app", "s"),
    Key("c", "compact", "", "Compact rows", "View", "app", "c"),
    Key("backslash", "toggle_detail", "", "Show or hide the details panel", "View", "app", "\\"),
    Key("comma", "run('widgets.sidepanel:open_display')", "", "Display settings", "View", "app",
        ","),
    # Sources
    Key("ctrl+r", "run('jobs:check_again')", "", "Check for updates again", "Sources", "app",
        "ctrl+r"),
    Key("w", "run('screens.link:open_watch')", "", "Watch a source…", "Sources", "app", "w",
        needs="watch"),
    Key("p", "run('screens.profiles:open_profiles')", "", "Profiles", "Sources", "app", "p",
        needs="writable"),
    # App
    Key("ctrl+p", "run('commands:open_palette')", "commands", "All commands", "App", "app",
        "ctrl+p", palette=False, priority=True),
    Key("escape", "escape", "clear", "Close or clear", "App", "app", "esc", palette=False),
    Key("question_mark", "help", "help", "All shortcuts", "App", "app", "?"),
    Key("q", "quit", "quit", "Quit", "App", "app", "q"),
    # Every dialog (AtlasModal). A text field still takes q as a letter.
    Key("escape", "close", "", "", "App", "modal"),
    Key("q", "close", "", "Close the dialog", "App", "modal", "q", palette=False),
    # Reader
    Key("r", "raw", "", "Formatted or Markdown, in the reader", "Reader", "reader", "r",
        palette=False),
    # Changes and history
    Key("j,down", "move(1)", "", "Move in the list or the diff", CHANGES, "changes", "j/k",
        palette=False),
    Key("k,up", "move(-1)", "", "", CHANGES, "changes"),
    Key("pagedown", "page(1)", "", "Move one page down or up", CHANGES, "changes", "pgdn/pgup",
        palette=False),
    Key("pageup", "page(-1)", "", "", CHANGES, "changes"),
    Key("home", "go(0)", "", "Go to the top or the end", CHANGES, "changes", "home/end",
        palette=False),
    Key("end", "go(-1)", "", "", CHANGES, "changes"),
    Key("left_square_bracket", "file(-1)", "", "Show the previous or next file", CHANGES,
        "changes", "[ ]", palette=False),
    Key("right_square_bracket", "file(1)", "", "", CHANGES, "changes"),
    Key("enter", "activate", "", "Open the file or the unchanged lines", CHANGES, "changes",
        "enter", palette=False),
    Key("u", "update", "", "Update the skill, in See changes", CHANGES, "changes", "u",
        palette=False),
    Key("r", "restore", "", "Restore the selected version, in History", CHANGES, "changes", "r",
        palette=False),
    Key("t", "again", "", "Try again after an error, in History", CHANGES, "changes", "t",
        palette=False),
)  # fmt: skip

# The key bar for each context, most important first. Hints drop from the right as the bar
# narrows, except the STICKY ones. "name=label" gives a hint its own label in that context.
BAR: dict[str, tuple[str, ...]] = {
    "list": ("enter", "ctrl+k", "question_mark"),
    "marks": ("x", "u", "y", "l", "delete=trash", "escape", "question_mark", "q"),
    "search": ("escape=leave search", "question_mark", "q"),
    "panel": ("enter=run", "tab=next", "escape=back to list", "question_mark", "q"),
}
STICKY = frozenset({"question_mark", "q"})
_BY_NAME = {k.name: k for k in reversed(KEYS)}


def bindings(where: str) -> list[BindingType]:
    """Textual bindings for one place. The key bar draws the hints, so none show in a footer."""
    return [
        Binding(
            k.keys,
            k.action,
            k.help or k.label,
            show=False,
            key_display=k.show or None,
            priority=k.priority,
        )
        for k in KEYS
        if k.where == where
    ]


def actions(where: str) -> set[str]:
    """Action names without their arguments, such as "view" for "view(1)"."""
    return {k.action.partition("(")[0] for k in KEYS if k.where == where}


def key(name: str) -> Key:
    """The Key whose first Textual key name is name, such as "ctrl+k"."""
    return _BY_NAME[name]


def bar(context: str = "list") -> list[Key]:
    """The keys of one key bar context, in order."""
    return [k for k, _ in bar_labels(context)]


def bar_labels(context: str = "list") -> list[tuple[Key, str]]:
    """(key, label) for each hint of one key bar context, in order."""
    out = []
    for entry in BAR[context]:
        name, _, label = entry.partition("=")
        k = key(name)
        out.append((k, label or k.label))
    return out


def help_rows() -> list[tuple[str, str, str]]:
    """(group, key text, help text) for each row that the help screen lists."""
    return [(k.group, k.show, k.help) for k in KEYS if k.help]


def view_key(view: str) -> str:
    """The digit that shows a view, from app.DIGIT_VIEWS, or "" when it has none."""
    from .app import DIGIT_VIEWS

    return str(DIGIT_VIEWS.index(view) + 1) if view in DIGIT_VIEWS else ""
