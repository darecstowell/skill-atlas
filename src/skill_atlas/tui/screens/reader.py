"""The SKILL.md reader: the formatted file or its Markdown, with an outline of its sections."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content, Span
from textual.geometry import Region, Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Markdown, Static
from textual.widgets.markdown import MarkdownFence

from ...core import views
from ...updates import skill_name
from .. import keys, theme
from ..widgets import app_of
from . import AtlasModal, CloseCell, HintButton

if TYPE_CHECKING:
    from ..app import AtlasApp

SKELETON_AFTER = 0.3
SKELETON_KEEP = 0.5
OUTLINE_FROM = 100
HINTS = (
    ("t", "Outline", "outline", "Show or hide the outline", "outline-hint"),
    ("y", "Copy", "copy", "Copy the Markdown", "copy"),
    ("o", "GitHub ↗", "github", "Open the file on GitHub", "github"),
    ("shift+r", "Reveal", "reveal", "Show the folder", "reveal"),
    ("esc", "Close", "close", "Close the reader", "close-hint"),
)
SHORT = 30
READ_ONLY = "This read-only build has only the first lines. Run atlas to read the whole file."
TEXT, MUTED, FAINT, LINK = "$atlas-text", "$atlas-muted", "$atlas-faint", "$atlas-accent"
# The web's avatar tokens, `--id-bg` and `--id-fg`, as (lightness, chroma) per mode.


@dataclass(frozen=True)
class Target:
    """What the reader shows: a scanned skill (`path`) or an available one (`repo`, `file`)."""

    name: str
    where: str
    label: str
    hue: int
    path: str | None = None
    repo: str | None = None
    file: str = ""
    base: tuple[str, str] | None = None  # (repo, folder) that relative links resolve against
    preview: str | None = None  # read-only builds: the first lines only

    @property
    def github(self) -> str:
        if self.base is None:
            return ""
        repo, folder = self.base
        return f"https://github.com/{repo}/blob/HEAD/{folder + '/' if folder else ''}SKILL.md"


def open_reader(app: AtlasApp, path: str | None = None) -> None:
    """Open the reader on a skill path or `a:<repo>:<path>`; by default, the current row."""
    if path is None:
        skill, item = app.current()
        path = skill or item
    target = target_of(app, path)
    if target is None:
        app.notify("Move to a skill, then press v to read its SKILL.md.")
        return
    app.push_screen(ReaderScreen(target))


def target_of(app: AtlasApp, key: str | None) -> Target | None:
    ins = app.data.insights
    if ins is None or not key:
        return None
    if key.startswith("a:"):
        repo, _, file = key[2:].partition(":")
        if not file:
            return None
        found = next((a for a in app.data.available.get(repo, []) if a.get("path") == file), {})
        avail = {"kind": "avail", "repo": repo, "path": file}
        return Target(
            name=found.get("name") or skill_name(repo, file),
            where=f"{repo} · {file}",
            label=repo,
            hue=views.hue(repo),
            repo=repo,
            file=file,
            base=base_of(avail),
        )
    s = app.data.skill(key)
    if s is None:
        return None
    return Target(
        name=s.get("invoke") or s["name"],
        where=views.tilde(s["path"], (app.data.scan or {}).get("home", "")),
        label=views.group_label(ins, s),
        hue=views.hue_of(ins, s),
        path=s["path"],
        base=base_of(s),
        preview=None if ins.writable else s.get("body_preview") or "",
    )


def base_of(s: dict) -> tuple[str, str] | None:
    """The skill's folder on GitHub, as the web's skillBase: none for plugin skills."""
    repo = views.repo_of(s)
    if not repo or s.get("scope") == "plugin":
        return None
    file = s.get("path") if s.get("kind") == "avail" else (s.get("origin") or {}).get("skillPath")
    return (repo, re.sub(r"/?SKILL\.md$", "", file)) if file else None


def join_path(folder: str, rel: str) -> str:
    out = folder.split("/") if folder else []
    for part in re.sub(r"[?#].*$", "", rel).split("/"):
        if part == "..":
            if out:
                out.pop()
        elif part and part != ".":
            out.append(part)
    return "/".join(out)


def resolve(href: str, base: tuple[str, str] | None) -> str | None:
    """Where a link goes: the same URL, the file on GitHub, or None for no link."""
    if re.match(r"(https?:|mailto:)", href, re.I) or href.startswith("#"):
        return href
    if re.match(r"[a-z][\w+.-]*:", href, re.I | re.A) or href.startswith("//") or not base:
        return None
    repo, folder = base
    frag = href[href.index("#") :] if "#" in href else ""
    return f"https://github.com/{repo}/blob/HEAD/{join_path(folder, href)}{frag}"


def slug(text: str) -> str:
    return re.sub(r"\s+", "-", re.sub(r"[^\w\s-]", "", text.lower()).strip())


def split_front(text: str) -> tuple[list[tuple[str, str]], str]:
    """The frontmatter as (key, value) pairs, and the rest. A port of the web's parser."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    m = re.match(r"---\n([\s\S]*?)\n---[ \t]*(?:\n|$)", text)
    if not m:
        return [], text
    front: list[list[str]] = []
    block = False
    for ln in m[1].split("\n"):
        km = re.fullmatch(r"([A-Za-z_][\w-]*):\s*(.*)", ln, re.A)
        if km:
            block = re.fullmatch(r"\|[-+]?", km[2]) is not None
            folded = re.fullmatch(r"[|>][-+]?", km[2]) is not None
            front.append([km[1], "" if folded else re.sub(r"^([\"'])(.*)\1$", r"\2", km[2])])
        elif front and ln.strip():
            f = front[-1]
            f[1] = f[1] + ("\n" if block else " ") + ln.strip() if f[1] else ln.strip()
    return [(k, v) for k, v in front], text[m.end() :]


