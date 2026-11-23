"""What the detail panel shows for a skill, a group, or an available skill, as specs.

Rules come from core.views; this module only lays them out with the web page's words.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from rich.style import Style
from rich.text import Text

from ...core import views
from .. import theme
from . import charts
from .detail_parts import (
    Act,
    BarsEl,
    BoxEl,
    DefEl,
    El,
    HeatEl,
    Hint,
    HintsEl,
    RowEl,
    SkelEl,
    SparkEl,
    SwitchEl,
    TextEl,
    TitleEl,
    wrap_text,
)

if TYPE_CHECKING:
    from ...core.api import AtlasAPI
    from ..state import AtlasData

SEC_RULES = {
    "remote-exec": "Runs downloaded code",
    "decode-exec": "Decodes and runs data",
    "secrets": "Reads secrets",
    "env-leak": "Sends the environment out",
    "tools": "Broad tool access",
    "injection": "Prompt injection",
    "hidden-comment": "Hidden instructions",
    "invisible": "Invisible characters",
    "blob": "Encoded blob",
    "escapes": "Escaped text",
    "code": "Scripts",
    "network": "Network hosts",
}
LEVELS = {"high": ("✗ high", "atlas-danger"), "medium": ("! medium", "atlas-warn")}
DESC_LINES, DESC_LINES_SHORT = 6, 3
DESC_W = 64  # DetailText.desc max-width 68 less its padding
SEC_HOLD = 2
# Sections open until the user folds them; the rest start folded, as on the web.
OPEN = frozenset({"skill.lb", "skill.use", "group.use", "group.facts"})
# Open by default in a short window too (design §11).
ALWAYS = frozenset({"skill.lb"})
# Dark and light (lightness, chroma) of the source badge: the web's --id-bg and --id-fg.


@dataclass
class Load:
    """A lazy read. state: "wait" (hold the space), "skeleton", "ok", or "error"."""

    state: str
    value: Any = None
    error: str = ""


@dataclass
class Ctx:
    """What the builders read. `load` starts a lazy read; `job` gives a name's job state."""

    ins: views.Insights
    data: AtlasData
    atlas: AtlasAPI
    harness: str
    colors: dict[str, str]
    dark: bool
    width: int
    short: bool
    folded: frozenset[str]
    load: Callable[..., Load]
    job: Callable[[str], str | None]
    job_error: Callable[[str], str]
    desc_open: bool = False
    confirm: str | None = None
    sec_flip: frozenset[str] = frozenset()
    ssh: bool = False

    def style(self, token: str, bold: bool = False) -> Style:
        color = self.colors.get(token)
        return Style(color=color or None, bold=bold or None)

    def t(self, text: str, token: str = "atlas-text", bold: bool = False) -> Text:
        return Text(text, self.style(token, bold), end="")

    @property
    def writable(self) -> bool:
        return self.ins.writable

    def is_open(self, key: str) -> bool:
        if key in self.folded:
            return False
        if "+" + key in self.folded:
            return True
        if self.short and key not in ALWAYS:
            return False
        return key in OPEN

    def repo_info(self, repo: str | None) -> Load:
        if not repo:
            return Load("ok", {})
        got = self.load(f"repo:{repo}", self.atlas.repos, [repo])
        if got.state == "ok":
            return Load("ok", (got.value or {}).get(repo) or {})
        return got


# --------------------------------------------------------------------------
# small pieces
# --------------------------------------------------------------------------


def _join(ctx: Ctx, parts: Iterable[Text | str]) -> Text:
    out = Text(end="")
    for part in parts:
        if not part:
            continue
        if out:
            out.append(" · ", ctx.style("atlas-faint"))
        out.append_text(ctx.t(part, "atlas-muted") if isinstance(part, str) else part)
    return out


def _muted(ctx: Ctx, text: str, cls: str = "") -> TextEl:
    return TextEl(ctx.t(text, "atlas-muted"), cls)


def _error(ctx: Ctx, text: str) -> TextEl:
    return TextEl(Text.assemble(ctx.t("✗ ", "atlas-danger"), ctx.t(text)))


def _hold(lines: int = 1) -> TextEl:
    """Blank lines that hold the place of text that has not loaded yet."""
    return TextEl(Text("\n".join(" " for _ in range(lines)), end=""))


def _today(ins: views.Insights) -> date:
    now = ins.now
    return now.astimezone().date() if now.tzinfo else now.date()


def badge(ctx: Ctx, label: str, hue: int) -> Text:
    """The source's one-letter badge in its hue, as the web's avatar."""
    bg, fg = theme.identity(hue, ctx.dark)
    letter = views.monogram(label).upper()
    return Text(f" {letter} ", Style(color=fg, bgcolor=bg, bold=True), end="")


def section(
    ctx: Ctx,
    key: str,
    label: str,
    summary: str,
    body: Callable[[], list[El]],
    cue: dict[str, str] | None = None,
) -> BoxEl:
    """A folding section: `▾ LABEL`. Folded, it shows the summary, or the cue in its tone."""
    is_open = ctx.is_open(key)
    left = Text.assemble(
        ctx.t("▾ " if is_open else "▸ ", "atlas-muted"), ctx.t(label.upper(), "atlas-muted")
    )
    right = Text(end="")
    if not is_open and cue:
        danger = cue["tone"] == "danger"
        glyph = "✗" if danger else "!"
        right = ctx.t(f"{glyph} {cue['text']}", "atlas-danger" if danger else "atlas-warn")
    elif not is_open and summary:
        right = ctx.t(summary, "atlas-faint")
    tip = f"{'Fold' if is_open else 'Show'} {label.split(' · ')[0].lower()}"
    head = RowEl(f"h:{key}", left, right, Act("fold", (key,)), tip=tip, keep="left", cls="head")
    items = tuple(body()) if is_open else ()
    cls = "section -open" if is_open else "section"
    return BoxEl(f"s:{key}", (head, BoxEl(f"b:{key}", items, "body")), cls)


