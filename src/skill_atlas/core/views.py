"""The view rules of web/index.html as pure functions, so the TUI shows what the page shows.

Inputs are the /api/data scan, the /api/updates check, and the /api/usage snapshot, as plain dicts.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import TypedDict, TypeVar, cast

NO_SOURCE = "Local, no upstream"
UNUSED_DAYS = 90
WEEKS = 26
SPARK_WEEKS = 12
DAY_MS = 86_400_000
RUNNING = frozenset({"queued", "downloading", "installing"})
SORTS = ("name", "uses", "recent", "cost")
SEC_NOTE = "A heuristic scan of the files. It can miss real risks and flag safe code."
HUES = (250, 205, 170, 145, 105, 75, 45, 20, 350, 320, 290)
# id, label, tooltip; in the order of the web view strip.
VIEWS = (
    ("all", "All", ""),
    ("on", "On", ""),
    ("off", "Off", ""),
    ("updates", "Updates", ""),
    ("issues", "Issues", "Skills with SKILL.md problems"),
    ("new", "New", ""),
    ("unused", "Unused", "No recorded use in 90 days"),
    ("costly", "Costly", "On, costly, and not used in 90 days"),
    ("similar", "Similar", ""),
    ("diverged", "Diverged", ""),
    ("review", "Review", "Skills with high-risk patterns"),
)
_BOILER = re.compile(
    r"^(when the user (wants|asks|needs)( help)?( to| with| for)?|use (this skill )?when"
    r"( the user)?|use this when|this skill should be used when|use for)\s+",
    re.I,
)
_ISO = re.compile(r"(\d{4}-\d\d-\d\d)(?:[T ](\d\d:\d\d(?::\d\d)?)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?)?")
# CLDR root collation order of punctuation, which JS localeCompare follows.
_PUNCT = "_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"
_T = TypeVar("_T")


@dataclass
class ViewState:
    """The filter inputs: harness picker, view strip, search box, and display menu."""

    harness: str = "all"
    view: str = "all"
    query: str = ""
    group_by: str = "source"
    sort: str = "name"
    show_project: bool = False
    show_stale: bool = False

    @property
    def q(self) -> str:
        """The search text. Rows show `/name`, so a leading `/` is not part of it."""
        return self.query.strip().lstrip("/").strip()


@dataclass
class Insights:
    """The data the rules read. Settings are read live; rebuild when skills, updates, or usage
    change. `usage` None means still loading; `missing` is len(restore_plan()["install"])."""

    scan: dict
    updates: dict | None = None
    usage: dict | None = None
    now: datetime = field(default_factory=lambda: datetime.now().astimezone())
    writable: bool = True
    descs: dict = field(default_factory=dict)
    missing: int = 0
    by_path: dict[str, dict] = field(init=False, repr=False, default_factory=dict)
    _by_name: dict[str, list[dict]] = field(init=False, repr=False, default_factory=dict)
    _prefix: dict[str, str] = field(init=False, repr=False, default_factory=dict)
    _dupes: dict[str, list[str]] = field(init=False, repr=False, default_factory=dict)
    _hay: dict[str, str] = field(init=False, repr=False, default_factory=dict)
    _use: dict[str, dict] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        skills = self.skills
        self.by_path = {s["path"]: s for s in skills}
        for s in skills:
            self._by_name.setdefault(s["name"], []).append(s)
        self._prefix = _prefix_labels(skills)
        by_desc: dict[str, list[dict]] = {}
        for s in skills:
            if s.get("scope") == "personal" and s.get("description"):
                by_desc.setdefault(s["description"], []).append(s)
        for s in skills:
            names = [x["name"] for x in by_desc.get(s.get("description") or "", []) if x is not s]
            if names:
                self._dupes[s["path"]] = names
            parts = (s.get(k) for k in ("name", "invoke", "description", "plugin", "marketplace"))
            more = (s.get("project"), s.get("path"), source_of(self, s))
            self._hay[s["path"]] = " ".join(str(p) for p in (*parts, *more) if p).lower()
        self._use = _index_usage(skills, self.usage or {})

    @property
    def skills(self) -> list[dict]:
        return self.scan.get("skills") or []

    @property
    def harness_ids(self) -> list[str]:
        return list(self.scan.get("harnesses") or {})


class Switch(TypedDict):
    on: bool
    mode: str
    toggle: str
    key: str


class Tab(TypedDict):
    id: str
    label: str
    title: str
    count: int | None
    waiting: bool


class Group(TypedDict):
    id: str
    kind: str
    key: str
    label: str
    repo: str | None
    repo_url: str
    hue: int
    local: bool
    open: bool
    skills: list[dict]
    members: list[dict]
    on: int
    total: int
    checked: str
    switch: bool
    meta: str
    fresh: int
    spark: list[int] | None
    available: list[dict]
    available_total: int
    available_open: bool
    available_note: str
    installable: int
    fresh_installable: int


class Section(TypedDict):
    id: str
    title: str
    count: str
    open: bool
    groups: list[Group]
    rows: list[dict]
    group_ids: list[str]


class Item(TypedDict):
    key: str
    tone: str
    text: str
    detail: str
    action: str


class Tag(TypedDict):
    kind: str
    text: str
    title: str
    level: str


class Empty(TypedDict):
    title: str
    body: str
    actions: list[str]


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _origin(s: dict) -> dict:
    o = s.get("origin")
    return o if isinstance(o, dict) else {}


def _group_map(items: Iterable[_T], fn: Callable[[_T], str]) -> list[tuple[str, list[_T]]]:
    out: dict[str, list[_T]] = {}
    for x in items:
        out.setdefault(fn(x), []).append(x)
    return list(out.items())


def _round(x: float) -> int:
    """Math.round: halves go up."""
    return math.floor(x + 0.5)


def _to_fixed(x: float, places: int) -> str:
    return str(Decimal(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def short(n: int) -> str:
    if n >= 1000:
        return _to_fixed(n / 1000, 0 if n >= 10000 else 1) + "k"
    return str(n)


def approx(n: int) -> str:
    return "≈" + short(n)


def uses_text(n: int) -> str:
    return "1 use" if n == 1 else f"{n:,} uses"


def _weight(ch: str) -> tuple[int, int | str]:
    if ch.isspace():
        return (0, ord(ch))
    i = _PUNCT.find(ch)
    if i >= 0:
        return (1, i)
    if unicodedata.category(ch)[0] in "PS":
        return (2, ord(ch))
    if ch.isdigit():
        return (3, unicodedata.digit(ch, 0))
    if ch.isalpha():
        return (4, ch.casefold())
    return (5, ord(ch))


@lru_cache(maxsize=16384)
def collate(text: str, base: bool = False) -> tuple:
    """A sort key that follows JS localeCompare; base=True ignores case and accents."""
    primary: list[tuple[int, int | str]] = []
    accents: list[tuple[int, ...]] = []
    case: list[int] = []
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.combining(ch) and accents:
            accents[-1] += (ord(ch),)
            continue
        primary.append(_weight(ch))
        accents.append(())
        case.append(1 if ch.isupper() else 0)
    if base:
        return (tuple(primary),)
    return (tuple(primary), tuple(accents), tuple(case))


def tilde(path: str, home: str = "") -> str:
    s = str(path or "")
    if home and (s == home or s.startswith(home + "/")):
        return "~" + s[len(home) :]
    return re.sub(r"^/(Users|home)/[^/]+", "~", s)


def hue(key: str) -> int:
    """The source's hue, the same djb2 hash as the page."""
    h = 5381
    for ch in str(key):
        c = ord(ch)
        if c > 0xFFFF:
            c = 0xD800 + ((c - 0x10000) >> 10)
        h = (h * 33 + c) & 0xFFFFFFFF
    return HUES[h % len(HUES)]


