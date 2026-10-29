"""UI state, the loaded data, and the saved display preferences."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from ..core import views
from . import theme

GROUPS = ("source", "type")
GROUP_SIZES = ("regular", "large")
MOTIONS = ("full", "reduced", "off")
SAVED = (
    "harness",
    "group_by",
    "sort",
    "compact",
    "group_size",
    "palette",
    "mode",
    "key_hints",
    "motion",
    "show_project",
    "show_stale",
    "detail_open",
    "panel_width",
    "collapsed",
    "folded",
    "reader_raw",
)
SETS = ("marked", "collapsed", "folded")
CHOICES: dict[str, tuple[str, ...]] = {
    "view": tuple(v[0] for v in views.VIEWS),
    "group_by": GROUPS,
    "group_size": GROUP_SIZES,
    "motion": MOTIONS,
    "sort": views.SORTS,
    "palette": theme.PALETTES,
    "mode": theme.MODES,
}
PREFS_ENV = "SKILL_ATLAS_TUI_PREFS"
Basis = tuple[dict | None, ...]  # (scan, updates, usage)
PARTS = ("scan", "usage", "updates")


@dataclass
class UIState:
    """What the user sees: filters, layout, selection, marks, and look."""

    harness: str = ""
    view: str = "all"
    query: str = ""
    group_by: str = "source"
    sort: str = "name"
    show_project: bool = False
    show_stale: bool = False
    compact: bool = False
    group_size: str = "regular"  # "large": two-line group headers, as the web's large collections
    detail_open: bool = True
    selected: str | None = None
    selected_key: str | None = None  # a group id or `a:<repo>:<path>`; only when selected is None
    marked: frozenset[str] = frozenset()
    collapsed: frozenset[str] = frozenset()  # folded list groups, with the web's keys
    # Panel sections the user changed: `key` when folded, `key:open` when opened by default.
    folded: frozenset[str] = frozenset()
    palette: str = "atlas"
    mode: str = "dark"
    key_hints: bool = True
    motion: str = "full"  # full, reduced (Textual "basic"), or off ("none")
    reader_raw: bool = False  # the reader opens in its Markdown view
    panel_width: int = 0  # cells; 0 picks the width from the window size

    def prefs(self) -> dict[str, Any]:
        return {k: sorted(v) if k in SETS else v for k in SAVED for v in [getattr(self, k)]}

    def view_state(self) -> views.ViewState:
        """The filter fields, as core.views reads them."""
        return views.ViewState(
            harness=self.harness or "all",
            view=self.view,
            query=self.query,
            group_by=self.group_by,
            sort=self.sort,
            show_project=self.show_project,
            show_stale=self.show_stale,
        )


FIELDS = frozenset(f.name for f in fields(UIState))


def prefs_path() -> Path:
    """$SKILL_ATLAS_TUI_PREFS, else $XDG_CONFIG_HOME/skill-atlas/tui.json."""
    env = os.environ.get(PREFS_ENV)
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "skill-atlas" / "tui.json"


def valid(name: str, value: Any) -> bool:
    default = getattr(UIState(), name)
    if name in ("selected", "selected_key"):
        return value is None or isinstance(value, str)
    if name in SETS:
        return isinstance(value, (set, frozenset, list)) and all(isinstance(v, str) for v in value)
    if type(value) is not type(default):
        return False
    if name == "panel_width":
        return 0 <= value <= 400
    return name not in CHOICES or value in CHOICES[name]


def load(path: Path) -> UIState:
    """The saved preferences on top of the defaults. Bad or unknown values are skipped."""
    state = UIState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if isinstance(raw, dict):
        if raw.get("reduced_motion") is True:  # saved before `motion` had three levels
            raw.setdefault("motion", "reduced")
        for name in SAVED:
            if name in raw and valid(name, raw[name]):
                value = raw[name]
                setattr(state, name, frozenset(value) if name in SETS else value)
    return state


def save(state: UIState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state.prefs(), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class AtlasData:
    """The latest results from the core, and which parts are loading or failed."""

    scan: dict | None = None
    usage: dict | None = None
    updates: dict | None = None
    loading: set[str] = field(default_factory=set)
    errors: dict[str, str] = field(default_factory=dict)
    missing: int = 0  # len(restore_plan()["install"]); the side panel's "N missing" item
    _insights: views.Insights | None = field(default=None, repr=False)
    _counts: tuple[object, dict[tuple, dict[str, int]]] = field(
        default_factory=lambda: (None, {}), repr=False
    )

    @property
    def skills(self) -> list[dict]:
        return self.scan["skills"] if self.scan else []

    @property
    def harnesses(self) -> dict[str, dict]:
        return self.scan.get("harnesses", {}) if self.scan else {}

    @property
    def available(self) -> dict[str, list[dict]]:
        """Skills that watched repos offer, by repo, from the update check."""
        return (self.updates or {}).get("available") or {}

    @property
    def insights(self) -> views.Insights | None:
        """What core.views reads, built once per change. None until the scan arrives."""
        if self._insights is None and self.scan is not None:
            self._insights = self.build((self.scan, self.updates, self.usage))
        return self._insights

    def basis(self, part: str, value: dict) -> Basis:
        """(scan, updates, usage) as they will be once `value` is stored as `part`."""
        got = {"scan": self.scan, "updates": self.updates, "usage": self.usage, part: value}
        return got["scan"], got["updates"], got["usage"]

    def build(self, basis: Basis) -> views.Insights | None:
        """Insights for a basis. Safe on a worker thread: it only reads."""
        scan, updates, usage = basis
        return None if scan is None else views.Insights(scan, updates, usage, missing=self.missing)

    def counts(self, st: views.ViewState) -> dict[str, int]:
        """The view tab counts, once per Insights for each harness and scope."""
        ins = self.insights
        if ins is None:
            return {}
        owner, memo = self._counts
        if owner is not ins:
            memo = {}
            self._counts = (ins, memo)
        key = (st.harness, st.show_project, st.show_stale)
        if key not in memo:
            memo[key] = views.counts(ins, st)
        return memo[key]

    def skill(self, path: str | None) -> dict | None:
        ins = self.insights
        return ins.by_path.get(path) if ins and path else None

    def put(
        self, part: str, value: dict, basis: Basis = (), insights: views.Insights | None = None
    ) -> None:
        """Store a part. Insights built from `basis` are kept only if no other part moved since."""
        setattr(self, part, value)
        now = (self.scan, self.updates, self.usage)
        fresh = len(basis) == 3 and all(a is b for a, b in zip(basis, now, strict=True))
        self._insights = insights if fresh else None