def tiles(ctx: Ctx, stats: list[tuple[str, str, str]]) -> TextEl:
    """Stat tiles: a value over a muted label. Up to 3 columns, each as wide as its widest
    tile, 3 cells apart; a blank line between rows."""

    def widths(per: int) -> list[int]:
        return [max(max(len(v), len(lb)) for v, lb, _ in stats[c::per]) for c in range(per)]

    per = next(
        (n for n in range(min(3, len(stats)), 0, -1) if sum(widths(n)) + 3 * (n - 1) <= ctx.width),
        1,
    )
    cols = widths(per)
    lines: list[Text] = []
    for i in range(0, len(stats), per):
        row = stats[i : i + per]
        top, bottom = Text(end=""), Text(end="")
        for j, (value, label, token) in enumerate(row):
            pad = 0 if j == len(row) - 1 else cols[j] + 3
            top.append_text(ctx.t(value.ljust(pad), token))
            bottom.append_text(ctx.t(label.ljust(pad), "atlas-muted"))
        lines += [Text(end=""), top, bottom] if lines else [top, bottom]
    return TextEl(Text("\n", end="").join(lines))


def _after_fold(blocks: list[BoxEl]) -> list[BoxEl]:
    """Mark an open section that follows a folded one, so a blank row stays above it."""
    out: list[BoxEl] = []
    for b in blocks:
        prev = out[-1].cls.split() if out else []
        mine = b.cls.split()
        if "-open" in mine and "section" in prev and "-open" not in prev:
            b = replace(b, cls=f"{b.cls} -after-fold")
        out.append(b)
    return out


def clamp_lines(ctx: Ctx, text: Text, lines: int) -> tuple[Text, bool]:
    """The text wrapped as the panel wraps it, cut to `lines` lines that end in `…`."""
    width = min(ctx.width, DESC_W)
    wrapped = wrap_text(text, width)
    if len(wrapped) <= lines:
        return text, False
    last = wrapped[lines - 1]
    if last.cell_len >= width:
        last = last[: width - 1]
    while last.plain and last.plain[-1] in " ,.;:":
        last.right_crop(1)
    last.append("…")
    return Text("\n", end="").join([*wrapped[: lines - 1], last]), True


def _snap_time(at: str) -> str:
    try:
        dt = datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return str(at) or "an unknown time"
    hour = dt.strftime("%I").lstrip("0")
    return f"{dt:%b} {dt.day}, {dt.year}, {hour}:{dt:%M} {dt:%p}"


def _pct(score: float) -> int:
    return math.floor(score * 100 + 0.5)


def _problems(s: dict) -> list[dict]:
    raw = s.get("problems") or []
    return [p if isinstance(p, dict) else {"message": str(p), "level": "warn"} for p in raw]


def _home(ctx: Ctx) -> str:
    return str(ctx.ins.scan.get("home") or "")


def _tilde(ctx: Ctx, path: str) -> str:
    return views.tilde(path, _home(ctx))


def _harness_label(h: dict, hid: str) -> str:
    return str(h.get("label") or h.get("name") or hid)


# --------------------------------------------------------------------------
# a skill
# --------------------------------------------------------------------------


def skill_blocks(ctx: Ctx, s: dict) -> list[BoxEl]:
    return _after_fold(_skill_blocks(ctx, s))


def _skill_blocks(ctx: Ctx, s: dict) -> list[BoxEl]:
    blocks: list[BoxEl | None] = [
        _head(ctx, s),
        _who(ctx, s),
        _desc(ctx, s),
        _acts(ctx, s),
        _problem_card(ctx, s),
        _cards(ctx, s),
        _loaded_by(ctx, s) if s.get("scope") == "personal" else None,
        _overlap(ctx, s),
        _usage(ctx, s),
        _security(ctx, s),
        _details(ctx, s),
        _history(ctx, s),
        _danger(ctx, s),
    ]
    return [b for b in blocks if b is not None]


def _crumb(ctx: Ctx, s: dict) -> RowEl:
    ins = ctx.ins
    label = views.group_label(ins, s)
    info = ctx.repo_info(views.repo_of(s))
    stars = (info.value or {}).get("stars") if info.state == "ok" else None
    left = Text.assemble(badge(ctx, label, views.hue_of(ins, s)), " ", ctx.t(label, "atlas-muted"))
    right = ctx.t(f"★ {views.short(stars)}", "atlas-muted") if stars else None
    gid = views.group_key(ins, s)
    return RowEl("crumb", left, right, Act("group", (gid,)), tip="Show this collection")


def _title(ctx: Ctx, name: str, switch: SwitchEl | None = None) -> TitleEl:
    text = Text.assemble(ctx.t("/", "atlas-faint"), ctx.t(name, bold=True))
    return TitleEl(text, switch)


def _panel_switch(ctx: Ctx, s: dict) -> SwitchEl | None:
    st = views.switch_state(ctx.ins, ctx.harness, s)
    stale = s.get("status") == "stale"
    if not ctx.writable or not st["toggle"] or stale:
        return None
    tip = f"Plugin {s.get('plugin')}" if st["toggle"] == "plugin" else s["name"]
    act = Act("switch", (ctx.harness, st["toggle"], st["key"]))
    return SwitchEl("switch", act, st["on"], tip=tip)


def _head(ctx: Ctx, s: dict) -> BoxEl:
    ins = ctx.ins
    path = _tilde(ctx, s["path"])
    items: list[El] = [
        _crumb(ctx, s),
        _title(ctx, s.get("invoke") or s["name"], _panel_switch(ctx, s)),
        TextEl(ctx.t(path, "atlas-muted"), "path", cut="start", tip=path),
    ]
    probs = _problems(s)
    error = bool(probs) and views.worst(probs) == "error"
    issues = views.plural(len(probs), "issue")
    meta: list[Text | str] = []
    if views.is_outdated(ins, s):
        meta.append(charts.tag("update", ctx.colors))
    if s.get("local_edits"):
        meta.append(charts.tag("edited", ctx.colors))
    if error:
        meta.append(charts.tag("error", ctx.colors, label=issues))
    if (s.get("security") or {}).get("level") == "high":
        meta.append(charts.tag("risk", ctx.colors))
    if probs and not error:
        meta.append(charts.tag("issues", ctx.colors, label=issues))
    if s.get("scope") == "plugin" and s.get("status") != "stale":
        ref = s.get("plugin_ref")
        n = sum(1 for x in ins.skills if x.get("plugin_ref") == ref and x.get("status") != "stale")
        meta.append(
            f"The switch turns all {views.plural(n, 'skill')} in {s.get('plugin')} on or off"
        )
    same = views.dupes(ins, s)
    if same:
        meta.append(f"Same as {', '.join(same)}")
    if meta:
        items.append(TextEl(_join(ctx, meta), "meta"))
    return BoxEl("head", tuple(items), "head")