def reason(error: Exception) -> str:
    if isinstance(error, FileNotFoundError):
        return "the file is gone. Press ctrl+p and choose Reload to scan again"
    if isinstance(error, PermissionError):
        return "you do not have permission to read it. Check its permissions"
    if isinstance(error, UnicodeDecodeError):
        return "it is not UTF-8 text"
    return str(error).rstrip(".") or type(error).__name__


def _parser(base: tuple[str, str] | None) -> Callable[[], MarkdownIt]:
    """GFM-like Markdown that shows raw HTML as text, images as alt text, and maps links."""

    def links(state: StateCore) -> None:
        for tok in state.tokens:
            if tok.type != "inline" or not tok.children:
                continue
            out: list[Token] = []
            dropped = False
            for c in tok.children:
                if c.type == "image":
                    alt = c.content or "image"
                    out += [Token("em_open", "em", 1), Token("text", "", 0, content=alt)]
                    out.append(Token("em_close", "em", -1))
                    continue
                if c.type == "link_open":
                    href = resolve(str(c.attrs.get("href", "")), base)
                    if href is None:
                        dropped = True
                        continue
                    c.attrs["href"] = href
                elif c.type == "link_close" and dropped:
                    dropped = False
                    continue
                out.append(c)
            tok.children = out

    def make() -> MarkdownIt:
        md = MarkdownIt("gfm-like").disable(["html_block", "html_inline"])
        md.core.ruler.push("atlas_links", links)
        return md

    return make


# Raw view: Markdown syntax in the palette's text levels. Links take the accent.

_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
_HEAD = re.compile(r"( {0,3}#{1,6})(\s.*)?")
_HR = re.compile(r" {0,3}([-*_])( *\1){2,} *")
_QUOTE = re.compile(r" {0,3}(?:> ?)+")
_ITEM = re.compile(r"\s*(?:[-*+]|\d{1,9}[.)])\s+(?:\[[ xX]\]\s)?")
_KEY = re.compile(r"([A-Za-z_][\w-]*)(:)", re.A)
_INLINE = re.compile(
    r"(?P<tick>`+)(?P<code>.+?)(?P=tick)"
    r"|(?P<lb>\[)(?P<label>[^\]]+)(?P<url>\]\([^)]*\))"
    r"|(?P<em>\*\*|__)(?P<strong>\S(?:.*?\S)?)(?P=em)"
    r"|(?P<auto><https?://[^>\s]+>)"
)


