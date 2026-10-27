"""Profiles: named sets of skill and plugin switches, applied to each harness in one step."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import harnesses
import scan

MAX_NAME = 60
ACTIONS = ("save", "rename", "delete", "restore", "preview", "apply")
# A writer for one Claude Code root: {"skill": {name: on}, "plugin": {ref: on}}.
ClaudeWriter = Callable[[Path, dict[str, dict[str, bool]]], None]


def path() -> Path:
    return scan.user_config_path().with_name("profiles.json")


def load() -> list[dict]:
    data = scan.read_json_strict(path())
    items = data.get("profiles")
    return (
        [p for p in items if isinstance(p, dict) and p.get("name")]
        if isinstance(items, list)
        else []
    )


def _store(items: list[dict]) -> None:
    target = path().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".atlas-tmp")
    tmp.write_text(json.dumps({"profiles": items}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def _name(v) -> str:
    name = " ".join(str(v or "").split())
    if not name:
        raise ValueError("give the profile a name")
    if len(name) > MAX_NAME:
        raise ValueError(f"use {MAX_NAME} characters or fewer for the name")
    return name


def _find(items: list[dict], name: str) -> dict:
    for p in items:
        if p["name"] == name:
            return p
    raise ValueError(f"no profile is named {name!r}")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def summary(p: dict) -> dict:
    """A profile with on and off counts, for the menu."""
    states = _states(p.get("harnesses"))
    n = {"on": 0, "off": 0}
    for st in states.values():
        for v in [*st["skills"].values(), *st["plugins"].values()]:
            n["on" if v else "off"] += 1
    return {**p, "harnesses": states, **n}


def listing() -> dict:
    return {"profiles": [summary(p) for p in load()]}


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------


def _states(v) -> dict[str, dict[str, dict[str, bool]]]:
    """Clean per-harness switch maps out of a request or a file."""
    out: dict[str, dict[str, dict[str, bool]]] = {}
    for hid, st in (v if isinstance(v, dict) else {}).items():
        st = st if isinstance(st, dict) else {}
        out[str(hid)] = {
            k: {str(n): bool(on) for n, on in scan.as_dict(st.get(k)).items()}
            for k in ("skills", "plugins")
        }
    return out


def _mine(h: harnesses.Harness, skills: list[dict]) -> list[dict]:
    """The skills this harness loads that it can switch."""
    if not h.switch:
        return []
    return [
        s
        for s in skills
        if h.id in s.get("harnesses", [])
        and s.get("status") != "stale"
        and (s["scope"] == "personal" or (h.switch == "claude" and s["scope"] == "plugin"))
    ]


def current(h: harnesses.Harness, skills: list[dict]) -> dict[str, dict[str, bool]]:
    """What is on and off in one harness now, keyed like a profile."""
    mine = _mine(h, skills)
    out: dict[str, dict[str, bool]] = {"skills": {}, "plugins": {}}
    if h.switch == "claude":
        st = scan.settings_state(h.home)
        for s in mine:
            if s["scope"] == "plugin":
                out["plugins"][s["plugin_ref"]] = st["enabledPlugins"].get(s["plugin_ref"]) is True
            else:
                out["skills"][s["name"]] = st["skillOverrides"].get(s["name"]) != "off"
        return out
    off = set(harnesses.off_names(h, skills))
    for s in mine:
        out["skills"][s["name"]] = s["name"] not in off
    return out


def capture(
    found: list[harnesses.Harness],
    skills: list[dict],
    ids: list[str] | None = None,
    picked: dict[str, list[str]] | None = None,
    rest_off: bool = False,
) -> dict:
    """Switch maps for a new profile: each harness as it is now, or the picked ones on."""
    out = {}
    for h in found:
        if not h.switch or (ids is not None and h.id not in ids):
            continue
        now = current(h, skills)
        if picked is not None:
            want = {k: set(picked.get(k) or []) for k in ("skills", "plugins")}
            now = {
                k: {n: True for n in now[k] if n in want[k]}
                | ({n: False for n in now[k] if n not in want[k]} if rest_off else {})
                for k in now
            }
        if now["skills"] or now["plugins"]:
            out[h.id] = now
    if not out:
        raise ValueError("there is nothing to save. No harness here can switch these skills")
    return out


def preview(states: dict, found: list[harnesses.Harness], skills: list[dict]) -> dict[str, dict]:
    """Per harness: what turns on, what turns off, and what the profile names that is gone."""
    by_id = {h.id: h for h in found}
    out: dict[str, dict] = {}
    for hid, want in _states(states).items():
        h = by_id.get(hid)
        row: dict = {"label": (h.label or h.name) if h else hid, "found": h is not None}
        row.update({k: [] for k in ("on", "off", "plugins_on", "plugins_off", "missing")})
        if h is None or not h.switch:
            row["missing"] = sorted([*want["skills"], *want["plugins"]])
            out[hid] = row
            continue
        now = current(h, skills)
        for kind, prefix in (("skills", ""), ("plugins", "plugins_")):
            for n, on in sorted(want[kind].items()):
                if n not in now[kind]:
                    row["missing"].append(n)
                elif now[kind][n] != on:
                    row[prefix + ("on" if on else "off")].append(n)
        out[hid] = row
    return out


def changes(rows: dict[str, dict]) -> int:
    return sum(len(r[k]) for r in rows.values() for k in ("on", "off", "plugins_on", "plugins_off"))


def apply(
    states: dict,
    found: list[harnesses.Harness],
    skills: list[dict],
    write_claude: ClaudeWriter,
) -> dict:
    """Write one config file per harness. Returns the new settings and what to restore for undo."""
    by_id = {h.id: h for h in found}
    rows = preview(states, found, skills)
    previous: dict[str, dict[str, dict[str, bool]]] = {}
    settings: dict[str, dict] = {}
    for hid, row in rows.items():
        h = by_id.get(hid)
        if h is None or not (row["on"] or row["off"] or row["plugins_on"] or row["plugins_off"]):
            continue
        skill_map = dict.fromkeys(row["on"], True) | dict.fromkeys(row["off"], False)
        plugin_map = dict.fromkeys(row["plugins_on"], True) | dict.fromkeys(
            row["plugins_off"], False
        )
        if h.switch == "claude":
            write_claude(h.home, {"skill": skill_map, "plugin": plugin_map})
            settings[hid] = scan.settings_state(h.home)
        else:
            recs = [s for s in _mine(h, skills) if s["name"] in skill_map]
            harnesses.set_skill_states(h, [(s, skill_map[s["name"]]) for s in recs])
            settings[hid] = harnesses.state(h, skills)
        previous[hid] = {
            "skills": {n: not on for n, on in skill_map.items()},
            "plugins": {n: not on for n, on in plugin_map.items()},
        }
    return {"settings": settings, "previous": previous, "changed": changes(rows), "preview": rows}


# --------------------------------------------------------------------------
# requests
# --------------------------------------------------------------------------


def handle(
    action: str,
    req: dict,
    found: Callable[[], list[harnesses.Harness]],
    skills: Callable[[], list[dict]],
    write_claude: ClaudeWriter,
) -> dict:
    """One /api/profiles/<action> call."""
    items = load()
    if action == "save":
        name = _name(req.get("name"))
        ids = req.get("harnesses")
        picked = req.get("picked")
        states = capture(
            found(),
            skills(),
            [str(i) for i in ids] if isinstance(ids, list) else None,
            {k: [str(x) for x in v] for k, v in picked.items() if isinstance(v, list)}
            if isinstance(picked, dict)
            else None,
            bool(req.get("rest_off")),
        )
        old = next((p for p in items if p["name"] == name), None)
        if old is not None and not req.get("replace"):
            raise RuntimeError(f"a profile named {name!r} exists")
        entry = {"name": name, "saved": _now(), "harnesses": states}
        items = [entry if p is old else p for p in items] if old else [*items, entry]
        _store(items)
        return {**listing(), "saved": name}
    if action == "rename":
        p, new = _find(items, str(req.get("name"))), _name(req.get("to"))
        if new != p["name"] and any(x["name"] == new for x in items):
            raise RuntimeError(f"a profile named {new!r} exists")
        p["name"] = new
        _store(items)
        return listing()
    if action == "delete":
        p = _find(items, str(req.get("name")))
        _store([x for x in items if x is not p])
        return {**listing(), "deleted": p}
    if action == "restore":
        raw = req.get("profile")
        if not isinstance(raw, dict):
            raise ValueError("profile must be an object")
        name = _name(raw.get("name"))
        if any(x["name"] == name for x in items):
            raise RuntimeError(f"a profile named {name!r} exists")
        _store(
            [
                *items,
                {
                    "name": name,
                    "saved": str(raw.get("saved") or _now()),
                    "harnesses": _states(raw.get("harnesses")),
                },
            ]
        )
        return listing()
    if action in ("preview", "apply"):
        # Undo sends the previous states inline, not a name.
        states = (
            req["states"] if "states" in req else _find(items, str(req.get("name")))["harnesses"]
        )
        if action == "preview":
            rows = preview(states, found(), skills())
            return {"harnesses": rows, "changed": changes(rows)}
        return apply(states, found(), skills(), write_claude)
    raise ValueError(f"unknown profile action {action!r}")