def _who(ctx: Ctx, s: dict) -> BoxEl:
    you = not s.get("claude_only")
    agent = not s.get("manual_only")
    invoke = s.get("invoke") or s["name"]
    you_t = ctx.t(
        f"Type /{invoke}" if you else "Not in the / menu", "atlas-text" if you else "atlas-muted"
    )
    agent_t = ctx.t(
        "Loads it when it fits" if agent else "Never on its own",
        "atlas-text" if agent else "atlas-muted",
    )
    if ctx.short:
        return BoxEl("who", (_muted(ctx, f"{you_t.plain} · {agent_t.plain}", "who"),))
    return BoxEl("who", (DefEl((("You", you_t), ("Agent", agent_t))),))


def _description(ctx: Ctx, key: str, text: str) -> BoxEl:
    """A muted description clamped by lines, with Show more."""
    lines = DESC_LINES_SHORT if ctx.short else DESC_LINES
    full = ctx.t(text, "atlas-muted")
    shown, long = clamp_lines(ctx, full, lines)
    items: list[El] = [TextEl(full if ctx.desc_open else shown, "desc")]
    if long:
        label = "Show less" if ctx.desc_open else "Show more"
        items.append(HintsEl("more", (Hint(label, Act("more_desc"), key="shift+m"),)))
    return BoxEl(key, tuple(items))


def _desc(ctx: Ctx, s: dict) -> BoxEl:
    desc = str(s.get("description") or "")
    if not desc:
        return BoxEl("desc", (_muted(ctx, "No description", "desc"),))
    return _description(ctx, "desc", desc)


def github_url(s: dict) -> str:
    """The web's GitHub link: the marketplace or source URL, when it is a web URL."""
    ms = s.get("marketplace_source") or {}
    o = s.get("origin") or {}
    src = str(ms.get("url") or ms.get("repo") or o.get("sourceUrl") or o.get("source") or "")
    return src.removesuffix(".git") if src.startswith(("http://", "https://")) else ""


def _acts(ctx: Ctx, s: dict) -> BoxEl:
    path = s["path"]
    invoke = f"/{s.get('invoke') or s['name']}"
    shown = invoke if len(invoke) <= 20 else invoke[:19] + "…"
    hints = [
        Hint("Read", Act("read", (path,)), key="v", tip="Read the SKILL.md"),
        Hint(f"Copy {shown}", Act("copy", (invoke, invoke)), tip=f"Copy {invoke}"),
    ]
    url = github_url(s)
    if url:
        hints.append(Hint("GitHub ↗", Act("github", (url,)), key="o", tip=url))
    if ctx.writable and not ctx.ssh:
        tip = "Show the folder in the file manager"
        hints.append(Hint("Reveal", Act("reveal", (path,)), key="shift+r", tip=tip))
    hints.append(Hint("⋯", Act("more", (path,)), tone="plain", tip="More actions · ctrl+k"))
    return BoxEl("acts", (HintsEl("acts", tuple(hints)),), "acts")


def _problem_card(ctx: Ctx, s: dict) -> BoxEl | None:
    probs = _problems(s)
    if not probs:
        return None
    error = views.worst(probs) == "error"
    n = len(probs)
    rows: list[tuple[str | Text, Text]] = []
    for p in probs:
        bad = p.get("level") == "error"
        level = ctx.t("✗ Error" if bad else "! Warning", "atlas-danger" if bad else "atlas-warn")
        rows.append((level, ctx.t(str(p.get("message") or ""))))
        if p.get("hint"):
            rows.append(("", ctx.t(str(p["hint"]), "atlas-muted")))
        if str(p.get("path") or "").startswith("/"):
            rows.append(("", ctx.t(_tilde(ctx, p["path"]), "atlas-muted")))
    title = TextEl(ctx.t("1 problem to fix" if n == 1 else f"{n} problems to fix", bold=True))
    items: list[El] = [title, DefEl(tuple(rows), label_w=10)]
    card = BoxEl("c-prob", tuple(items), f"card {'-danger' if error else '-warn'}")
    return BoxEl("prob", (card,), "cards")


def _card(key: str, title: Text, body: list[El], cls: str = "card") -> BoxEl:
    return BoxEl(key, (TextEl(title), *body), cls)


def _update_hint(ctx: Ctx, name: str, outdated: bool, verbs: tuple[str, str]) -> Hint | None:
    js = ctx.job(name)
    ing, ed = verbs
    if js in views.RUNNING:
        return Hint("Queued" if js == "queued" else f"{ing}…", tone="busy")
    if js == "done":
        return Hint(f"✓ {ed}", tone="done")
    if js == "failed":
        tip = ctx.job_error(name)
        return Hint("Retry", Act("update", (name,)), key="u", tone="danger", tip=tip)
    if not outdated:
        return None
    if ctx.confirm == name:
        return Hint("Replace my edits", Act("update", (name,)), key="u", tone="warn")
    return Hint("Update", Act("update", (name,)), key="u", tone="primary")


def _diff_line(ctx: Ctx, name: str) -> El:
    got = ctx.load(f"diff:{name}", ctx.atlas.diff, name)
    if got.state == "wait":
        return _hold()
    if got.state == "skeleton":
        return SkelEl((0.5,))
    if got.state == "error":
        return _muted(ctx, f"Could not get the changes: {got.error}.")
    files = (got.value or {}).get("files") or []
    if not files:
        return _muted(ctx, "The files are the same. Only the version record is different.")
    return TextEl(
        Text.assemble(
            ctx.t(f"{views.plural(len(files), 'file')} changed", "atlas-muted"),
            "  ",
            ctx.t(f"+{got.value.get('added', 0)}", "atlas-add"),
            " ",
            ctx.t(f"−{got.value.get('removed', 0)}", "atlas-del"),
        )
    )


def _snapshots(ctx: Ctx, name: str) -> Load:
    got = ctx.load(f"hist:{name}", ctx.atlas.history, name)
    if got.state == "ok":
        return Load("ok", (got.value or {}).get("snapshots") or [])
    return got