def _inline(text: str, at: int, spans: list[Span]) -> None:
    for m in _INLINE.finditer(text):
        s = at + m.start()
        if m["tick"]:
            n = len(m["tick"])
            spans += [Span(s, s + n, FAINT), Span(s + n, at + m.end() - n, TEXT)]
            spans.append(Span(at + m.end() - n, at + m.end(), FAINT))
        elif m["lb"]:
            spans += [Span(s, s + 1, FAINT), Span(at + m.start("label"), at + m.end("label"), LINK)]
            spans.append(Span(at + m.start("url"), at + m.end(), FAINT))
        elif m["em"]:
            spans += [Span(s, s + 2, FAINT), Span(s + 2, at + m.end() - 2, f"bold {TEXT}")]
            spans.append(Span(at + m.end() - 2, at + m.end(), FAINT))
        else:
            spans.append(Span(s, at + m.end(), LINK))


def highlight(lines: list[str]) -> list[Content]:
    """One Content per line of the raw file."""
    out: list[Content] = []
    front = bool(lines) and lines[0] == "---" and "---" in lines[1:]
    fence = ""
    for i, line in enumerate(lines):
        spans: list[Span] = []
        if front:
            if i and line.rstrip() == "---":
                front = False
                spans.append(Span(0, len(line), FAINT))
            elif i == 0:
                spans.append(Span(0, len(line), FAINT))
            elif m := _KEY.match(line):
                spans += [Span(0, m.end(1), TEXT), Span(m.start(2), m.end(2), FAINT)]
        elif fence:
            m = _FENCE.match(line)
            if (
                m
                and m[1][0] == fence[0]
                and len(m[1]) >= len(fence)
                and not line[m.end() :].strip()
            ):
                fence = ""
                spans.append(Span(0, len(line), FAINT))
            else:
                spans.append(Span(0, len(line), TEXT))
        elif m := _FENCE.match(line):
            fence = m[1]
            spans.append(Span(0, len(line), FAINT))
        elif m := _HEAD.fullmatch(line):
            spans += [Span(0, m.end(1), FAINT), Span(m.end(1), len(line), f"bold {TEXT}")]
        elif _HR.fullmatch(line):
            spans.append(Span(0, len(line), FAINT))
        else:
            start = 0
            if m := (_QUOTE.match(line) or _ITEM.match(line)):
                start = m.end()
                spans.append(Span(0, start, FAINT))
            if line.lstrip().startswith("|"):
                spans += [Span(k, k + 1, FAINT) for k, ch in enumerate(line) if ch == "|"]
            _inline(line[start:], start, spans)
        out.append(Content(line, spans))
    return out


