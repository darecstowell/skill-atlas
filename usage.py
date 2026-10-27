"""Count skill use from Claude Code's counters and from the session logs of each agent harness."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
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
# session logs
# --------------------------------------------------------------------------

CLAUDE, CODEX, GEMINI, COPILOT, OPENCODE = (
    "claude-code",
    "codex",
    "gemini-cli",
    "copilot-cli",
    "opencode",
)
SKILL_FILE = re.compile(r"([\w.:-]+)/SKILL\.md")
SKILL_TAG = re.compile(r"<skill>\s*<name>\s*([^<]+?)\s*</name>")
HEX64 = re.compile(r"[0-9a-f]{64}")
CODEX_MARKERS = (b'"session_meta"', b'"turn_context"', b"SKILL.md", b"<skill>")


def project_of(cwd: str) -> str:
    return Path(cwd.split("/.claude/worktrees/", 1)[0]).name if cwd else ""


def _obj(line: bytes) -> dict:
    try:
        d = json.loads(line)
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def _event(ts, ctx: dict, skill, harness: str) -> list[str]:
    project = ctx.get("project") or project_of(str(ctx.get("cwd") or ""))
    return [str(ts), str(ctx.get("session") or ""), str(skill), project, harness]


def parse_line(line: bytes, ctx: dict | None = None) -> list[list[str]]:
    """Skill events in one Claude Code transcript line."""
    if not any(m in line for m in MARKERS):
        return []
    d = _obj(line)
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
    meta = {"session": d.get("sessionId"), "cwd": d.get("cwd")}
    return [_event(d["timestamp"], meta, n, CLAUDE) for n in names]


def parse_codex(line: bytes, ctx: dict) -> list[list[str]]:
    """Codex reads a skill's SKILL.md with a tool; a `$skill` mention adds a <skill> fragment."""
    if not any(m in line for m in CODEX_MARKERS):
        return []
    d = _obj(line)
    p = d.get("payload")
    if not isinstance(p, dict):
        return []
    if d.get("type") in ("session_meta", "turn_context"):
        if d["type"] == "session_meta" and p.get("id"):
            ctx["session"] = str(p["id"])
        if p.get("cwd"):
            ctx["cwd"] = str(p["cwd"])
        return []
    if d.get("type") != "response_item" or not d.get("timestamp"):
        return []
    kind = p.get("type")
    if kind in ("custom_tool_call", "function_call") and p.get("name") != "apply_patch":
        names = SKILL_FILE.findall(str(p.get("input") or p.get("arguments") or ""))
    elif kind == "message" and p.get("role") == "user" and isinstance(p.get("content"), list):
        texts = [str(c.get("text") or "") for c in p["content"] if isinstance(c, dict)]
        names = [n for t in texts for n in SKILL_TAG.findall(t)]
    else:
        return []
    return [_event(d["timestamp"], ctx, n, CODEX) for n in dict.fromkeys(names)]


def _gemini_calls(msg, ctx: dict) -> list[list[str]]:
    """activate_skill calls in one Gemini message. Rewritten messages count each call once."""
    calls = msg.get("toolCalls") if isinstance(msg, dict) else None
    out = []
    seen = ctx.setdefault("seen", [])
    for c in calls if isinstance(calls, list) else []:
        if not isinstance(c, dict) or c.get("name") != "activate_skill":
            continue
        args, key = c.get("args"), str(c.get("id") or "")
        ts = c.get("timestamp") or msg.get("timestamp")
        if not isinstance(args, dict) or not args.get("name") or not ts or key in seen:
            continue
        if c.get("status") not in (None, "success"):
            continue
        if key:
            seen.append(key)
        out.append(_event(ts, ctx, args["name"], GEMINI))
    return out


def parse_gemini(line: bytes, ctx: dict) -> list[list[str]]:
    if b"activate_skill" not in line and b'"sessionId"' not in line:
        return []
    d = _obj(line)
    if d.get("sessionId"):
        ctx["session"] = str(d["sessionId"])
    return _gemini_calls(d, ctx)


def read_gemini_json(path: Path, ctx: dict) -> list[list[str]]:
    """Older Gemini CLI chats are one JSON document, rewritten on each turn."""
    d = read_json(path)
    ctx["seen"] = []
    if d.get("sessionId"):
        ctx["session"] = str(d["sessionId"])
    msgs = d.get("messages")
    return [e for m in (msgs if isinstance(msgs, list) else []) for e in _gemini_calls(m, ctx)]


