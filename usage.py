"""Count skill use from Claude Code's own counters and from its session transcripts."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from scan import read_json

REPO = Path(__file__).resolve().parent
CACHE = REPO / "out" / "usage-index.json"
DEDUPE_SECONDS = 600
RESCAN_SECONDS = 30
CHECKPOINT_SECONDS = 20
COMMAND = re.compile(r"<command-name>/([^<\s]+)</command-name>")
MARKERS = (b'"Skill"', b"<command-name>/")

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "finished": 0.0,
    "agg": None,
    "error": None,
}
_counter_cache: dict[str, tuple[tuple[int, int], dict]] = {}


# --------------------------------------------------------------------------
# counters
# --------------------------------------------------------------------------


def state_file(root: Path) -> Path:
    """~/.claude keeps its state beside it in ~/.claude.json; other roots keep it inside."""
    home = Path.home()
    if root.expanduser().resolve() == (home / ".claude").resolve():
        return home / ".claude.json"
    return root / ".claude.json"


def iso_ms(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _skill_usage(path: Path) -> dict:
    """skillUsage from a state file. It can be big, so parse it again only when it changes."""
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (st.st_size, st.st_mtime_ns)
    hit = _counter_cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    found = read_json(path).get("skillUsage")
    found = found if isinstance(found, dict) else {}
    _counter_cache[str(path)] = (key, found)
    return found


def counters(roots: list[Path]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for root in roots:
        for name, e in _skill_usage(state_file(root)).items():
            if not isinstance(e, dict):
                continue
            c = out.setdefault(name, {"count": 0, "last_ms": 0})
            c["count"] += _int(e.get("usageCount"))
            c["last_ms"] = max(c["last_ms"], _int(e.get("lastUsedAt")))
    return {
        n: {"count": c["count"], "last": iso_ms(c["last_ms"]) if c["last_ms"] else None}
        for n, c in out.items()
    }


# --------------------------------------------------------------------------
# transcripts
# --------------------------------------------------------------------------


def project_of(cwd: str) -> str:
    return Path(cwd.split("/.claude/worktrees/", 1)[0]).name if cwd else ""


def parse_line(line: bytes) -> list[list[str]]:
    """Skill events in one transcript line, each as [timestamp, session, skill, project]."""
    if not any(m in line for m in MARKERS):
        return []
    try:
        d = json.loads(line)
    except ValueError:
        return []
    if not isinstance(d, dict):
        return []
    msg = d.get("message")
    if not isinstance(msg, dict) or not d.get("timestamp"):
        return []
    content = msg.get("content")
    names: list[str] = []
    if d.get("type") == "assistant" and isinstance(content, list):
        names = [
            str(c["input"]["skill"])
            for c in content
            if isinstance(c, dict)
            and c.get("type") == "tool_use"
            and c.get("name") == "Skill"
            and isinstance(c.get("input"), dict)
            and c["input"].get("skill")
        ]
    elif d.get("type") == "user" and isinstance(content, str):
        names = COMMAND.findall(content)
    meta = [str(d["timestamp"]), str(d.get("sessionId") or ""), project_of(str(d.get("cwd") or ""))]
    return [[meta[0], meta[1], n, meta[2]] for n in names]


def read_events(path: Path, offset: int) -> tuple[list[list[str]], int]:
    """Events from complete lines after `offset`, and the offset after the last one."""
    events: list[list[str]] = []
    pos = offset
    with path.open("rb") as fh:
        fh.seek(offset)
        for line in fh:
            if not line.endswith(b"\n"):
                break  # a line still being written; the next pass reads it whole
            pos += len(line)
            events += parse_line(line)
    return events, pos


def transcripts(roots: list[Path]) -> list[Path]:
    return sorted({p for r in roots for p in (r / "projects").glob("**/*.jsonl") if p.is_file()})


def _valid(entry) -> bool:
    return (
        isinstance(entry, dict)
        and all(isinstance(entry.get(k), int) for k in ("size", "mtime", "offset"))
        and isinstance(entry.get("events"), list)
        and all(isinstance(e, list) and len(e) == 4 for e in entry["events"])
    )


def cached_files(cache: Path) -> dict[str, dict]:
    files = read_json(cache).get("files")
    return {k: v for k, v in files.items() if _valid(v)} if isinstance(files, dict) else {}


def save(cache: Path, files: dict[str, dict]) -> None:
    """Write the cache. A folder you cannot write to only costs a full read next start."""
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(cache.name + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "files": files}), encoding="utf-8")
        os.replace(tmp, cache)
    except OSError as e:
        print(f"skill-atlas: cannot save the usage cache: {e}", file=sys.stderr)


def index(roots: list[Path], cache: Path, progress=None) -> dict[str, dict]:
    """Bring the per-file cache up to date. Only new bytes of a grown file are read."""
    old = cached_files(cache)
    files = transcripts(roots)
    new: dict[str, dict] = {}
    saved = time.monotonic()
    for i, path in enumerate(files):
        try:
            st = path.stat()
            prev = old.get(str(path))
            if prev and prev["size"] == st.st_size and prev["mtime"] == st.st_mtime_ns:
                new[str(path)] = prev
            else:
                # Same file grown: read on from the old offset. A new or cut file: read it all.
                start, kept = 0, []
                if prev and st.st_size >= prev["size"] and prev.get("ino", st.st_ino) == st.st_ino:
                    start, kept = prev["offset"], prev["events"]
                events, offset = read_events(path, start)
                new[str(path)] = {
                    "size": st.st_size,
                    "mtime": st.st_mtime_ns,
                    "ino": st.st_ino,
                    "offset": offset,
                    "events": kept + events,
                }
        except OSError:
            continue
        if progress:
            progress(i + 1, len(files))
        if time.monotonic() - saved > CHECKPOINT_SECONDS:
            # A long first pass keeps its work if the server stops part way.
            save(cache, {**old, **new})
            saved = time.monotonic()
    save(cache, new)
    return new


def _local_day(ts: str) -> tuple[float, str]:
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.timestamp(), t.astimezone().date().isoformat()


def aggregate(files: dict[str, dict]) -> dict:
    """Daily counts and projects per skill. Two uses in one session within 10 minutes count once."""
    rows = []
    for f in files.values():
        for ts, session, skill, project in f["events"]:
            try:
                at, day = _local_day(ts)
            except ValueError:
                continue
            rows.append((session, skill, at, day, project, ts))
    rows.sort()
    skills: dict[str, dict] = {}
    last_kept: dict[tuple[str, str], float] = {}
    first_day = None
    for session, skill, at, day, project, ts in rows:
        key = (session, skill)
        if session and key in last_kept and at - last_kept[key] < DEDUPE_SECONDS:
            continue
        last_kept[key] = at
        s = skills.setdefault(skill, {"days": {}, "projects": {}, "last": ts})
        s["days"][day] = s["days"].get(day, 0) + 1
        if project:
            s["projects"][project] = s["projects"].get(project, 0) + 1
        s["last"] = max(s["last"], ts)
        first_day = day if first_day is None else min(first_day, day)
    return {"skills": skills, "first_day": first_day}


# --------------------------------------------------------------------------
# background passes
# --------------------------------------------------------------------------


def _run(roots: list[Path]) -> None:
    try:
        if _state["agg"] is None:
            # Show what the last run found while this one catches up.
            _state["agg"] = aggregate(cached_files(CACHE))

        def progress(done: int, total: int) -> None:
            _state["done"], _state["total"] = done, total

        _state["agg"] = aggregate(index(roots, CACHE, progress))
        _state["error"] = None
    except Exception as e:
        _state["error"] = f"could not count skill use: {e}"
        print(f"skill-atlas: {_state['error']}", file=sys.stderr)
    finally:
        with _lock:
            _state["running"] = False
            _state["finished"] = time.time()


def start(roots: list[Path]) -> bool:
    """Start one incremental pass unless one is running or the last one ended moments ago."""
    with _lock:
        if _state["running"] or time.time() - _state["finished"] < RESCAN_SECONDS:
            return False
        _state["running"] = True
    threading.Thread(target=_run, args=(roots,), daemon=True).start()
    return True


def snapshot(roots: list[Path]) -> dict:
    start(roots)
    agg = _state["agg"] or {"skills": {}, "first_day": None}
    return {
        "status": "indexing" if _state["running"] else "ready",
        "error": _state["error"],
        "progress": [_state["done"], _state["total"]],
        "counters": counters(roots),
        "skills": agg["skills"],
        "first_day": agg["first_day"],
        "today": datetime.now().astimezone().date().isoformat(),
    }