class RawView(Widget):
    """The file as it is on disk, with line numbers. Long lines wrap under their own text."""

    DEFAULT_CSS = """
    RawView { width: 1fr; height: auto; color: $atlas-muted; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._lines: list[Content] = []
        self._rows: list[tuple[int, Content]] = []
        self._width = -1

    def set_text(self, text: str) -> None:
        lines = text.expandtabs(4).replace("\r\n", "\n").split("\n")
        if len(lines) > 1 and lines[-1] == "":
            lines.pop()
        self._lines = highlight(lines)
        self._width = -1
        self.refresh(layout=True)

    @property
    def digits(self) -> int:
        return len(str(len(self._lines)))

    def rows(self, width: int) -> list[tuple[int, Content]]:
        """(line number, or 0 under a wrapped line; the text) for each row at this width."""
        if width != self._width:
            room = max(8, width - self.digits - 2)
            self._rows = []
            for n, line in enumerate(self._lines, 1):
                parts = line.wrap(room) or [Content("")]
                self._rows.append((n, parts[0]))
                self._rows += [(0, p) for p in parts[1:]]
            self._width = width
        return self._rows

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return len(self.rows(width))

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        rows = self.rows(width)
        base = self.visual_style
        if y >= len(rows):
            return Strip.blank(width, base.rich_style)
        n, text = rows[y]
        number = f"{n:>{self.digits}}" if n else " " * self.digits
        line = Content.assemble((number, FAINT), "  ", text)
        strip = Strip(line.render_segments(base), line.cell_length)
        return strip.extend_cell_length(width, base.rich_style)


class Outline(ScrollView, can_focus=True):
    """The h2 and h3 headings. The cursor follows the scroll until the outline has focus."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j,down", "move(1)", "Next section", show=False),
        Binding("k,up", "move(-1)", "Previous section", show=False),
        Binding("g,home", "move(-1000000)", "First section", show=False),
        Binding("G,shift+g,end", "move(1000000)", "Last section", show=False),
        Binding("enter", "jump", "Go to the section", show=False),
    ]
    DEFAULT_CSS = """
    Outline {
        width: 28; height: 1fr; padding: 1 1 1 0;
        background: $atlas-surface-1; color: $atlas-muted;
        border-right: solid $atlas-border;
    }
    """
    TOP = 2

    class Jump(Message):
        """Scroll to section `index`; keyboard=False when a click asked."""

        def __init__(self, index: int, keyboard: bool) -> None:
            super().__init__()
            self.index = index
            self.keyboard = keyboard

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.entries: list[tuple[int, str]] = []
        self.cursor = 0
        self.hover = -1

    def set_entries(self, entries: list[tuple[int, str]]) -> None:
        self.entries = entries
        self.cursor = 0
        self.virtual_size = Size(0, len(entries) + self.TOP)
        self.refresh()

    def follow(self, index: int) -> None:
        if self.has_focus or index == self.cursor:
            return
        self.cursor = index
        self._show_cursor()

    def _show_cursor(self) -> None:
        self.scroll_to_region(self._row(self.cursor), animate=False, immediate=True)
        self.refresh()

    def _row(self, index: int) -> Region:
        return Region(0, index + self.TOP, 1, 1)

    def _index(self, event: events.MouseEvent) -> int:
        offset = event.get_content_offset(self)
        if offset is None:
            return -1
        i = offset.y + round(self.scroll_y) - self.TOP
        return i if 0 <= i < len(self.entries) else -1

    def render_line(self, y: int) -> Strip:
        width = self.scrollable_content_region.width
        y += round(self.scroll_y)
        base = self.visual_style
        i = y - self.TOP
        if y == 0:
            line = Content.assemble("  ", ("On this page".upper(), MUTED))
        elif 0 <= i < len(self.entries):
            level, text = self.entries[i]
            focused = self.has_focus and i == self.cursor
            lit = i in (self.cursor, self.hover)
            indent = 2 if level == 3 else 0
            label = Content.styled(text, TEXT if lit else MUTED)
            label = label.truncate(max(1, width - 2 - indent), ellipsis=True)
            line = Content.assemble(("▌" if focused else " ", TEXT), " " * (1 + indent), label)
            line = line.extend_right(width - line.cell_length)
            if focused or lit:
                line = line.stylize(f"on {'$atlas-selection' if focused else '$atlas-surface-2'}")
        else:
            return Strip.blank(width, base.rich_style)
        strip = Strip(line.render_segments(base), line.cell_length)
        return strip.extend_cell_length(width, base.rich_style)

    def action_move(self, step: int) -> None:
        if self.entries:
            self.cursor = max(0, min(len(self.entries) - 1, self.cursor + step))
            self._show_cursor()

    def action_jump(self) -> None:
        if self.entries:
            self.post_message(self.Jump(self.cursor, keyboard=True))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        i = self._index(event)
        if i != self.hover:
            self.hover = i
            text = self.entries[i][1] if i >= 0 else ""
            self.tooltip = text if len(text) > self.scrollable_content_region.width - 4 else None
            self.refresh()

    def on_leave(self, event: events.Leave) -> None:
        self.hover = -1
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        i = self._index(event)
        if i >= 0:
            self.cursor = i
            self.refresh()
            self.post_message(self.Jump(i, keyboard=False))

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()