def parse_copilot(line: bytes, ctx: dict) -> list[list[str]]:
    if b'"skill.invoked"' not in line and b'"session.start"' not in line:
        return []
    d = _obj(line)
    data = d.get("data")
    if not isinstance(data, dict):
        return []
    if d.get("type") == "session.start":
        context = data.get("context")
        cwd = (context.get("cwd") if isinstance(context, dict) else None) or data.get("cwd")
        if cwd:
            ctx["cwd"] = str(cwd)
        if data.get("sessionId"):
            ctx["session"] = str(data["sessionId"])
        return []
    if d.get("type") != "skill.invoked" or not data.get("name") or not d.get("timestamp"):
        return []
    return [_event(d["timestamp"], ctx, data["name"], COPILOT)]


def _col(row: sqlite3.Row, name: str):
    try:
        return row[name]
    except IndexError:
        return None


def read_opencode(path: Path, ctx: dict) -> list[list[str]]:
    """Skill tool calls in OpenCode's database, opened read-only."""
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
    try:
        con.row_factory = sqlite3.Row
        try:
            dirs = {
                _col(r, "id"): _col(r, "directory") for r in con.execute("SELECT * FROM session")
            }
        except sqlite3.Error:
            dirs = {}
        rows = con.execute("SELECT * FROM part WHERE data LIKE '%skill%'").fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        d = _obj(str(_col(r, "data") or "").encode())
        state = d.get("state")
        if d.get("type") != "tool" or d.get("tool") != "skill" or not isinstance(state, dict):
            continue
        args, times = state.get("input"), state.get("time")
        name = args.get("name") if isinstance(args, dict) else None
        ms = _int(times.get("start") if isinstance(times, dict) else 0) or _int(
            _col(r, "time_created")
        )
        if not name or not ms or state.get("status") == "error":
            continue
        session = str(_col(r, "session_id") or d.get("sessionID") or "")
        meta = {"session": session, "cwd": dirs.get(session) or ""}
        out.append(_event(iso_ms(ms), meta, name, OPENCODE))
    return out


LINE_READERS = {
    CLAUDE: parse_line,
    CODEX: parse_codex,
    GEMINI: parse_gemini,
    COPILOT: parse_copilot,
}
WHOLE_READERS = {GEMINI: read_gemini_json, OPENCODE: read_opencode}


def read_events(path: Path, offset: int, parse=parse_line, ctx: dict | None = None):
    """Events from complete lines after `offset`, and the offset after the last one."""
    events: list[list[str]] = []
    ctx = {} if ctx is None else ctx
    pos = offset
    with path.open("rb") as fh:
        fh.seek(offset)
        for line in fh:
            if not line.endswith(b"\n"):
                break  # a line still being written; the next pass reads it whole
            pos += len(line)
            events += parse(line, ctx)
    return events, pos


def transcripts(roots: list[Path]) -> list[Path]:
    return sorted({p for r in roots for p in (r / "projects").glob("**/*.jsonl") if p.is_file()})


def _base(var: str, *default: str) -> Path:
    v = os.environ.get(var)
    return Path(v).expanduser() if v else Path.home().joinpath(*default)


def sources(roots: list[Path]) -> list[tuple[Path, str]]:
    """Every session log to read, with the harness that wrote it. Absent harnesses add none."""
    codex = _base("CODEX_HOME", ".codex")
    gemini = _base("GEMINI_CLI_HOME") / ".gemini" / "tmp"
    db = _base("XDG_DATA_HOME", ".local", "share") / "opencode" / "opencode.db"
    found = [(p, CLAUDE) for p in transcripts(roots)]
    found += [(p, CODEX) for p in codex.glob("sessions/**/rollout-*.jsonl")]
    found += [(p, CODEX) for p in codex.glob("archived_sessions/rollout-*.jsonl")]
    found += [(p, GEMINI) for p in gemini.glob("*/chats/session-*.json*")]
    found += [
        (p, COPILOT) for p in _base("COPILOT_HOME", ".copilot").glob("session-state/*/events.jsonl")
    ]
    found += [(db, OPENCODE)]
    return sorted(
        {(p, h) for p, h in found if p.suffix in (".jsonl", ".json", ".db") and p.is_file()}
    )


def _gemini_project(path: Path) -> str:
    """tmp/<id>/chats/<file>: <id> is a short name or the SHA-256 of the project path."""
    d = path.parent.parent
    try:
        return project_of((d / ".project_root").read_text(encoding="utf-8").strip())
    except OSError:
        pass
    known = read_json(d.parent.parent / "projects.json").get("projects")
    for p, short in (known if isinstance(known, dict) else {}).items():
        if d.name in (short, hashlib.sha256(str(p).encode()).hexdigest()):
            return project_of(str(p))
    return "" if HEX64.fullmatch(d.name) else d.name