def _update_card(ctx: Ctx, s: dict, name: str) -> BoxEl:
    source = (s.get("origin") or {}).get("source") or ""
    js = ctx.job(name)
    body: list[El] = [_muted(ctx, f"A newer version is on {source}.")]
    if js == "failed":
        why = ctx.job_error(name)
        body.append(
            TextEl(ctx.t(f"✗ The update failed{': ' + why if why else ''}.", "atlas-danger"))
        )
    elif not js:
        body.append(_diff_line(ctx, name))
    if s.get("local_edits"):
        note = "± You changed this skill after install. Updating replaces your changes."
        body.append(TextEl(ctx.t(note, "atlas-warn")))
    hints: list[Hint] = []
    if ctx.writable and not js:
        hints.append(
            Hint("See changes", Act("diff", (name,)), key="d", tip="What the update changes")
        )
    slot = _update_hint(ctx, name, views.is_outdated(ctx.ins, s), ("Updating", "Updated"))
    if slot is not None:
        hints.append(slot)
    if hints:
        body.append(HintsEl(f"upd:{name}", tuple(hints)))
    return _card("c-upd", ctx.t("Update available", bold=True), body, "card -accent")


def _cards(ctx: Ctx, s: dict) -> BoxEl | None:
    cards: list[El] = []
    scope, stale = s.get("scope"), s.get("status") == "stale"
    if scope == "personal":
        name = views.lock_name(s)
        if not s.get("store"):
            where = _tilde(ctx, s.get("source_root") or "")
            store = _tilde(ctx, ctx.ins.scan.get("store") or "~/.agents")
            text = (
                f"It lives in {where}, outside {store}/skills,"
                " so update, link, and delete do not apply."
            )
            cards.append(
                _card("c-copy", ctx.t("A copy for one harness", bold=True), [_muted(ctx, text)])
            )
        elif not name and ctx.writable:
            link = HintsEl(
                "link", (Hint("Link to GitHub…", Act("link", (s["dir_name"],)), key="l"),)
            )
            body: list[El] = [_muted(ctx, "Link it to get update checks."), link]
            cards.append(_card("c-link", ctx.t("Not linked to a repo", bold=True), body))
        elif name and (views.is_outdated(ctx.ins, s) or ctx.job(name)):
            cards.append(_update_card(ctx, s, name))
        elif s.get("local_edits"):
            note = "± You changed this skill after install. An update would replace your changes."
            cards.append(TextEl(ctx.t(note, "atlas-warn"), "note"))
    elif scope == "plugin" and not stale:
        pass
    elif stale:
        text = "Claude Code no longer loads this copy."
        cards.append(_card("c-old", ctx.t("Old version", bold=True), [_muted(ctx, text)]))
    else:
        text = f"Loads only when you work inside {s.get('project')}."
        cards.append(_card("c-prj", ctx.t("Project skill", bold=True), [_muted(ctx, text)]))
    return BoxEl("cards", tuple(cards), "cards") if cards else None


def _loaded_by(ctx: Ctx, s: dict) -> BoxEl:
    hs = ctx.ins.scan.get("harnesses") or {}
    rows: list[El] = []
    on = 0
    for hid in s.get("harnesses") or []:
        h = hs.get(hid)
        if not h:
            continue
        st = views.switch_state(ctx.ins, hid, s)
        on += st["on"]
        label = _harness_label(h, hid)
        act = Act("switch", (hid, st["toggle"] or "skill", st["key"] or s["name"]))
        live = bool(h.get("switch")) and ctx.writable
        rows.append(
            SwitchEl(
                f"lb:{hid}",
                act,
                st["on"],
                label=label,
                tip=f"{s['name']} in {label}",
                current=hid == ctx.harness,
                disabled=not live,
            )
        )
    summary = f"On in {on} of {len(rows)}" if rows else "No harness"

    def body() -> list[El]:
        return rows or [_muted(ctx, "No harness loads this folder.")]

    return section(ctx, "skill.lb", "Loaded by", summary, body)


def _newer(c: dict) -> str:
    newer = str(c.get("newer") or "")
    return {"other": "That copy is newer", "this": "This copy is newer"}.get(newer, "Same date")


def _overlap(ctx: Ctx, s: dict) -> BoxEl | None:
    sim = views.similar_of(ctx.ins, ctx.harness, s)
    copies = s.get("copies") or []
    if not sim and not copies:
        return None
    parts = [
        views.plural(len(sim), "similar skill") if sim else "",
        f"{len(copies)} diverged" if copies else "",
    ]
    summary = " · ".join(p for p in parts if p)
    cue = None
    if copies:
        n = len(copies)
        cue = {"tone": "warn", "text": "1 diverged copy" if n == 1 else f"{n} diverged copies"}

    def similar() -> list[El]:
        rows: list[El] = []
        for x in sim:
            other = x["skill"]
            score = x.get("score") or 0
            meter = charts.meter(score, 10, ctx.colors)
            right = Text.assemble(meter, " ", ctx.t(f"{_pct(score):>3}%", "atlas-muted"))
            name = Text.assemble(
                ctx.t("/", "atlas-faint"), ctx.t(other.get("invoke") or other["name"])
            )
            tip = f"Open /{other['name']} · {_tilde(ctx, x['path'])}"
            act = Act("select", (other["path"],))
            rows.append(RowEl(f"sim:{x['path']}", name, right, act, tip))
        note = "The descriptions overlap, so the agent may load the wrong one."
        return [
            TextEl(ctx.t("Similar skills"), "sub"),
            _muted(ctx, note),
            BoxEl("sim", tuple(rows)),
        ]

    def copied() -> list[El]:
        rows: list[El] = []
        for c in copies:
            why = "Other files differ too" if c.get("trees_differ") else "Only SKILL.md differs"
            sub = ctx.t(f"{_newer(c)} · {why}", "atlas-muted")
            where = ctx.t(_tilde(ctx, c.get("dir") or c["path"]))
            if ctx.writable:
                act = Act("compare", (s["path"], c["path"]))
                tip = "Compare the two SKILL.md files"
                rows.append(
                    RowEl(f"cpy:{c['path']}", where, ctx.t("Compare"), act, tip, sub, cut="start")
                )
            else:
                rows.append(RowEl(f"cpy:{c['path']}", where, sub=sub, cut="start"))
        note = "Other folders have a skill with this name and a different SKILL.md."
        out: list[El] = [
            TextEl(ctx.t("Copies"), "sub"),
            _muted(ctx, note),
            BoxEl("cpy", tuple(rows)),
        ]
        if not ctx.writable:
            out.append(_muted(ctx, "Run ./atlas to compare the files."))
        return out

    def body() -> list[El]:
        return (similar() if sim else []) + (copied() if copies else [])

    return section(ctx, "skill.ovl", "Overlap", summary, body, cue)