class ModeSwitch(Widget):
    """r, then Formatted | Markdown. Click a side to show it, or the r to switch."""

    KEY = "r "
    LABELS = (" Formatted ", " Markdown ")
    DEFAULT_CSS = """
    ModeSwitch {
        width: 23; height: 1; margin-right: 2; background: $atlas-surface-1; color: $atlas-muted;
    }
    """
    raw = reactive(False)
    hover = reactive(-1)

    def on_mount(self) -> None:
        self.tooltip = "Show formatted text or Markdown (r)"

    def render(self) -> Content:
        parts = [(self.KEY, LINK)]
        for i, label in enumerate(self.LABELS):
            if (i == 1) == self.raw:
                parts.append((label, f"{TEXT} on $atlas-surface-3"))
            else:
                look = (
                    f"{TEXT} on $atlas-surface-2" if i == self.hover else f"{MUTED} on $background"
                )
                parts.append((label, look))
        return Content.assemble(*parts)

    def _side(self, x: int) -> int:
        """0 or 1 for a label; -1 for the key."""
        x -= len(self.KEY)
        return -1 if x < 0 else 0 if x < len(self.LABELS[0]) else 1

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self.hover = self._side(event.x)

    def on_leave(self, event: events.Leave) -> None:
        self.hover = -1

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        side = self._side(event.x)
        if side < 0 or (side == 1) != self.raw:
            await self.screen.run_action("raw")


class FrontMatter(Widget):
    """The frontmatter as a key-value table, as the web shows it."""

    DEFAULT_CSS = """
    FrontMatter {
        layout: grid; grid-size: 2; grid-columns: auto 1fr; grid-rows: auto; grid-gutter: 0 2;
        height: auto; padding: 1 2; margin-bottom: 1; background: $atlas-surface-2;
    }
    FrontMatter > .key { width: auto; color: $atlas-faint; }
    FrontMatter > .value { color: $atlas-muted; }
    """

    async def set_pairs(self, pairs: list[tuple[str, str]]) -> None:
        await self.remove_children()
        cells = [
            Static(Content(text), classes=kind)
            for key, value in pairs
            for kind, text in (("key", key), ("value", value))
        ]
        await self.mount_all(cells)
        self.display = bool(pairs)


class _Fence(MarkdownFence):
    @classmethod
    def highlight(cls, code: str, language: str, ansi: bool = False, dark: bool = False) -> Content:
        return Content(code)


class ReaderDoc(Markdown):
    """Textual's Markdown with the web's plain code blocks and one-cell bullets."""

    BULLETS = ["• ", "◦ ", "▪ ", "◦ ", "▪ "]  # noqa: RUF012
    BLOCKS = {**Markdown.BLOCKS, "fence": _Fence, "code_block": _Fence}  # noqa: RUF012


class ReaderPage(VerticalScroll, inherit_bindings=False):
    """The scrolling body. The screen binds its keys, so none of them animate."""


def _bindings() -> list[BindingType]:
    shared = keys.actions("reader")
    local = [
        Binding("j,down", "down", "Scroll down", show=False),
        Binding("k,up", "up", "Scroll up", show=False),
        Binding("space,pagedown", "page_down", "Page down", show=False),
        Binding("b,pageup", "page_up", "Page up", show=False),
        Binding("g,home", "top", "Go to the top", show=False),
        Binding("G,shift+g,end", "end", "Go to the end", show=False),
        Binding("t", "outline", "Show or hide the outline", show=False),
        Binding("y", "copy", "Copy the Markdown", show=False),
        Binding("o", "github", "Open the file on GitHub", show=False),
        Binding("R,shift+r", "reveal", "Show the folder", show=False),
        Binding("q", "close", "Close", show=False),
    ]
    return [*keys.bindings("reader"), *(b for b in local if b.action not in shared)]