def monogram(label: str) -> str:
    return re.sub(r"^[^A-Za-z0-9]+", "", str(label))[:1] or "?"


def gh_repo(v: object) -> str | None:
    m = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?/?\Z", str(v or ""), re.A)
    if m:
        return m.group(1)
    return v if isinstance(v, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", v, re.A) else None


def clean_desc(text: str | None) -> str:
    """The description without its leading boilerplate ("Use when the user…")."""
    t = _BOILER.sub("", str(text or ""), count=1)
    return t[0].upper() + t[1:] if t else ""


def search_terms(query: str) -> list[str]:
    return query.lower().split()


def _ms(ts: object) -> float | None:
    """Date.parse for ISO strings, in milliseconds; None when it does not parse."""
    m = _ISO.fullmatch(str(ts or "").strip())
    if not m:
        return None
    day, clock, frac, zone = m.groups()
    if clock is None:
        text, zone = day + "T00:00:00", "Z"
    else:
        text = f"{day}T{clock}{':00' if len(clock) == 5 else ''}"
        if frac:
            text += "." + frac[:3].ljust(6, "0")
    if zone:
        zone = "+00:00" if zone == "Z" else f"{zone[:3]}:{zone[-2:]}"
    try:
        return datetime.fromisoformat(text + (zone or "")).timestamp() * 1000
    except ValueError:
        return None


def _local_date(now: datetime) -> date:
    return now.astimezone().date() if now.tzinfo else now.date()


def _midnight(d: date) -> float:
    return datetime(d.year, d.month, d.day).timestamp() * 1000


def _now_ms(ins: Insights) -> float:
    return ins.now.timestamp() * 1000


# --------------------------------------------------------------------------
# index: prefix groups and usage
# --------------------------------------------------------------------------


def _prefix_of(name: str) -> str | None:
    return name.split("-")[0] if "-" in name else None


def _prefix_labels(skills: list[dict]) -> dict[str, str]:
    """Untracked skills that share a name prefix get a group, named by the longest shared part."""
    loose = [s for s in skills if s.get("scope") == "personal" and not _origin(s).get("source")]
    counts: dict[str, int] = {}
    for s in loose:
        p = _prefix_of(s["name"])
        if p:
            counts[p] = counts.get(p, 0) + 1
    labels: dict[str, str] = {}
    for p, n in counts.items():
        if n < 3:
            continue
        parts = [s["name"].split("-") for s in loose if _prefix_of(s["name"]) == p]
        k = 1
        while all(len(x) > k + 1 and x[k] == parts[0][k] for x in parts):
            k += 1
        labels[p] = "-".join(parts[0][:k]) + "-*"
    out = {}
    for s in loose:
        p = _prefix_of(s["name"])
        if p and p in labels:
            out[s["path"]] = labels[p]
    return out


def _use_keys(s: dict) -> list[str]:
    plugin = s.get("plugin")
    keys = [s.get("invoke"), s.get("name"), s.get("dir_name"), plugin and f"{plugin}:{s['name']}"]
    return [k for k in keys if k]


def _index_usage(skills: list[dict], d: dict) -> dict[str, dict]:
    """Usage per skill path. Names map to one skill: exact, else a unique `-name` suffix."""
    recs = [s for s in skills if s.get("status") != "stale"]
    exact: dict[str, dict] = {}
    for s in recs:
        for k in _use_keys(s):
            exact.setdefault(k, s)
    tails: dict[str, list[dict]] = {}
    for s in recs:
        name = s["name"]
        for i, ch in enumerate(name):
            if ch == "-":
                tails.setdefault(name[i + 1 :], []).append(s)
    counters = d.get("counters") or {}
    named = d.get("skills") or {}
    by: dict[str, dict] = {}
    for n in dict.fromkeys([*counters, *named]):
        rec = exact.get(n)
        if rec is None and len(tails.get(n, [])) == 1:
            rec = tails[n][0]
        if rec is None:
            continue
        u = by.setdefault(
            rec["path"], {"counted": 0, "seen": 0, "days": {}, "projects": {}, "last": 0.0}
        )
        c, t = counters.get(n), named.get(n)
        if c is not None:
            u["counted"] += c.get("count") or 0
            u["last"] = max(u["last"], _ms(c.get("last")) or 0)
        if t is not None:
            for day, k in (t.get("days") or {}).items():
                u["days"][day] = u["days"].get(day, 0) + k
                u["seen"] += k
            for pr, k in (t.get("projects") or {}).items():
                u["projects"][pr] = u["projects"].get(pr, 0) + k
            u["last"] = max(u["last"], _ms(t.get("last")) or 0)
    for u in by.values():
        u["count"] = max(u["counted"], u["seen"])
    return by


# --------------------------------------------------------------------------
# sources, harnesses, switches
# --------------------------------------------------------------------------


def source_of(ins: Insights, s: dict) -> str:
    return _origin(s).get("source") or ins._prefix.get(s.get("path", "")) or NO_SOURCE


def is_local_group(source: str) -> bool:
    return source == NO_SOURCE or source.endswith("-*")


def dupes(ins: Insights, s: dict) -> list[str]:
    """Names of personal skills with the same description."""
    return ins._dupes.get(s.get("path", ""), [])


def search_haystack(ins: Insights, s: dict) -> str:
    return ins._hay.get(s.get("path", ""), "")


def repo_of(s: dict) -> str | None:
    if s.get("kind") in ("avail", "group"):
        return s.get("repo")
    if _origin(s).get("source"):
        return _origin(s)["source"]
    if s.get("scope") != "plugin":
        return None
    ms = s.get("marketplace_source") or {}
    return gh_repo(ms.get("url")) or gh_repo(ms.get("repo"))


def group_label(ins: Insights, s: dict) -> str:
    kind, scope = s.get("kind"), s.get("scope")
    if kind == "group":
        return s["label"]
    if kind == "avail":
        return s["repo"]
    if scope == "plugin":
        return s.get("plugin", "")
    if scope == "project":
        return s.get("project", "")
    return source_of(ins, s)


def group_key(ins: Insights, s: dict) -> str:
    """The list id of the group a skill or available skill sits in: src:, plg:, or prj:."""
    if s.get("kind") == "avail":
        return f"src:{s['repo']}"
    if s.get("scope") == "plugin":
        return f"plg:{s.get('plugin_ref')}"
    if s.get("scope") == "project":
        return f"prj:{s.get('project')}"
    return f"src:{source_of(ins, s)}"


def hue_of(ins: Insights, s: dict) -> int:
    """The detail panel's hue for a skill, an available skill, or a group from group_for."""
    if s.get("kind") == "group":
        return hue(s["hue_key"])
    if s.get("kind") == "avail":
        return hue(s["repo"])
    key = group_key(ins, s)
    return hue(key[4:] if key.startswith("src:") else key)


def harness_choices(ins: Insights) -> list[str]:
    ids = ins.harness_ids
    return (["all"] if len(ids) > 1 else []) + ids


def default_harness(ins: Insights) -> str:
    return next(iter(ins.harness_ids), "all")


def loads(harness: str, s: dict) -> bool:
    hs = s.get("harnesses") or []
    return len(hs) > 0 if harness == "all" else harness in hs


def live(harness: str, s: dict) -> bool:
    return s.get("scope") == "personal" and loads(harness, s)


def switchable(ins: Insights, harness: str) -> bool:
    return bool((ins.scan.get("harnesses") or {}).get(harness, {}).get("switch"))


def reads_store(ins: Insights, harness: str) -> bool:
    """Installs land in the store, so only offer them where the harness reads it."""
    return harness == "all" or bool((ins.scan.get("harnesses") or {}).get(harness, {}).get("store"))


def switch_state(ins: Insights, harness: str, s: dict) -> Switch:
    """What the switch shows for one skill in one harness. "all" is on when any harness is on."""
    hs = ins.scan.get("harnesses") or {}
    h = hs.get(harness)
    scope, name = s.get("scope"), s.get("name", "")
    if not h:
        if scope == "project":
            return Switch(on=True, mode="project only", toggle="", key="")
        if s.get("status") == "stale":
            return Switch(on=False, mode="old version", toggle="", key="")
        on = any(switch_state(ins, i, s)["on"] for i in s.get("harnesses") or [] if i in hs)
        return Switch(on=on, mode="", toggle="", key="")
    settings = (ins.scan.get("settings") or {}).get(harness) or {}
    if h.get("switch") != "claude" and scope != "project":
        if not h.get("switch"):
            return Switch(on=True, mode="", toggle="", key="")
        off = name in (settings.get("off") or [])
        return Switch(on=not off, mode="off" if off else "on", toggle="skill", key=name)
    if scope == "personal":
        mode = (settings.get("skillOverrides") or {}).get(name) or "on"
        return Switch(on=mode != "off", mode=mode, toggle="skill", key=name)
    if scope == "plugin":
        if s.get("status") == "stale":
            return Switch(on=False, mode="old version", toggle="", key="")
        ref = s.get("plugin_ref", "")
        plugins = settings.get("enabledPlugins") or {}
        mode = "not set" if ref not in plugins else ""
        return Switch(on=plugins.get(ref) is True, mode=mode, toggle="plugin", key=ref)
    return Switch(on=True, mode="project only", toggle="", key="")


def header_meta(ins: Insights, harness: str) -> list[str]:
    """The notes beside the view strip: built-ins off, and where the switches write."""
    h = (ins.scan.get("harnesses") or {}).get(harness) or {}
    out = []
    if ins.scan.get("bundled_skills_disabled") and h.get("switch") == "claude":
        out.append("built-ins off")
    if harness == "all":
        out.append("pick a harness to switch skills")
    elif h.get("switch"):
        path = ((ins.scan.get("settings") or {}).get(harness) or {}).get("path") or ""
        out.append(f"writes {tilde(path, ins.scan.get('home', ''))}")
    else:
        out.append(f"{h.get('name') or 'agent'} has no per-skill switch")
    return out


# --------------------------------------------------------------------------
# updates and available skills
# --------------------------------------------------------------------------


def _upd(ins: Insights) -> dict:
    return ins.updates or {}


def _available(ins: Insights) -> dict[str, list[dict]]:
    return _upd(ins).get("available") or {}


def _watched(ins: Insights) -> list[str]:
    return _upd(ins).get("watched") or []


def lock_name(s: dict) -> str | None:
    """The lock key of a GitHub-tracked skill: its folder name."""
    if s.get("scope") == "personal" and _origin(s).get("skillFolderHash"):
        return s.get("dir_name")
    return None


def update_status(ins: Insights, s: dict) -> str | None:
    name = lock_name(s)
    return (_upd(ins).get("skills") or {}).get(name) if name else None


def is_outdated(ins: Insights, s: dict) -> bool:
    return update_status(ins, s) == "outdated"


def update_targets(ins: Insights, skills: list[dict]) -> tuple[list[dict], list[dict]]:
    """The outdated skills that Update all updates, and the ones it skips for local edits."""
    out = [s for s in skills if is_outdated(ins, s)]
    return [s for s in out if not s.get("local_edits")], [s for s in out if s.get("local_edits")]


def new_in(ins: Insights, repo: str) -> list[dict]:
    return [a for a in _available(ins).get(repo) or [] if a.get("new")]


def new_total(ins: Insights) -> int:
    return sum(len(new_in(ins, r)) for r in _available(ins))


def checked_ms(ins: Insights) -> float | None:
    return _ms(_upd(ins).get("checked_at"))


def avail_shown(ins: Insights, st: ViewState, repo: str) -> list[dict]:
    """Skills the repo offers that are not installed, filtered by the view and the search."""
    if not ins.writable or st.view not in ("all", "new"):
        return []
    if st.view == "all" and st.group_by != "source":
        return []
    terms = search_terms(st.query)
    info = (ins.descs.get(repo) or {}).get("skills") or {}
    out = []
    for a in _available(ins).get(repo) or []:
        if st.view == "new" and not a.get("new"):
            continue
        desc = (info.get(a.get("path")) or {}).get("description") or ""
        hay = f"{a.get('name')} {repo} {desc}".lower()
        if all(t in hay for t in terms):
            out.append(a)
    return out


def avail_open(
    ins: Insights, st: ViewState, repo: str, installed: int, collapsed: Collection[str] = ()
) -> bool:
    """Open when the repo has news or nothing installed; `av:` and `+av:` keys flip the default."""
    if st.q or st.view == "new":
        return True
    if new_in(ins, repo) or installed == 0:
        return f"av:{repo}" not in collapsed
    return f"+av:{repo}" in collapsed


# --------------------------------------------------------------------------
# usage
# --------------------------------------------------------------------------


def use_ready(ins: Insights) -> bool:
    return (ins.usage or {}).get("status") == "ready"


def use_of(ins: Insights, s: dict) -> dict | None:
    """counted, seen, count, days, projects, and last (ms) for one skill, or None."""
    return ins._use.get(s.get("path", ""))


def uses(ins: Insights, s: dict) -> int:
    u = use_of(ins, s)
    return u["count"] if u else 0


def last_used(ins: Insights, s: dict) -> float:
    u = use_of(ins, s)
    return u["last"] if u else 0.0


def is_unused(ins: Insights, s: dict) -> bool:
    if not use_ready(ins) or s.get("scope") == "project" or s.get("status") == "stale":
        return False
    return _now_ms(ins) - last_used(ins, s) > UNUSED_DAYS * DAY_MS


def sum_days(ins: Insights, skills: Iterable[dict]) -> dict[str, int]:
    days: dict[str, int] = {}
    for s in skills:
        for d, k in ((use_of(ins, s) or {}).get("days") or {}).items():
            days[d] = days.get(d, 0) + k
    return days


def weekly(days: dict[str, int], n: int, now: datetime) -> list[int]:
    """Weekly totals ending today, oldest first."""
    out = [0] * n
    today = _midnight(_local_date(now))
    for day, k in days.items():
        try:
            d = date.fromisoformat(day)
        except ValueError:
            continue
        w = n - 1 - _round((today - _midnight(d)) / DAY_MS) // 7
        if 0 <= w < n:
            out[w] += k
    return out


def spark_series(ins: Insights, s: dict, n: int = SPARK_WEEKS) -> list[int] | None:
    """Uses per week for the row's spark; None when the row shows no use cell."""
    u = use_of(ins, s)
    if not use_ready(ins) or s.get("status") == "stale" or not u or not u["count"]:
        return None
    return weekly(u["days"], n, ins.now)


def group_spark(ins: Insights, skills: Iterable[dict], n: int = SPARK_WEEKS) -> list[int] | None:
    if not use_ready(ins):
        return None
    w = weekly(sum_days(ins, skills), n, ins.now)
    return w if any(w) else None


def top_used(ins: Insights, skills: Iterable[dict], n: int = 5) -> list[dict]:
    return sorted((s for s in skills if uses(ins, s)), key=lambda s: -uses(ins, s))[:n]


def ago(ms: float, now: datetime) -> str:
    then = datetime.fromtimestamp(ms / 1000).date()
    days = math.floor((_midnight(_local_date(now)) - _midnight(then)) / DAY_MS)
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{_round(days / 7)} weeks ago"
    return f"{_round(days / 30)} months ago"


def heatmap(days: dict[str, int], now: datetime) -> dict:
    """The 26-week calendar: cells with day, n, level 0-4, week, and dow (0 is Sunday)."""
    today = _local_date(now)
    start = today - timedelta(days=(today.weekday() + 1) % 7 + (WEEKS - 1) * 7)
    counts = [
        days.get((start + timedelta(i)).isoformat(), 0) for i in range((today - start).days + 1)
    ]
    top = max(counts, default=0)

    def level(n: int) -> int:
        return max(1, min(4, math.ceil(4 * math.log1p(n) / math.log1p(top)))) if n else 0

    cells, months = [], []
    for i, n in enumerate(counts):
        d = start + timedelta(i)
        w, dow = divmod(i, 7)
        if d.day <= 7 and dow == 0 and w > 0:
            months.append({"week": w, "label": d.strftime("%b")})
        cells.append({"day": d.isoformat(), "n": n, "level": level(n), "week": w, "dow": dow})
    total, active = sum(counts), sum(1 for n in counts if n)
    summary = f"{plural(total, 'use')} on {plural(active, 'day')} in saved sessions"
    return {"cells": cells, "months": months, "total": total, "active": active, "summary": summary}


# --------------------------------------------------------------------------
# cost, security, overlap
# --------------------------------------------------------------------------


def cost_total(skills: Iterable[dict]) -> int:
    return sum(s.get("tokens_listed") or 0 for s in skills)


def listed_in(ins: Insights, harness: str) -> list[dict]:
    """Skills whose name and description the harness puts in every session, costliest first."""
    known = harness in (ins.scan.get("harnesses") or {})
    out = [
        s
        for s in ins.skills
        if s.get("status") != "stale"
        and s.get("scope") != "project"
        and (harness in (s.get("harnesses") or []) if known else bool(s.get("harnesses")))
        and switch_state(ins, harness, s)["on"]
    ]
    return sorted(out, key=lambda s: -(s.get("tokens_listed") or 0))


def costly_unused(ins: Insights, harness: str) -> set[str]:
    """Paths of skills that are on, in the top quarter by listed tokens, and unused in 90 days."""
    if not use_ready(ins):
        return set()
    on = listed_in(ins, harness)
    if not on:
        return set()
    cut = on[math.ceil(len(on) / 4) - 1].get("tokens_listed") or 0
    return {s["path"] for s in on if (s.get("tokens_listed") or 0) >= cut and is_unused(ins, s)}


def context_cost(ins: Insights, harness: str) -> dict:
    """total, count, top (5 skills), per_harness (for "all"), and the pane summary."""
    on = listed_in(ins, harness)
    total = cost_total(on)
    out = {
        "total": total,
        "count": len(on),
        "top": on[:5],
        "per_harness": [],
        "summary": f"{approx(total)} tokens" if on else "No tokens",
    }
    if harness == "all":
        hs = ins.scan.get("harnesses") or {}
        per = [(i, listed_in(ins, i)) for i in hs]
        per = sorted((p for p in per if p[1]), key=lambda p: (-cost_total(p[1]), collate(p[0])))
        out["per_harness"] = [
            {"id": i, "label": hs[i].get("label", i), "total": cost_total(lst), "count": len(lst)}
            for i, lst in per
        ]
        if per:
            out["summary"] = f"Up to {approx(cost_total(per[0][1]))} tokens"
    return out


def is_risky(s: dict) -> bool:
    return (s.get("security") or {}).get("level") == "high"


def security_counts(ins: Insights, st: ViewState) -> dict[str, int]:
    shown = [s for s in ins.skills if in_view(ins, st, s)]
    sec = [s.get("security") or {} for s in shown]
    return {
        "high": sum(1 for x in sec if x.get("level") == "high"),
        "medium": sum(1 for x in sec if x.get("level") == "medium"),
        "code": sum(1 for x in sec if x.get("code")),
    }


def similar_of(ins: Insights, harness: str, s: dict) -> list[dict]:
    """Similar skills that load in the harness, through any copy of that name; `skill` is it."""
    out = []
    for x in s.get("similar") or []:
        cands = [ins.by_path.get(x["path"]), *ins._by_name.get(x["name"], [])]
        found = next((y for y in cands if y is not None and loads(harness, y)), None)
        if found is not None:
            out.append({**x, "skill": found})
    return out


def overlap_counts(ins: Insights, harness: str, skills: Iterable[dict]) -> dict[str, int]:
    pairs, names = set(), set()
    for s in skills:
        for x in similar_of(ins, harness, s):
            pairs.add(tuple(sorted((s["name"], x["name"]))))
        if s.get("copies"):
            names.add(s["name"])
    return {"similar": len(pairs), "diverged": len(names)}


# --------------------------------------------------------------------------
# filters and counts
# --------------------------------------------------------------------------


def in_view(ins: Insights, st: ViewState, s: dict) -> bool:
    """Loaded by the harness, and not hidden by the project and old-version toggles."""
    project = s.get("scope") == "project"
    if not project and not loads(st.harness, s):
        return False
    if project and not st.show_project:
        return False
    return not (s.get("status") == "stale" and not st.show_stale)


def matches(ins: Insights, s: dict, query: str) -> bool:
    hay = search_haystack(ins, s)
    return all(t in hay for t in search_terms(query))


def visible(ins: Insights, st: ViewState, s: dict, costly: set[str] | None = None) -> bool:
    """In view, in the current view tab, and matching every search term."""
    if not in_view(ins, st, s):
        return False
    v = st.view
    if v == "new":
        return False
    if v == "updates":
        keep = is_outdated(ins, s)
    elif v == "issues":
        keep = bool(s.get("problems"))
    elif v == "unused":
        keep = s.get("scope") != "project" and is_unused(ins, s)
    elif v == "costly":
        keep = s["path"] in (costly if costly is not None else costly_unused(ins, st.harness))
    elif v in ("similar", "diverged"):
        keep = overlap_view(ins, st, s)
    elif v == "review":
        keep = is_risky(s)
    else:
        keep = v == "all" or switch_state(ins, st.harness, s)["on"] == (v == "on")
    return keep and matches(ins, s, st.query)


def overlap_view(ins: Insights, st: ViewState, s: dict) -> bool:
    found = similar_of(ins, st.harness, s) if st.view == "similar" else s.get("copies")
    return bool(found)


def sort_skills(ins: Insights, skills: Iterable[dict], sort: str) -> list[dict]:
    if sort == "uses":
        return sorted(skills, key=lambda s: (-uses(ins, s), collate(s["name"])))
    if sort == "recent":
        return sorted(skills, key=lambda s: (-last_used(ins, s), collate(s["name"])))
    if sort == "cost":
        return sorted(skills, key=lambda s: (-(s.get("tokens_listed") or 0), collate(s["name"])))
    return sorted(skills, key=lambda s: collate(s["name"]))


def visible_skills(ins: Insights, st: ViewState) -> list[dict]:
    costly = costly_unused(ins, st.harness) if st.view == "costly" else None
    return sort_skills(ins, [s for s in ins.skills if visible(ins, st, s, costly)], st.sort)


def loaded_skills(ins: Insights, harness: str) -> list[dict]:
    return [
        s
        for s in ins.skills
        if s.get("status") != "stale" and s.get("scope") != "project" and loads(harness, s)
    ]


def window_title(ins: Insights, harness: str) -> str:
    """The web tab title: "(3↑ · 2 new) Skill Atlas" when there is news."""
    up = sum(1 for s in loaded_skills(ins, harness) if is_outdated(ins, s))
    fresh = new_total(ins)
    badge = " · ".join(p for p in (f"{up}↑" if up else "", f"{fresh} new" if fresh else "") if p)
    return f"({badge}) Skill Atlas" if ins.writable and badge else "Skill Atlas"


def counts(ins: Insights, st: ViewState) -> dict[str, int]:
    """The number on each view tab. Similar and Diverged show none."""
    lv = loaded_skills(ins, st.harness)
    on = sum(1 for s in lv if switch_state(ins, st.harness, s)["on"])
    return {
        "all": len(lv),
        "on": on,
        "off": len(lv) - on,
        "updates": sum(1 for s in lv if is_outdated(ins, s)),
        "issues": sum(1 for s in lv if s.get("problems")),
        "new": new_total(ins),
        "unused": sum(1 for s in lv if is_unused(ins, s)),
        "costly": len(costly_unused(ins, st.harness)),
        "review": sum(1 for s in ins.skills if in_view(ins, st, s) and is_risky(s)),
    }


def view_tabs(ins: Insights, st: ViewState, n: dict[str, int] | None = None) -> list[Tab]:
    """The view tabs the strip shows, in order. Unused waits while usage loads."""
    n = n if n is not None else counts(ins, st)
    status = (ins.usage or {}).get("status")
    hidden = {
        "updates": not ins.writable,
        "issues": not n["issues"] and st.view != "issues",
        "new": not ins.writable or (not n["new"] and st.view != "new"),
        "unused": not ins.writable or status == "error",
        "costly": st.view != "costly",
        "similar": st.view != "similar",
        "diverged": st.view != "diverged",
        "review": not n["review"] and st.view != "review",
    }
    return [
        Tab(
            id=v,
            label=label,
            title=title,
            count=n.get(v),
            waiting=v == "unused" and not use_ready(ins),
        )
        for v, label, title in VIEWS
        if not hidden.get(v)
    ]


def shown_views(ins: Insights, st: ViewState) -> list[str]:
    return [t["id"] for t in view_tabs(ins, st)]


# --------------------------------------------------------------------------
# the list: sections and groups
# --------------------------------------------------------------------------


def _is_open(st: ViewState, collapsed: Collection[str], gid: str) -> bool:
    return bool(st.q) or gid not in collapsed


def _group_order(ins: Insights, sort: str, label: str, shown: list[dict]) -> tuple:
    name = collate(label, base=True)
    if sort == "uses":
        return (-sum(uses(ins, s) for s in shown), name)
    if sort == "recent":
        return (-max([0.0, *(last_used(ins, s) for s in shown)]), name)
    if sort == "cost":
        return (-cost_total(shown), name)
    return (0, name)


def _group(gid: str, kind: str, key: str, label: str, shown: list[dict], **kw: object) -> Group:
    base = {
        "id": gid,
        "kind": kind,
        "key": key,
        "label": label,
        "repo": None,
        "repo_url": "",
        "hue": hue(gid),
        "local": False,
        "open": True,
        "skills": shown,
        "members": shown,
        "on": len(shown),
        "total": len(shown),
        "checked": "true",
        "switch": False,
        "meta": "",
        "fresh": 0,
        "spark": None,
        "available": [],
        "available_total": 0,
        "available_open": False,
        "available_note": "",
        "installable": 0,
        "fresh_installable": 0,
    }
    return cast(Group, {**base, **kw})


def _source_group(
    ins: Insights,
    st: ViewState,
    source: str,
    shown: list[dict],
    members: list[dict],
    collapsed: Collection[str],
) -> Group:
    gid = f"src:{source}"
    on = sum(1 for s in members if switch_state(ins, st.harness, s)["on"])
    url = next((_origin(s)["sourceUrl"] for s in members if _origin(s).get("sourceUrl")), "")
    local = is_local_group(source)
    avail = _available(ins).get(source) or []
    if members:
        tally = f"{on} of {len(members)} on"
        if len(shown) < len(members) and st.view != "new":
            tally += f" · {len(shown)} shown"
    else:
        tally = "watching"
    meta = ("local · " if local and source != NO_SOURCE else "") + tally
    if avail:
        meta += f" · {len(avail)} not installed"
    block = not local and reads_store(ins, st.harness)
    offer = avail_shown(ins, st, source) if block and avail else []
    installable = [a for a in avail if not a.get("taken")]
    note = "You have every skill from this repo. New ones will show here."
    return _group(
        gid,
        "src",
        source,
        source,
        shown,
        repo=None if local else source,
        repo_url=_repo_url(url, source, local),
        hue=hue(source),
        local=local,
        open=st.view == "new" or _is_open(st, collapsed, gid),
        members=members,
        on=on,
        total=len(members),
        checked="true" if on == len(members) else "false" if on == 0 else "mixed",
        switch=bool(members) and switchable(ins, st.harness),
        meta=meta,
        fresh=len(new_in(ins, source)),
        spark=group_spark(ins, members),
        available=offer,
        available_total=len(avail),
        available_open=bool(offer) and avail_open(ins, st, source, len(members), collapsed),
        available_note=note if block and not avail and not members else "",
        installable=len(installable),
        fresh_installable=sum(1 for a in installable if a.get("new")),
    )


def _repo_url(url: str, source: str, local: bool) -> str:
    if url:
        return url.removesuffix(".git")
    return "" if local else f"https://github.com/{source}"


def _source_groups(
    ins: Insights, st: ViewState, personal: list[dict], collapsed: Collection[str]
) -> list[Group]:
    alive = [s for s in ins.skills if live(st.harness, s)]
    members = dict(_group_map(alive, lambda s: source_of(ins, s)))
    grouped = _group_map(personal, lambda s: source_of(ins, s))
    have = {k for k, _ in grouped}
    for repo in _available(ins):
        if repo in have:
            continue
        idle = repo in _watched(ins) and st.view == "all" and not st.q and repo not in members
        if reads_store(ins, st.harness) and (avail_shown(ins, st, repo) or idle):
            grouped.append((repo, []))
    grouped.sort(key=lambda g: (g[0] == NO_SOURCE, _group_order(ins, st.sort, g[0], g[1])))
    return [
        _source_group(ins, st, src, lst, members.get(src, []), collapsed) for src, lst in grouped
    ]


def _plugin_group(
    ins: Insights, st: ViewState, ref: str, shown: list[dict], collapsed: Collection[str]
) -> Group:
    gid = f"plg:{ref}"
    lv = next((s for s in shown if s.get("status") != "stale"), shown[0])
    sw = switch_state(ins, st.harness, lv)
    note = " · not in enabledPlugins" if sw["mode"] == "not set" else ""
    repo = repo_of(lv)
    return _group(
        gid,
        "plg",
        ref,
        lv.get("plugin") or ref,
        shown,
        repo=repo,
        repo_url=f"https://github.com/{repo}" if repo else "",
        open=_is_open(st, collapsed, gid),
        on=sum(1 for s in shown if switch_state(ins, st.harness, s)["on"]),
        checked="true" if sw["on"] else "false",
        switch=lv.get("status") != "stale",
        meta=f"{lv.get('marketplace', '')} · {plural(len(shown), 'skill')}{note}",
        spark=group_spark(ins, shown),
    )


def _project_group(
    st: ViewState, name: str, shown: list[dict], collapsed: Collection[str]
) -> Group:
    gid = f"prj:{name}"
    return _group(
        gid,
        "prj",
        name,
        name,
        shown,
        open=_is_open(st, collapsed, gid),
        meta=f"loads only inside this project · {len(shown)}",
    )


def _section(
    sid: str,
    title: str,
    count: str,
    st: ViewState,
    collapsed: Collection[str],
    groups: list[Group],
    rows: list[dict],
    ids: list[str],
) -> Section:
    return Section(
        id=sid,
        title=title,
        count=count,
        open=_is_open(st, collapsed, sid),
        groups=groups,
        rows=rows,
        group_ids=ids,
    )


def sections(ins: Insights, st: ViewState, collapsed: Collection[str] = ()) -> list[Section]:
    """The list: Your skills (or New), Plugins, and Project skills, each with ordered groups.
    `collapsed` holds the ids the user folded. Grouped by scope, Your skills has rows only."""
    shown = visible_skills(ins, st)
    out: list[Section] = []
    personal = [s for s in shown if s.get("scope") == "personal"]
    by_source = st.group_by == "source" or st.view == "new"
    offered = []
    if by_source:
        quiet = st.view == "all" and not st.q
        offered = [
            r for r in _available(ins) if avail_shown(ins, st, r) or (quiet and r in _watched(ins))
        ]
    if personal or offered:
        total = sum(1 for s in ins.skills if live(st.harness, s))
        groups = _source_groups(ins, st, personal, collapsed) if by_source else []
        ids = [f"src:{source_of(ins, s)}" for s in personal] + [f"src:{r}" for r in offered]
        ids = list(dict.fromkeys(ids)) if by_source else []
        rows = [] if by_source else personal
        if st.view == "new":
            n = sum(len(avail_shown(ins, st, r)) for r in offered)
            out.append(
                _section(
                    "sec:new", "New from your sources", str(n), st, collapsed, groups, rows, ids
                )
            )
        else:
            count = str(total) if len(personal) == total else f"{len(personal)} of {total}"
            out.append(
                _section("sec:personal", "Your skills", count, st, collapsed, groups, rows, ids)
            )

    plugins = [s for s in shown if s.get("scope") == "plugin"]
    if plugins:
        refs = _group_map(plugins, lambda s: s.get("plugin_ref") or "")
        refs.sort(key=lambda g: _group_order(ins, st.sort, g[0], g[1]))
        groups = [_plugin_group(ins, st, ref, lst, collapsed) for ref, lst in refs]
        ids = [f"plg:{r}" for r, _ in refs]
        out.append(
            _section("sec:plugins", "Plugins", str(len(plugins)), st, collapsed, groups, [], ids)
        )

    project = [s for s in shown if s.get("scope") == "project"]
    if project:
        names = _group_map(project, lambda s: s.get("project") or "")
        names.sort(key=lambda g: _group_order(ins, st.sort, g[0], g[1]))
        groups = [_project_group(st, name, lst, collapsed) for name, lst in names]
        ids = [f"prj:{n}" for n, _ in names]
        out.append(
            _section(
                "sec:project", "Project skills", str(len(project)), st, collapsed, groups, [], ids
            )
        )
    return out


def groups(ins: Insights, st: ViewState, collapsed: Collection[str] = ()) -> list[Group]:
    """Every group of every section, in list order."""
    return [g for sec in sections(ins, st, collapsed) for g in sec["groups"]]


def empty_state(ins: Insights, st: ViewState) -> Empty:
    """What the list says when no section shows. Actions: clear, show_project, recheck, view_all."""
    q, v = st.q, st.view
    if q:
        terms = q.lower().split()
        hidden = sum(
            1
            for s in ins.skills
            if not in_view(ins, st, s) and all(t in search_haystack(ins, s) for t in terms)
        )
        body = "Try fewer or shorter words." if v == "all" else f"The {v} filter is on."
        if hidden:
            body += f" {plural(hidden, 'hidden skill')} match."
        actions = ["clear"] + (["show_project"] if hidden and not st.show_project else [])
        return Empty(title=f"No skills match “{q}”", body=body, actions=actions)
    if v in ("updates", "new"):
        at = checked_ms(ins)
        mins = None if at is None else max(0, _round((_now_ms(ins) - at) / 60000))
        when = (
            "No check has run yet."
            if mins is None
            else f"Checked {mins}m ago."
            if mins
            else "Checked just now."
        )
        if v == "new":
            when += " Your sources have not added skills since you last looked."
        title = "No new skills" if v == "new" else "Everything is up to date"
        return Empty(title=title, body=when, actions=["recheck"])
    fixed = {
        "issues": (
            "No problems found",
            "Each SKILL.md in this view has valid frontmatter, and each file it names is there.",
        ),
        "similar": (
            "No similar skills",
            "No two skills in this harness have descriptions that overlap a lot.",
        ),
        "diverged": (
            "No diverged copies",
            "Each copy of a skill has the same SKILL.md as the others.",
        ),
        "review": (
            "Nothing to review",
            f"No skill in this view has high-risk patterns. {SEC_NOTE}",
        ),
        "unused": ("Every skill is in use", "Each one ran in the last 90 days."),
        "costly": (
            "No costly skills sit unused",
            f"Each costly skill that is on ran in the last {UNUSED_DAYS} days.",
        ),
        "off": ("Nothing is off", "Every skill in this view loads."),
    }
    title, body = fixed.get(
        v, ("No skills here", "Turn on Project skills or Old plugin versions to see more.")
    )
    to_all = v in ("issues", "similar", "diverged", "review", "costly")
    return Empty(title=title, body=body, actions=["view_all"] if to_all else [])


# --------------------------------------------------------------------------
# rows, panels, and bulk actions
# --------------------------------------------------------------------------


def worst(problems: list[dict]) -> str:
    return "error" if any(p.get("level") == "error" for p in problems) else "warn"


def _tag(kind: str, text: str, title: str = "", level: str = "") -> Tag:
    return Tag(kind=kind, text=text, title=title, level=level)


def _sec_tag(s: dict) -> Tag | None:
    x = s.get("security") or {}
    if x.get("level") == "high":
        high = (x.get("counts") or {}).get("high", 0)
        title = f"{plural(high, 'high-risk pattern')}. Read Security in the detail panel."
        return _tag("risk", "review", title)
    if x.get("code"):
        return _tag("plain", "runs code", f"Ships {plural(x['code'], 'script')} the agent can run")
    return None


def tags(ins: Insights, harness: str, s: dict) -> list[Tag]:
    """A row's tags, in order. The row shows the first two, then +N. `kind` is the CSS class."""
    out: list[Tag] = []
    problems = s.get("problems") or []
    if problems:
        why = "\n".join(p.get("message", "") for p in problems)
        out.append(_tag("issue", plural(len(problems), "problem"), why, worst(problems)))
    sec = _sec_tag(s)
    if sec and is_risky(s):
        out.append(sec)
    if s.get("local_edits"):
        why = "Changed after install. Updating replaces your changes."
        out.append(_tag("edited", "edited", why))
    if update_status(ins, s) == "unknown":
        why = "Not found in the source repo. It may have moved or been removed."
        out.append(_tag("gone", "not upstream", why))
    if is_outdated(ins, s) and not ins.writable:
        out.append(_tag("update", "update"))
    if s.get("manual_only"):
        why = "disable-model-invocation: the agent never calls it on its own"
        out.append(_tag("manual", "you only", why))
    if s.get("claude_only"):
        out.append(_tag("manual", "agent only", "user-invocable: false. It is not in the / menu"))
    if sec and not is_risky(s):
        out.append(sec)
    mode = switch_state(ins, harness, s)["mode"]
    if mode and mode not in ("on", "off", "not set", "project only"):
        out.append(_tag("plain", mode))
    if s.get("status") == "stale":
        out.append(_tag("plain", f"v{s.get('plugin_version')}"))
    same = dupes(ins, s)
    if same:
        out.append(_tag("plain", f"same as {same[0]}", f"Same as {', '.join(same)}"))
    sim = similar_of(ins, harness, s)
    if sim:
        close = ", ".join(x["name"] for x in sim)
        why = f"Its description is close to {close}. The agent may pick the wrong one."
        out.append(_tag("plain", "similar", why))
    cp = s.get("copies") or []
    if cp:
        verb = "has" if len(cp) == 1 else "have"
        why = f"{plural(len(cp), 'other copy')} with this name {verb} a different SKILL.md"
        out.append(_tag("div", "diverged", why))
    return out


def row_state(ins: Insights, harness: str, s: dict, job: str | None = None) -> str:
    """busy, done, project, off, edited, outdated, or on. `job` is the job state of lock_name(s)."""
    if job in RUNNING:
        return "busy"
    if job == "done":
        return "done"
    if s.get("scope") == "project":
        return "project"
    if not switch_state(ins, harness, s)["on"]:
        return "off"
    if s.get("local_edits"):
        return "edited"
    return "outdated" if is_outdated(ins, s) else "on"


def inventory(ins: Insights, harness: str) -> dict[str, int]:
    """The stats at the top of the inventory panel."""
    lv = loaded_skills(ins, harness)
    personal = [s for s in lv if s.get("scope") == "personal"]
    on = sum(1 for s in lv if switch_state(ins, harness, s)["on"])
    return {
        "on": on,
        "off": len(lv) - on,
        "updates": sum(1 for s in lv if is_outdated(ins, s)),
        "untracked": sum(1 for s in personal if not lock_name(s)),
        "duplicates": sum(1 for s in personal if dupes(ins, s)),
        "edited": sum(1 for s in personal if s.get("local_edits")),
        "uses": sum(uses(ins, s) for s in lv),
        "unused": sum(1 for s in lv if is_unused(ins, s)),
    }


def _store_detail(problems: list[dict]) -> str:
    ghosts = sum(1 for p in problems if p.get("code") == "ghost-lock")
    broken = len(problems) - ghosts
    parts = [
        f"{ghosts} lock {'entry' if ghosts == 1 else 'entries'} with no folder" if ghosts else "",
        f"{plural(broken, 'folder')} that no harness can load" if broken else "",
    ]
    return " · ".join(p for p in parts if p)


def attention(ins: Insights, st: ViewState) -> list[Item]:
    """The Needs attention items, danger first. `action` is a view id, "restore", or ""."""
    items: list[Item] = []
    store = (ins.scan.get("health") or {}).get("problems") or []
    if store:
        tone = "danger" if worst(store) == "error" else "warn"
        text = plural(len(store), "store problem")
        items.append(
            Item(key="a-store", tone=tone, text=text, detail=_store_detail(store), action="")
        )
    high = sum(1 for s in ins.skills if in_view(ins, st, s) and is_risky(s))
    if high:
        detail = f"{plural(high, 'skill')} with high-risk security findings."
        text = f"{plural(high, 'skill')} to review"
        items.append(Item(key="a-sec", tone="danger", text=text, detail=detail, action="review"))
    lv = loaded_skills(ins, st.harness)
    bad = [s for s in lv if s.get("problems")]
    if bad:
        tone = "danger" if any(worst(s["problems"]) == "error" for s in bad) else "warn"
        n = plural(len(bad), "skill")
        detail = f"{n} with SKILL.md problems."
        items.append(
            Item(key="a-prob", tone=tone, text=f"{n} with problems", detail=detail, action="issues")
        )
    m = ins.missing
    if ins.writable and m:
        who = "1 skill in the lock file has" if m == 1 else f"{m} skills in the lock file have"
        detail = f"{who} no folder."
        items.append(
            Item(key="a-miss", tone="warn", text=f"{m} missing", detail=detail, action="restore")
        )
    diverged = overlap_counts(ins, st.harness, lv)["diverged"]
    if diverged:
        text = plural(diverged, "diverged name")
        detail = f"{plural(diverged, 'skill name')} with copies that differ."
        items.append(Item(key="a-div", tone="warn", text=text, detail=detail, action="diverged"))
    costly = len(costly_unused(ins, st.harness))
    if costly:
        text = plural(costly, "costly skill")
        detail = f"{text} not used in {UNUSED_DAYS} days."
        text += " not used"
        items.append(Item(key="a-cost", tone="warn", text=text, detail=detail, action="costly"))
    return sorted(items, key=lambda i: i["tone"] != "danger")


def attention_cue(items: list[Item]) -> dict[str, str] | None:
    """The folded pane's cue: the worst tone, and one item's text or a count."""
    if not items:
        return None
    text = items[0]["text"] if len(items) == 1 else f"{len(items)} things to check"
    return {"tone": items[0]["tone"], "text": text}


def group_for(ins: Insights, gid: str) -> dict:
    """The selection object for a group id (src:, plg:, prj:), as the detail panel reads it."""
    kind, key = gid[:3], gid[4:]
    base = {"kind": "group", "type": kind, "id": gid, "key": f"g:{gid}", "hue_key": gid}
    if kind == "plg":
        refs = [x for x in ins.skills if x.get("plugin_ref") == key]
        lv = next((x for x in refs if x.get("status") != "stale"), refs[0] if refs else None)
        label = (lv or {}).get("plugin") or key
        return {**base, "ref": key, "label": label, "repo": repo_of(lv) if lv else None}
    if kind == "prj":
        return {**base, "project": key, "label": key, "repo": None}
    repo = None if is_local_group(key) else key
    return {**base, "type": "src", "source": key, "label": key, "repo": repo, "hue_key": key}


def members_of(ins: Insights, harness: str, gid: str) -> list[dict]:
    """The skills a group's detail counts. Plugin groups list none for "all", as on the page."""
    kind, key = gid[:3], gid[4:]
    if kind == "plg":
        return [
            x
            for x in ins.skills
            if x.get("plugin_ref") == key
            and x.get("status") != "stale"
            and harness in (x.get("harnesses") or [])
        ]
    if kind == "prj":
        return [x for x in ins.skills if x.get("scope") == "project" and x.get("project") == key]
    return [s for s in ins.skills if live(harness, s) and source_of(ins, s) == key]


def group_stats(ins: Insights, harness: str, skills: list[dict]) -> dict[str, int | None]:
    """The stats in a group's detail. `unused` is None while usage loads."""
    on = sum(1 for s in skills if switch_state(ins, harness, s)["on"])
    return {
        "on": on,
        "off": len(skills) - on,
        "updates": sum(1 for s in skills if is_outdated(ins, s)),
        "edited": sum(1 for s in skills if s.get("local_edits")),
        "you_only": sum(1 for s in skills if s.get("manual_only")),
        "unused": sum(1 for s in skills if is_unused(ins, s)) if use_ready(ins) else None,
    }


def bulk_plan(ins: Insights, harness: str, marked: list[dict]) -> dict:
    """What each bulk action would touch among the marked skills, given in scan order."""
    own = [s for s in marked if live(harness, s) and (switchable(ins, harness) or harness == "all")]
    plugins = list(
        dict.fromkeys(
            s["plugin_ref"]
            for s in marked
            if s.get("scope") == "plugin" and s.get("status") != "stale"
        )
    )
    cfg = ((ins.scan.get("settings") or {}).get(harness) or {}).get("enabledPlugins") or {}
    lit = [switch_state(ins, harness, s)["on"] for s in own]
    return {
        "list": marked,
        "on": {
            "skills": [s for s, on in zip(own, lit, strict=True) if not on],
            "plugins": [r for r in plugins if cfg.get(r) is not True],
        },
        "off": {
            "skills": [s for s, on in zip(own, lit, strict=True) if on],
            "plugins": [r for r in plugins if cfg.get(r) is True],
        },
        "update": [s for s in own if s.get("store") and is_outdated(ins, s)],
        "link": [s for s in own if s.get("store") and not lock_name(s)],
        "delete": [s for s in own if s.get("store")],
    }