def _usage_cue(ctx: Ctx) -> dict[str, str] | None:
    u = ctx.data.usage or {}
    if ctx.data.errors.get("usage") or u.get("status") == "error" or u.get("error"):
        return {"tone": "warn", "text": "Could not read usage"}
    return None


def _wait(ctx: Ctx) -> list[El]:
    """The usage index is not ready: why, or how far it has read."""
    u = ctx.data.usage or {}
    err = ctx.data.errors.get("usage") or u.get("error")
    if err or u.get("status") == "error":
        return [_error(ctx, f"Could not read usage: {err or 'the session index failed'}.")]
    done, total = [*(u.get("progress") or []), 0, 0][:2]
    line = ctx.t(f"Reading your agent sessions… {done:,} of {total:,}", "atlas-muted")
    track = charts.progress(done / total if total else 0, min(24, ctx.width), ctx.colors)
    return [TextEl(line), TextEl(track)]


def _use_stats(ctx: Ctx, count: int, last: float, days: int) -> TextEl:
    when = views.ago(last, ctx.ins.now) if last else "never"
    return tiles(
        ctx,
        [
            (f"{count:,}", "uses", "atlas-text"),
            (when, "last used", "atlas-text"),
            (f"{days:,}", "active days", "atlas-text"),
        ],
    )


def _weeks(ctx: Ctx) -> int:
    """How many weeks the usage chart shows at this width."""
    if ctx.short:
        return min(views.WEEKS, ctx.width)
    return charts.heat_grid(ctx.width, views.WEEKS)[2]


def _calendar(ctx: Ctx, days: dict[str, int]) -> list[El]:
    """The heatmap; a short window gets a sparkline and its summary instead."""
    today = _today(ctx.ins)
    if ctx.short:
        n = _weeks(ctx)
        weeks = views.weekly(days, n, ctx.ins.now)
        summary = views.heatmap(days, ctx.ins.now)["summary"]
        return [SparkEl(charts.spark(weeks, n, ctx.colors, today=today)), _muted(ctx, summary)]
    return [HeatEl(tuple(sorted(days.items())), today, "in saved sessions")]