def seed(path: Path, harness: str) -> dict:
    """What a log's path tells about its session before any line is read."""
    if harness == CODEX:
        return {"session": path.stem[-36:]}
    if harness == COPILOT:
        return {"session": path.parent.name}
    if harness == GEMINI:
        return {"session": path.stem, "project": _gemini_project(path)}
    return {}


def _signature(path: Path, harness: str) -> tuple[int, int, int]:
    """Size, mtime and inode. A database also changes through its write-ahead log."""
    st = path.stat()
    size, mtime = st.st_size, st.st_mtime_ns
    if harness == OPENCODE:
        try:
            wal = Path(f"{path}-wal").stat()
            size, mtime = size + wal.st_size, max(mtime, wal.st_mtime_ns)
        except OSError:
            pass
    return size, mtime, st.st_ino


def _valid(entry) -> bool:
    return (
        isinstance(entry, dict)
        and all(isinstance(entry.get(k), int) for k in ("size", "mtime", "offset"))
        and isinstance(entry.get("events"), list)
        and all(isinstance(e, list) and len(e) in (4, 5) for e in entry["events"])
        and isinstance(entry.get("ctx", {}), dict)
    )


def cached_files(cache: Path) -> dict[str, dict]:
    """Cached entries. Events from version 1 caches have no harness, so they are Claude Code's."""
    files = read_json(cache).get("files")
    if not isinstance(files, dict):
        return {}
    out = {k: v for k, v in files.items() if _valid(v)}
    for v in out.values():
        v["events"] = [e if len(e) == 5 else [*e, CLAUDE] for e in v["events"]]
    return out


def save(cache: Path, files: dict[str, dict]) -> None:
    """Write the cache. A folder you cannot write to only costs a full read next start."""
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(cache.name + ".tmp")
        tmp.write_text(json.dumps({"version": 2, "files": files}), encoding="utf-8")
        os.replace(tmp, cache)
    except OSError as e:
        print(f"skill-atlas: cannot save the usage cache: {e}", file=sys.stderr)


def _read(path: Path, harness: str, prev: dict | None) -> dict:
    """A fresh cache entry. A grown log is read on from the old offset; others are read whole."""
    size, mtime, ino = _signature(path, harness)
    entry = {"size": size, "mtime": mtime, "ino": ino, "harness": harness}
    if harness in WHOLE_READERS and path.suffix != ".jsonl":
        ctx = seed(path, harness)
        return {**entry, "offset": size, "events": WHOLE_READERS[harness](path, ctx), "ctx": ctx}
    start, kept, ctx = 0, [], seed(path, harness)
    if prev and size >= prev["size"] and prev.get("ino", ino) == ino:
        start, kept, ctx = prev["offset"], prev["events"], dict(prev.get("ctx") or ctx)
    events, offset = read_events(path, start, LINE_READERS[harness], ctx)
    return {**entry, "offset": offset, "events": kept + events, "ctx": ctx}


def index(roots: list[Path], cache: Path, progress=None) -> dict[str, dict]:
    """Bring the per-file cache up to date. One odd file is skipped, not fatal."""
    old = cached_files(cache)
    files = sources(roots)
    new: dict[str, dict] = {}
    saved = time.monotonic()
    for i, (path, harness) in enumerate(files):
        try:
            prev = old.get(str(path))
            size, mtime, _ = _signature(path, harness)
            if prev and prev["size"] == size and prev["mtime"] == mtime:
                new[str(path)] = prev
            else:
                new[str(path)] = _read(path, harness, prev)
        except (OSError, ValueError, sqlite3.Error):
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
    """Daily counts, projects and harnesses per skill. Two uses in one session within 10 minutes
    count once."""
    rows = []
    for f in files.values():
        for ts, session, skill, project, *rest in f["events"]:
            try:
                at, day = _local_day(ts)
            except ValueError:
                continue
            rows.append((session, skill, rest[0] if rest else CLAUDE, at, day, project, ts))
    rows.sort()
    skills: dict[str, dict] = {}
    last_kept: dict[tuple[str, str, str], float] = {}
    last_at: dict[str, float] = {}
    first_day = None
    for session, skill, harness, at, day, project, ts in rows:
        key = (harness, session, skill)
        if session and key in last_kept and at - last_kept[key] < DEDUPE_SECONDS:
            continue
        last_kept[key] = at
        s = skills.setdefault(skill, {"days": {}, "projects": {}, "harnesses": {}, "last": ts})
        s["days"][day] = s["days"].get(day, 0) + 1
        if project:
            s["projects"][project] = s["projects"].get(project, 0) + 1
        s["harnesses"][harness] = s["harnesses"].get(harness, 0) + 1
        if at >= last_at.get(skill, at):
            s["last"], last_at[skill] = ts, at
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
