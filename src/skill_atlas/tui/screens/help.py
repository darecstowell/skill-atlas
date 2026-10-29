"""The keyboard shortcuts sheet (`?`), read from keys.KEYS."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual import events
from textual.binding import Binding, BindingType
from textual.content import Content
from textual.fuzzy import Matcher
from textual.widgets.option_list import Option

from .. import keys
from ..commands import VIEW_TITLES, FilterModal
from ..widgets import app_of

if TYPE_CHECKING:
    from ..app import AtlasApp

KEY_COLS = 12
WIDTH = 64
FOOT = "Right-click a row to see its actions.\nFor a screen reader, run atlas to use the web page."
TOP = ("ctrl+p",)  # keys listed above the groups, with no heading


class HelpScreen(FilterModal):
    """Every key with what it does, by group. A click or enter on a row runs it."""

    PLACEHOLDER = "Filter keys"
    PASS_KEYS = frozenset({"question_mark"})
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("question_mark", "close", "Close", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    HelpScreen #box { width: 64; }
    """

    def heading(self) -> Content:
        return Content.styled("Keyboard shortcuts", "bold $atlas-text")

    def footer(self) -> str:
        return FOOT

    def on_mount(self) -> None:
        super().on_mount()
        self._fit()

    def on_resize(self, event: events.Resize) -> None:
        self._fit()

    def _fit(self) -> None:
        cols, lines = self.app.size
        self.query_one("#box").styles.width = min(WIDTH, cols - 2)
        # Border 2, title 1, filter 2, list gap 1, footer 3, and 1 row of screen on each side.
        self.choices.styles.max_height = max(3, lines - 2 - 2 - 1 - 2 - 1 - 3)

    def _row(self, i: int, show: str, text: str) -> Option:
        return Option(
            Content.assemble((show.ljust(KEY_COLS), "$atlas-accent"), (text, "$atlas-text")),
            id=str(i),
        )

    def rows(self, query: str) -> list[Option | None]:
        listed = listed_keys()
        if query:
            matcher = Matcher(query)
            scored = []
            for i, _group, show, text in listed:
                exact = query in show.split(", ") or query == show
                score = matcher.match(text)
                if exact or score > 0:
                    scored.append((not exact, -score, i, show, text))
            if not scored:
                return [Option(Content(f"No keys match “{query}”"), disabled=True)]
            return [self._row(i, show, text) for *_, i, show, text in sorted(scored)]
        out: list[Option | None] = []
        last = ""
        for i, group, show, text in listed:
            if group != last:
                if out:
                    out.append(Option(Content(" "), disabled=True))
                last = group
                out.append(Option(Content.styled(group.upper(), "$atlas-muted"), disabled=True))
            out.append(self._row(i, show, text))
        return out

    def choose(self, option_id: str) -> None:
        k = keys.KEYS[int(option_id)]
        self.dismiss(None)
        if k.action != "help":
            app = app_of(self)
            app.call_later(app.run_key, k)


def listed_keys() -> list[tuple[int, str, str, str]]:
    """(index in KEYS, group, key text, help) per row. Each digit gets a row for its view.

    The TOP keys come first, in the group "".
    """
    from ..app import DIGIT_VIEWS

    top: list[tuple[int, str, str, str]] = []
    out: list[tuple[int, str, str, str]] = []
    for i, k in enumerate(keys.KEYS):
        if k.action.startswith("view("):
            n = int(k.action[5:-1])
            if n <= len(DIGIT_VIEWS):
                out.append((i, k.group, k.name, VIEW_TITLES[DIGIT_VIEWS[n - 1]]))
        elif k.help and k.name in TOP:
            top.append((i, "", k.show, k.help))
        elif k.help:
            out.append((i, k.group, k.show, k.help))
    return top + out


def open_help(app: AtlasApp) -> None:
    """`?`: show every key. A second `?` or esc closes it."""
    if not isinstance(app.screen, HelpScreen):
        app.push_screen(HelpScreen())