def _projects(ctx: Ctx, projects: dict[str, int]) -> El | None:
    top = sorted(projects.items(), key=lambda kv: -kv[1])[:4]
    if not top:
        return None
    most = top[0][1] or 1
    num_w = max(len(f"{n:,}") for _, n in top)
    name_w = min(max(len(p) for p, _ in top), max(8, ctx.width * 2 // 5))
    bar_w = max(4, min(16, ctx.width - name_w - num_w - 4))
    lines = []
    for name, n in top:
        cut = name if len(name) <= name_w else name[: name_w - 1] + "…"
        lines.append(
            Text.assemble(
                ctx.t(cut.ljust(name_w)),
                "  ",
                charts.meter(n / most, bar_w, ctx.colors, track=False),
                "  ",
                ctx.t(f"{n:,}".rjust(num_w), "atlas-muted"),
            )
        )
    return TextEl(Text("\n", end="").join(lines), "projects")


def _usage(ctx: Ctx, s: dict) -> BoxEl | None:
    ins = ctx.ins
    if not ctx.writable or s.get("scope") == "project" or s.get("status") == "stale":
        return None
    u = views.use_of(ins, s)
    ready = views.use_ready(ins)
    count = u["count"] if u else 0
    summary = views.uses_text(count) if count else "No uses yet"
    if not ready and not u:
        summary = "Reading sessions…"

    def body() -> list[El]:
        if not ready and not u:
            return _wait(ctx)
        if not u or not count:
            note = "No recorded uses yet."
            on = views.switch_state(ins, ctx.harness, s)["on"]
            if s.get("scope") == "personal" and on:
                note += (
                    " Every skill that is on costs a little context in each session,"
                    " so turn off the ones you never use."
                )
            return [_muted(ctx, note)]
        out: list[El] = [_use_stats(ctx, count, u["last"], len(u["days"]))]
        out += _calendar(ctx, u["days"]) if ready else _wait(ctx)
        if ready and u["counted"] > u["seen"]:
            note = (
                f"Claude Code counted {views.plural(u['counted'], 'use')} in all."
                " Old sessions get deleted, so the calendar shows fewer."
            )
            out.append(_muted(ctx, note))
        proj = _projects(ctx, u.get("projects") or {})
        if proj is not None:
            out.append(proj)
        return out

    label = f"Usage · {_weeks(ctx)} weeks"
    return section(ctx, "skill.use", label, summary, body, _usage_cue(ctx))


def _finding_groups(report: dict) -> list[tuple[str, str, list[dict]]]:
    out: dict[tuple[str, str], list[dict]] = {}
    for f in report.get("findings") or []:
        out.setdefault((f.get("rule", ""), f.get("level", "info")), []).append(f)
    return [(rule, level, items) for (rule, level), items in out.items()]


def _security_body(ctx: Ctx, s: dict) -> list[El]:
    note = _muted(ctx, views.SEC_NOTE, "note")
    sec = s.get("security") or {}
    counts = sec.get("counts") or {}
    if not ctx.writable:
        if sec.get("level", "none") == "none":
            line = "No risky patterns found."
        else:
            bits = [f"{counts.get(k)} {k}" for k in ("high", "medium", "info") if counts.get(k)]
            line = " · ".join(bits) + ". Run ./atlas to see each finding."
        return [_muted(ctx, line), note]
    path = s["path"]
    got = ctx.load(f"sec:{path}", ctx.atlas.security, path)
    if got.state == "wait":
        return [_hold(), _hold(SEC_HOLD), note]
    if got.state == "skeleton":
        return [_muted(ctx, "Scanning the files…"), SkelEl((0.7, 0.45)), note]
    if got.state == "error":
        retry = HintsEl("sec-retry", (Hint("Try again", Act("retry", (f"sec:{path}",))),))
        return [_error(ctx, f"Could not scan this skill: {got.error}."), retry, note]
    rep = got.value or {}
    if not rep.get("findings"):
        files = views.plural(rep.get("files") or 0, "file")
        return [TextEl(ctx.t(f"✓ No risky patterns in {files}.", "atlas-on")), note]
    out: list[El] = []
    for rule, level, items in _finding_groups(rep):
        key = f"{path}:{rule}:{level}"
        is_open = (level != "info") != (key in ctx.sec_flip)
        word, token = LEVELS.get(level, (level, "atlas-muted"))
        left = Text.assemble(
            ctx.t("▾ " if is_open else "▸ ", "atlas-muted"),
            ctx.t(word.ljust(9), token),
            ctx.t(SEC_RULES.get(rule, rule)),
        )
        right = ctx.t(str(len(items)), "atlas-muted")
        tip = f"{'Fold' if is_open else 'Show'} the findings"
        out.append(RowEl(f"sg:{rule}:{level}", left, right, Act("secfold", (key,)), tip))
        if not is_open:
            continue
        msg = (
            "Hosts named in the scripts. The skill can call them when it runs."
            if rule == "network"
            else str(items[0].get("message") or "")
        )
        found: list[El] = [_muted(ctx, msg)]
        for f in items:
            found.append(TextEl(ctx.t(f"{f.get('file')}:{f.get('line')}", "atlas-muted")))
            if f.get("excerpt"):
                found.append(TextEl(ctx.t(str(f["excerpt"])), "code"))
        out.append(BoxEl(f"sf:{rule}:{level}", tuple(found), "finding"))
    if rep.get("truncated"):
        out.append(_muted(ctx, f"{views.plural(rep['truncated'], 'more finding')} not shown."))
    if rep.get("skipped"):
        out.append(_muted(ctx, f"{views.plural(rep['skipped'], 'file')} over 1 MB not scanned."))
    out.append(note)
    return out


def _security(ctx: Ctx, s: dict) -> BoxEl:
    sec = s.get("security") or {}
    c = sec.get("counts") or {}
    if sec.get("level", "none") == "none":
        summary = "No risks found"
    else:
        parts = [
            views.plural(c["medium"], "medium finding") if c.get("medium") else "",
            f"{c['info']} info" if c.get("info") else "",
        ]
        summary = " · ".join(p for p in parts if p)
    high = c.get("high") or 0
    cue = {"tone": "danger", "text": views.plural(high, "high finding")} if high else None
    return section(ctx, "skill.sec", "Security", summary, lambda: _security_body(ctx, s), cue)


def _setting(ctx: Ctx, s: dict) -> str:
    h = (ctx.ins.scan.get("harnesses") or {}).get(ctx.harness) or {}
    sw = h.get("switch")
    scope = s.get("scope")
    if sw == "claude":
        if scope == "personal":
            mode = views.switch_state(ctx.ins, ctx.harness, s)["mode"]
            return f"skillOverrides.{s['name']}" + ("" if mode == "on" else f' = "{mode}"')
        if scope == "plugin":
            return f'enabledPlugins["{s.get("plugin_ref")}"]'
        return ""
    return _tilde(ctx, h.get("config") or "") if sw and scope == "personal" else ""


def _facts(
    ctx: Ctx, rows: list[tuple[str, Any]], cut: tuple[str, ...] = ("Path", "Folder")
) -> DefEl:
    out: list[tuple[str | Text, Text]] = []
    for label, value in rows:
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        if value in (None, ""):
            continue
        out.append((label, value if isinstance(value, Text) else ctx.t(str(value))))
    return DefEl(tuple(out), cut=cut)


def _details(ctx: Ctx, s: dict) -> BoxEl:
    o = s.get("origin") or {}
    ver = s.get("plugin_version") or s.get("version") or ""
    listed, used = s.get("tokens_listed") or 0, s.get("tokens_body") or 0
    summary = " · ".join(
        p for p in (f"v{ver}" if ver else "", f"{views.approx(listed)} tokens") if p
    )
    updated = str(s.get("last_updated") or o.get("updatedAt") or s.get("modified") or "")[:10]
    size = f"{(s.get('words') or 0):,} words · {views.plural(s.get('file_count') or 0, 'file')}"
    cost = f"{views.approx(listed)} tokens listed, {views.approx(used)} when used"
    rows = [
        ("Version", ver),
        ("License", s.get("license")),
        ("Updated", updated),
        ("Tools", s.get("allowed_tools")),
        ("Arguments", s.get("argument_hint")),
        ("Model", s.get("model")),
        ("Invocation", s.get("invocation")),
        ("Size", size),
        ("Context cost", cost),
        ("Setting", _setting(ctx, s)),
        ("Path", _tilde(ctx, s["path"])),
    ]
    return section(ctx, "skill.facts", "Details", summary, lambda: [_facts(ctx, rows)])


def _history(ctx: Ctx, s: dict) -> BoxEl | None:
    name = views.lock_name(s)
    if not ctx.writable or not name:
        return None
    snaps = _snapshots(ctx, name)
    summary, cue = "Reading…", None
    if snaps.state == "ok":
        summary = views.plural(len(snaps.value), "snapshot") if snaps.value else "No snapshots"
    elif snaps.state == "error":
        cue = {"tone": "warn", "text": "Could not read history"}

    def body() -> list[El]:
        if snaps.state == "wait":
            return [_hold()]
        if snaps.state == "skeleton":
            return [SkelEl((0.6, 0.4))]
        if snaps.state == "error":
            retry = HintsEl("hist-retry", (Hint("Try again", Act("retry", (f"hist:{name}",))),))
            return [_error(ctx, f"Could not read the history: {snaps.error}."), retry]
        if not snaps.value:
            text = (
                "No saved versions yet."
                " Before each update, the atlas saves a copy of this skill here."
            )
            return [_muted(ctx, text)]
        rows: list[El] = []
        for x in snaps.value:
            reason = "Before a restore" if x.get("reason") == "restore" else "Before an update"
            sub = ctx.t(reason + (f" · {x['hash']}" if x.get("hash") else ""), "atlas-muted")
            act = Act("history", (name,))
            tip = "Open the history to restore this version"
            when = ctx.t(_snap_time(x.get("at") or ""))
            rows.append(RowEl(f"snap:{x.get('id')}", when, ctx.t("Restore…"), act, tip, sub))
        return rows

    return section(ctx, "skill.hist", "History", summary, body, cue)


def _danger(
    ctx: Ctx, s: dict, *, names: list[str] | None = None, label: str = "Delete…"
) -> BoxEl | None:
    if names is None:
        if not (ctx.writable and s.get("scope") == "personal" and s.get("store")):
            return None
        names = [s["dir_name"]]
        note = "Moves the folder to the Trash and removes its lock entry. You can undo it."
    else:
        note = "Moves every folder in this collection to the Trash. You can undo it."
    hint = Hint(label, Act("delete", tuple(names)), key="delete", tone="danger", tip="Asks first")
    return BoxEl("danger", (HintsEl("delete", (hint,)), _muted(ctx, note, "note")), "danger")


# --------------------------------------------------------------------------
# a group
# --------------------------------------------------------------------------


def group_blocks(ctx: Ctx, gid: str) -> list[BoxEl]:
    return _after_fold(_group_blocks(ctx, gid))


def _group_blocks(ctx: Ctx, gid: str) -> list[BoxEl]:
    ins = ctx.ins
    g = views.group_for(ins, gid)
    members = views.members_of(ins, ctx.harness, gid)
    kind = g["type"]
    repo = g.get("repo")
    info = ctx.repo_info(repo)
    meta = (info.value or {}) if info.state == "ok" else {}
    on = sum(1 for s in members if views.switch_state(ins, ctx.harness, s)["on"])
    switch: SwitchEl | None = None
    parts: list[str] = []
    desc: str | None = ""
    acts: list[Hint] = []
    facts: list[tuple[str, Any]] = []
    danger: BoxEl | None = None
    if kind == "src":
        source = g["source"]
        local = views.is_local_group(source)
        avail = [a for a in ctx.data.available.get(source) or [] if not a.get("taken")]
        fresh = [a for a in avail if a.get("new")]
        watching = source in ((ctx.data.updates or {}).get("watched") or [])
        if members and views.switchable(ins, ctx.harness) and ctx.writable:
            mixed = 0 < on < len(members)
            tip = f"All {len(members)} skills from {source}"
            act = Act("switch_group", (ctx.harness, source))
            switch = SwitchEl("switch", act, on == len(members), tip=tip, mixed=mixed)
        stars = meta.get("stars")
        parts = [
            f"{on} of {len(members)} on",
            f"{len(avail)} available" if avail else "",
            f"★ {views.short(stars)}" if stars else "",
            "Watching" if watching else "",
        ]
        if source == views.NO_SOURCE:
            desc = "Skills with no upstream repo. Link one to get update checks."
        elif local:
            prefix = source.rstrip("*")
            desc = f"Skills that share the {prefix} name prefix. They have no linked repo yet."
        else:
            desc = meta.get("description") or ("" if info.state == "ok" else None)
        update = _group_update(ctx, members)
        if update is not None:
            acts.append(update)
        if ctx.writable and fresh:
            paths = tuple(a["path"] for a in fresh)
            acts.append(
                Hint(f"Install {len(fresh)} new", Act("install", (source, *paths)), key="shift+i")
            )
            acts.append(Hint("Dismiss new", Act("dismiss", (source,)), tip="Clear the new tags"))
        if ctx.writable and local:
            names = tuple(s["dir_name"] for s in members if s.get("store"))
            acts.append(Hint("Link to GitHub…", Act("link", names), key="l"))
        if ctx.writable and watching:
            acts.append(
                Hint(
                    "Stop watching",
                    Act("unwatch", (source,)),
                    tip="Stop checking it for new skills",
                )
            )
        checked = views.checked_ms(ins)
        kind_word = (
            "Local skills"
            if source == views.NO_SOURCE
            else "Name prefix"
            if local
            else "GitHub repo"
        )
        folder = members[0]["dir"].rsplit("/", 1)[0] if members else ""
        facts = [
            ("Kind", kind_word),
            ("Repo", repo),
            ("Checked", views.ago(checked, ins.now) if repo and checked else ""),
            ("Folder", _tilde(ctx, folder) if folder else ""),
        ]
        stored = [s["dir_name"] for s in members if s.get("store")]
        if ctx.writable and stored:
            danger = _danger(
                ctx, {}, names=stored, label=f"Delete {views.plural(len(stored), 'skill')}…"
            )
    elif kind == "plg":
        lv = members[0] if members else None
        if lv is not None and ctx.writable:
            st = views.switch_state(ins, ctx.harness, lv)
            if st["toggle"] == "plugin":
                act = Act("switch", (ctx.harness, "plugin", st["key"]))
                switch = SwitchEl("switch", act, st["on"], tip=f"Plugin {g['label']}")
        version = (lv or {}).get("plugin_version") or ""
        version = "" if version == "unknown" else version
        market = (lv or {}).get("marketplace") or ""
        parts = [
            "Plugin",
            market,
            f"v{version}" if version else "",
            views.plural(len(members), "skill"),
        ]
        about = meta.get("description")
        desc = f"From {market}: {about}" if about else "A plugin turns on or off as one unit."
        facts = [
            ("Marketplace", market),
            ("Version", version),
            ("Installed", str((lv or {}).get("installed_at") or "")[:10]),
            ("Updated", str((lv or {}).get("last_updated") or "")[:10]),
            ("Setting", f'enabledPlugins["{g["ref"]}"]'),
        ]
    else:
        parts = ["Project", views.plural(len(members), "skill")]
        desc = f"These skills load only when you work inside {g['project']}."
        folder = (members[0].get("project_path") or "") if members else ""
        facts = [("Folder", _tilde(ctx, folder) if folder else "")]
    if repo:
        url = f"https://github.com/{repo}"
        acts.append(Hint("GitHub ↗", Act("github", (url,)), key="o", tip=url))
    acts.append(Hint("⋯", Act("more", (gid,)), tone="plain", tip="More actions · ctrl+k"))

    title = Text.assemble(
        badge(ctx, g["label"], views.hue_of(ins, g)), " ", ctx.t(g["label"], bold=True)
    )
    head: list[El] = [TitleEl(title, switch), TextEl(_join(ctx, [p for p in parts if p]), "meta")]
    blocks: list[BoxEl | None] = [BoxEl("head", tuple(head), "head")]
    if desc is None and info.state == "error":
        blocks.append(
            BoxEl("desc", (_muted(ctx, f"Could not get the description: {info.error}."),))
        )
    elif desc is None:
        held: El = SkelEl((0.95, 0.9, 0.5)) if info.state == "skeleton" else _hold(3)
        blocks.append(BoxEl("desc", (held,)))
    elif desc:
        blocks.append(_description(ctx, "desc", desc))
    blocks.append(BoxEl("acts", (HintsEl("acts", tuple(acts)),), "acts"))
    blocks.append(_group_stats(ctx, members))
    blocks.append(_group_usage(ctx, members))
    blocks.append(section(ctx, "group.facts", "Details", "", lambda: [_facts(ctx, facts)]))
    blocks.append(danger)
    return [b for b in blocks if b is not None]


def _group_update(ctx: Ctx, members: list[dict]) -> Hint | None:
    out = [s for s in members if views.is_outdated(ctx.ins, s)]
    if not out or not ctx.writable:
        return None
    names = [views.lock_name(s) or s["name"] for s in out]
    if any(ctx.job(n) in views.RUNNING for n in names):
        return Hint("Updating…", tone="busy")
    return Hint(f"Update {len(out)}", Act("update", tuple(names)), key="u", tone="primary")


def _group_stats(ctx: Ctx, members: list[dict]) -> BoxEl:
    st = views.group_stats(ctx.ins, ctx.harness, members)

    def n(key: str) -> int:
        return int(st.get(key) or 0)

    unused = st.get("unused")
    stats = [
        (str(n("on")), "on", "atlas-on" if n("on") else "atlas-text"),
        (str(n("off")), "off", "atlas-text"),
        (str(n("updates")), "updates", "atlas-accent" if n("updates") else "atlas-text"),
        (str(n("edited")), "edited", "atlas-warn" if n("edited") else "atlas-text"),
        (str(n("you_only")), "you only", "atlas-text"),
        (
            "–" if unused is None else str(unused),
            "unused",
            "atlas-faint" if unused is None else "atlas-text",
        ),
    ]
    return BoxEl("stats", (tiles(ctx, stats),), "stats")


def _group_usage(ctx: Ctx, members: list[dict]) -> BoxEl | None:
    ins = ctx.ins
    if not ctx.writable:
        return None
    ready = views.use_ready(ins)
    total = sum(views.uses(ins, s) for s in members)
    summary = (
        "Reading sessions…" if not ready else views.uses_text(total) if total else "No uses yet"
    )

    def body() -> list[El]:
        if not ready:
            return _wait(ctx)
        if not total:
            return [_muted(ctx, "No recorded uses for these skills yet.")]
        days = views.sum_days(ins, members)
        last = max(views.last_used(ins, s) for s in members)
        out: list[El] = [_use_stats(ctx, total, last, len(days)), *_calendar(ctx, days)]
        top = views.top_used(ins, members, 5)
        if top:
            plugin = members[0].get("scope") == "plugin"
            rows = tuple(
                (
                    f"/{s['name'] if plugin else s.get('invoke') or s['name']}",
                    float(views.uses(ins, s)),
                )
                for s in top
            )
            acts = tuple(Act("select", (s["path"],)) for s in top)
            out.append(BarsEl("top", rows, acts))
        return out

    label = f"Usage · {_weeks(ctx)} weeks"
    return section(ctx, "group.use", label, summary, body, _usage_cue(ctx))


# --------------------------------------------------------------------------
# an available skill
# --------------------------------------------------------------------------


def parse_avail(key: str) -> tuple[str, str]:
    """`a:<repo>:<path>` to (repo, path)."""
    repo, _, path = key[2:].partition(":")
    return repo, path


def avail_blocks(ctx: Ctx, key: str) -> list[BoxEl]:
    repo, path = parse_avail(key)
    offered = ctx.data.available.get(repo) or []
    a = next((x for x in offered if x.get("path") == path), None)
    if a is None:
        return []
    item = {"kind": "avail", "repo": repo, "path": path, "name": a["name"]}
    descs = ctx.load(f"avail:{repo}", ctx.atlas.available, repo, [x["path"] for x in offered])
    crumb = _crumb(ctx, item)
    meta = _join(ctx, [charts.tag("new", ctx.colors) if a.get("new") else "", "Not installed"])
    head = BoxEl("head", (crumb, _title(ctx, a["name"]), TextEl(meta, "meta")), "head")
    if descs.state == "ok":
        info = ((descs.value or {}).get("skills") or {}).get(path) or {}
        text = info.get("description") or ""
        desc: El = _muted(ctx, text or "No description", "desc")
    elif descs.state == "error":
        desc = _muted(ctx, "Description unavailable.", "desc")
    elif descs.state == "skeleton":
        desc = SkelEl((0.95, 0.8, 0.5))
    else:
        desc = _hold(3)
    folder = path.removesuffix("SKILL.md").rstrip("/")
    url = f"https://github.com/{repo}/tree/HEAD/{folder}"
    hints = (
        Hint("Read", Act("read", ()), key="v", tip="Read the SKILL.md from GitHub"),
        Hint("GitHub ↗", Act("github", (url,)), tip=url),
    )
    taken = a.get("taken")
    if taken == "moved":
        why = "You have this skill under its old folder. Update or relink it instead."
    elif taken:
        why = (
            f"A skill named {a['name']} is already installed, so this one cannot go in next to it."
        )
    else:
        why = f"Installs into ~/.agents/skills/{a['name']} and tracks {repo} for updates."
    body: list[El] = [_muted(ctx, why)]
    if not taken and ctx.writable:
        js = ctx.job(a["name"])
        if js and js != "failed":
            slot = _update_hint(ctx, a["name"], True, ("Installing", "Installed"))
        else:
            label = "Retry" if js == "failed" else "Install"
            tone = "danger" if js == "failed" else "primary"
            slot = Hint(
                label,
                Act("install", (repo, path)),
                key="i",
                tone=tone,
                tip=ctx.job_error(a["name"]),
            )
        if slot is not None:
            body.append(HintsEl("install", (slot,)))
    title = ctx.t("Cannot install" if taken else "Available", bold=True)
    card = _card("c-ins", title, body, "card" if taken else "card -accent")
    return [
        head,
        BoxEl("desc", (desc,)),
        BoxEl("acts", (HintsEl("acts", hints),), "acts"),
        BoxEl("cards", (card,), "cards"),
        BoxEl("facts", (_facts(ctx, [("Source", repo), ("Path", path)]),), "facts"),
    ]