class ReaderScreen(AtlasModal[None]):
    """A full-screen SKILL.md reader."""

    BINDINGS: ClassVar[list[BindingType]] = _bindings()
    DEFAULT_CSS = """
    ReaderScreen { align: left top; background: $atlas-surface-1; }
    ReaderScreen > Vertical { width: 1fr; height: 1fr; background: $atlas-surface-1; }
    #head { height: 3; padding: 0 1; border-bottom: solid $atlas-border; }
    #badge { width: 3; height: 1; margin-right: 1; text-style: bold; content-align: center middle; }
    #title { width: 1fr; height: 2; }
    #title > Horizontal { height: 1; }
    #outline-hint.-on { background: $atlas-surface-3; }
    #name, #where { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    #where { color: $atlas-muted; }
    #body { height: 1fr; }
    #page, Outline {
        scrollbar-size-vertical: 1; scrollbar-size-horizontal: 0;
        scrollbar-background: $atlas-surface-1; scrollbar-background-hover: $atlas-surface-1;
        scrollbar-background-active: $atlas-surface-1; scrollbar-corner-color: $atlas-surface-1;
        scrollbar-color: $atlas-border-strong; scrollbar-color-hover: $atlas-muted;
        scrollbar-color-active: $atlas-text;
    }
    #page { width: 1fr; height: 1fr; align: center top; background: $atlas-surface-1; }
    #note { display: none; width: 1fr; height: auto; padding: 0 2; }
    #note { background: $atlas-warn-tint; color: $atlas-warn; }
    #note.-error { background: $atlas-danger-tint; color: $atlas-danger; }
    #column { width: 1fr; max-width: 80; height: auto; padding: 1 2 2 2; }
    #column.-raw { max-width: 88; }
    #state { display: none; height: auto; color: $atlas-muted; }
    #state.-loading { text-wrap: nowrap; text-overflow: clip; }
    #doc { padding: 0; color: $atlas-muted; }
    #doc MarkdownH1 {
        content-align: left top; color: $atlas-text; background: $atlas-surface-1;
        text-style: bold; margin: 0 0 1 0;
    }
    #doc MarkdownH2 {
        color: $atlas-text; background: $atlas-surface-1; text-style: bold;
        margin: 2 0 1 0; border-bottom: solid $atlas-border;
    }
    ReaderScreen.-short #doc MarkdownH2 { margin: 1 0 0 0; }
    #doc MarkdownH3, #doc MarkdownH4 {
        color: $atlas-text; background: $atlas-surface-1; text-style: bold; margin: 1 0 0 0;
    }
    #doc MarkdownH5, #doc MarkdownH6 {
        color: $atlas-muted; background: $atlas-surface-1; text-style: bold; margin: 1 0 0 0;
    }
    #doc MarkdownBlock > .code_inline { background: $atlas-surface-2; color: $atlas-text; }
    #doc MarkdownBlock > .strong { color: $atlas-text; text-style: bold; }
    #doc MarkdownFence { background: $background; color: $atlas-muted; margin: 0 0 1 0; }
    #doc MarkdownFence > Label { padding: 1 2; }
    #doc MarkdownBullet { color: $atlas-faint; }
    #doc MarkdownOrderedList MarkdownBullet { color: $atlas-muted; }
    #doc MarkdownBlockQuote {
        background: $atlas-surface-1; border-left: solid $atlas-border-strong;
        padding: 0 0 0 1; margin: 0 0 1 0;
    }
    #doc MarkdownHorizontalRule { border-bottom: solid $atlas-border; }
    #doc MarkdownTable { background: $atlas-surface-1; }
    #doc MarkdownTableContent { keyline: none; grid-gutter: 0 0; }
    #doc MarkdownTableContent > .header, #doc MarkdownTableContent > .cell {
        border-bottom: solid $atlas-border;
    }
    #doc MarkdownTableContent > .header {
        background: $atlas-surface-2; color: $atlas-text; text-style: bold;
    }
    """

    def __init__(self, target: Target) -> None:
        super().__init__()
        self.target = target
        self.text = ""
        self.loaded = False
        self.raw = False
        self.toc: list[tuple[int, str, str | None]] = []
        self._outline: bool | None = None
        self._shown = 0.0
        self._landed = (-1, -1)  # (section, scroll y) after a jump, until the page moves

    def compose(self) -> ComposeResult:
        t = self.target
        with Vertical():
            with Horizontal(id="head"):
                yield Static(Content(views.monogram(t.label).upper()), id="badge")
                with Vertical(id="title"):
                    with Horizontal():
                        yield Static(
                            Content.assemble(("/", FAINT), (t.name, f"bold {TEXT}")), id="name"
                        )
                        yield ModeSwitch(id="mode")
                        yield CloseCell(id="close")
                    with Horizontal():
                        yield Static(Content(t.where), id="where")
                        for key, label, action, tip, name in HINTS:
                            yield HintButton(
                                key, label, action, focusable=False, tooltip=tip, id=name
                            )
            with Horizontal(id="body"):
                yield Outline(id="outline")
                with ReaderPage(id="page"):
                    yield Static(id="note")
                    with Vertical(id="column"):
                        yield Static(id="state")
                        yield FrontMatter(id="front")
                        yield ReaderDoc(id="doc", parser_factory=_parser(t.base), open_links=False)
                        yield RawView(id="raw")

    def on_mount(self) -> None:
        app = app_of(self)
        self.raw = app.state.reader_raw
        self.query_one("#where", Static).tooltip = self.target.where
        self.query_one(FrontMatter).display = False
        self._paint_badge()
        self.watch(self.app, "theme", self._paint_badge, init=False)
        self.watch(self.query_one(ReaderPage), "scroll_y", self._follow, init=False)
        self.query_one(ReaderPage).focus()
        self._layout()
        self.load()

    def on_resize(self, event: events.Resize) -> None:
        self._layout()

    def _paint_badge(self) -> None:
        bg, fg = theme.identity(self.target.hue, self.app.current_theme.dark)
        badge = self.query_one("#badge")
        badge.styles.color, badge.styles.background = fg, bg

    # Loading

    @work(exclusive=True, group="reader")
    async def load(self) -> None:
        app, t = app_of(self), self.target
        timer = self.set_timer(SKELETON_AFTER, self._skeleton)
        note, error = "", False
        try:
            if t.preview is not None:
                text, note = t.preview, READ_ONLY
            elif t.repo:
                text = await app.fetch(app.atlas.available_text, t.repo, t.file)
            else:
                text = await app.fetch(app.atlas.skill_text, t.path)
        except Exception as e:
            text, note, error = "", f"Could not load the file: {reason(e)}.", True
        timer.stop()
        if self._shown:
            await asyncio.sleep(max(0.0, self._shown + SKELETON_KEEP - time.monotonic()))
        await self._fill(text, note, error)

    def _skeleton(self) -> None:
        if self.loaded:
            return
        self._shown = time.monotonic()
        bars = (0, 34, 58, 52, 61, 40, 0, 22, 0, 55, 60, 47, 30)
        lines = [Content.styled("Loading…", MUTED)] + [
            Content.styled(" " * w, "on $atlas-surface-2") for w in bars
        ]
        state = self.query_one("#state", Static)
        state.update(Content("\n").join(lines))
        state.set_classes("-loading")
        state.display = True

    async def _fill(self, text: str, note: str, error: bool) -> None:
        self.text, self.loaded = text, True
        self._note(note, error)
        state = self.query_one("#state", Static)
        state.set_classes("")
        state.display = not text.strip() and not error
        state.update(
            Content.assemble(
                ("This SKILL.md is empty", f"bold {TEXT}"),
                "\n\nAdd frontmatter with a name and a description, then the steps for the agent.",
            )
        )
        pairs, body = split_front(text)
        await self.query_one(FrontMatter).set_pairs(pairs)
        doc = self.query_one(ReaderDoc)
        await doc.update(body)
        self.toc = [entry for entry in doc.table_of_contents if entry[0] in (2, 3)]
        self.query_one(Outline).set_entries([(level, text) for level, text, _ in self.toc])
        self.query_one(RawView).set_text(text)
        self._layout()

    def _note(self, text: str, error: bool) -> None:
        note = self.query_one("#note", Static)
        note.update(Content(f"✗ {text}" if error else text))
        note.set_class(error, "-error")
        note.display = bool(text)

    # Layout

    @property
    def has_outline(self) -> bool:
        return self.loaded and not self.raw and len(self.toc) > 2

    def _layout(self) -> None:
        t = self.target
        self.set_class(self.size.height < SHORT, "-short")
        show = self.has_outline and (
            self._outline if self._outline is not None else self.size.width >= OUTLINE_FROM
        )
        self.query_one(Outline).display = show
        hint = self.query_one("#outline-hint", HintButton)
        hint.display = self.has_outline
        hint.set_class(show, "-on")
        self.query_one("#copy").disabled = not self.text
        self.query_one("#github").display = bool(t.github)
        self.query_one("#reveal").display = bool(t.path) and t.preview is None and not ssh()
        self.query_one(ModeSwitch).raw = self.raw
        self.query_one("#column").set_class(self.raw, "-raw")
        self.query_one(FrontMatter).display = not self.raw and bool(split_front(self.text)[0])
        self.query_one(ReaderDoc).display = not self.raw
        self.query_one(RawView).display = self.raw and self.loaded and bool(self.text)

    def _top(self, widget: Widget) -> int:
        page, y = self.query_one(ReaderPage), 0
        for node in (widget, *widget.ancestors):
            if node is page or not isinstance(node, Widget):
                break
            y += node.virtual_region.y
        return y

    def _heads(self) -> list[Widget]:
        doc = self.query_one(ReaderDoc)
        return [doc.get_child_by_id(block_id) for _, _, block_id in self.toc if block_id]

    def _follow(self) -> None:
        if not self.query_one(Outline).display:
            return
        page = self.query_one(ReaderPage)
        index, y = self._landed
        if round(page.scroll_y) == y:
            self.query_one(Outline).follow(index)
            return
        self._landed = (-1, -1)
        line = page.scroll_y + (
            page.scrollable_content_region.height if page.is_vertical_scroll_end else 1
        )
        tops = [self._top(h) for h in self._heads()]
        current = max((i for i, top in enumerate(tops) if top <= line), default=0)
        self.query_one(Outline).follow(current)

    def _jump_to(self, widget: Widget) -> int:
        page = self.query_one(ReaderPage)
        y = min(max(0, self._top(widget) - 1), page.max_scroll_y)
        page.scroll_to(y=y, animate=False)
        return y

    @on(Outline.Jump)
    def _jump(self, event: Outline.Jump) -> None:
        self._landed = (event.index, self._jump_to(self._heads()[event.index]))
        if not event.keyboard:
            self.query_one(ReaderPage).focus()

    @on(Markdown.LinkClicked)
    async def _link(self, event: Markdown.LinkClicked) -> None:
        event.stop()
        if event.href.startswith("#"):
            doc = self.query_one(ReaderDoc)
            want = slug(event.href[1:])
            for _, text, block_id in doc.table_of_contents:
                if block_id and slug(text) == want:
                    self._jump_to(doc.get_child_by_id(block_id))
                    return
        else:
            await self._job("open_github", event.href)

    # Actions

    def action_down(self) -> None:
        self.query_one(ReaderPage).scroll_relative(y=1, animate=False)

    def action_up(self) -> None:
        self.query_one(ReaderPage).scroll_relative(y=-1, animate=False)

    def action_page_down(self) -> None:
        self.query_one(ReaderPage).scroll_page_down(animate=False)

    def action_page_up(self) -> None:
        self.query_one(ReaderPage).scroll_page_up(animate=False)

    def action_top(self) -> None:
        self.query_one(ReaderPage).scroll_home(animate=False)

    def action_end(self) -> None:
        self.query_one(ReaderPage).scroll_end(animate=False)

    def action_raw(self) -> None:
        self.raw = not self.raw
        app_of(self).set_state(reader_raw=self.raw)
        self._layout()
        page = self.query_one(ReaderPage)
        page.scroll_home(animate=False)
        page.focus()

    def action_outline(self) -> None:
        if not self.has_outline:
            return
        outline = self.query_one(Outline)
        self._outline = not outline.display
        self._layout()
        (outline if self._outline else self.query_one(ReaderPage)).focus()

    async def action_copy(self) -> None:
        if self.text:
            await self._job("copy", self.text, "the Markdown")

    async def action_github(self) -> None:
        if self.target.github:
            await self._job("open_github", self.target.github)

    async def action_reveal(self) -> None:
        if self.query_one("#reveal").display:
            await self._job("reveal", self.target.path)

    async def _job(self, name: str, *args: Any) -> None:
        jobs = importlib.import_module(f"{__name__.rsplit('.', 2)[0]}.jobs")
        result = getattr(jobs, name)(self.app, *args)
        if inspect.isawaitable(result):
            await result


def ssh() -> bool:
    return bool(os.environ.get("SSH_TTY"))
