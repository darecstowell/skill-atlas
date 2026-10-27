"""Diff a tracked skill against upstream, and keep snapshots so an update can be rolled back."""

from __future__ import annotations

import difflib
import io
import json
import os
import re
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import updates
from scan import as_dict, git_tree_hash, read_json

KEEP = 5
MAX_TEXT_BYTES = 512 * 1024
MAX_FILE_LINES = 600
MAX_TOTAL_LINES = 4000
SNAP_ID = re.compile(r"^\d{8}T\d{9}Z(-\d+)?$")


def history_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    return Path(base).expanduser() / "skill-atlas" / "history"


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------


def _tar_folder(blob: bytes, folder: str) -> dict[str, bytes]:
    """The files of one folder in a GitHub tarball, by path inside that folder."""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        return {
            rel: updates.member_bytes(tar, m)
            for rel, m in updates.folder_members(tar, folder)
            if m.isfile()
        }


def _local_folder(path: Path) -> dict[str, bytes]:
    out = {}
    for p in sorted(path.rglob("*")):
        rel = p.relative_to(path)
        if ".git" in rel.parts:
            continue
        if p.is_symlink():
            out[rel.as_posix()] = os.readlink(p).encode()
        elif p.is_file():
            out[rel.as_posix()] = p.read_bytes()
    return out


def _text(data: bytes | None) -> list[str] | None:
    if data is None:
        return []
    if len(data) > MAX_TEXT_BYTES or b"\0" in data:
        return None
    try:
        return data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


def diff_folders(old: dict[str, bytes], new: dict[str, bytes]) -> dict:
    """Added, removed, and changed files from old to new, with unified diffs for text."""
    files, budget = [], MAX_TOTAL_LINES
    for path in sorted(old.keys() | new.keys()):
        a, b = old.get(path), new.get(path)
        if a == b:
            continue
        status = "added" if a is None else "removed" if b is None else "changed"
        entry: dict = {"path": path, "status": status, "added": 0, "removed": 0}
        lines_a, lines_b = _text(a), _text(b)
        if lines_a is None or lines_b is None:
            entry.update(binary=True, old_size=len(a or b""), new_size=len(b or b""))
            files.append(entry)
            continue
        body = list(difflib.unified_diff(lines_a, lines_b, lineterm="", n=3))[2:]
        entry["added"] = sum(1 for x in body if x.startswith("+"))
        entry["removed"] = sum(1 for x in body if x.startswith("-"))
        cap = max(0, min(MAX_FILE_LINES, budget))
        entry["diff"] = body[:cap]
        entry["truncated"] = len(body) > cap
        budget -= len(entry["diff"])
        files.append(entry)
    return {
        "files": files,
        "added": sum(f["added"] for f in files),
        "removed": sum(f["removed"] for f in files),
    }


def diff(name: str, roots: list[Path]) -> dict:
    """What an update would change in one tracked skill, read from the cached tarball."""
    found = updates.tracked(roots).get(name)
    if found is None:
        raise ValueError(f"{name} is not linked to a GitHub repo")
    lock, e = found
    repo, ref = e["source"], e.get("ref") or "HEAD"
    new = _tar_folder(updates.cached_tarball(repo, ref), updates.folder_of(e["skillPath"]))
    if "SKILL.md" not in new:
        raise ValueError(f"{e['skillPath']} is not in {repo}")
    skill_dir = lock.parent / "skills" / name
    old = _local_folder(skill_dir) if skill_dir.is_dir() else {}
    try:
        edited = skill_dir.is_dir() and git_tree_hash(skill_dir) != e["skillFolderHash"]
    except OSError:
        edited = False
    return {"name": name, "repo": repo, "local_edits": edited, **diff_folders(old, new)}


# --------------------------------------------------------------------------
# snapshots
# --------------------------------------------------------------------------


def _stamp() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"


def snapshot(skill_dir: Path, name: str, lock: Path, entry: dict, reason: str = "update") -> None:
    """Copy a skill folder and its lock entry to the history cache, then keep the newest few."""
    if not skill_dir.is_dir():
        return
    home = history_root() / name
    base = _stamp()
    snap, n = home / base, 1
    while snap.exists():
        n += 1
        snap = home / f"{base}-{n}"
    shutil.copytree(skill_dir, snap / "skill", symlinks=True)
    meta = {"at": updates.now_iso(), "reason": reason, "lock": str(lock), "entry": entry}
    (snap / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    prune(name)


def _snap_dirs(name: str) -> list[Path]:
    home = history_root() / name
    if not home.is_dir():
        return []
    return sorted((p for p in home.iterdir() if SNAP_ID.match(p.name)), reverse=True)


def prune(name: str, keep: int = KEEP) -> None:
    for old in _snap_dirs(name)[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def listing(name: str) -> dict:
    """The snapshots of one skill, newest first."""
    out = []
    for snap in _snap_dirs(name):
        meta = read_json(snap / "meta.json")
        entry = as_dict(meta.get("entry"))
        out.append(
            {
                "id": snap.name,
                "at": meta.get("at", ""),
                "reason": meta.get("reason", "update"),
                "hash": str(entry.get("skillFolderHash", ""))[:7],
            }
        )
    return {"name": name, "snapshots": out}


def rollback(name: str, snap_id: str, roots: list[Path]) -> dict:
    """Put a snapshot and its lock entry back through a staged swap. Saves the current one first."""
    if not SNAP_ID.match(snap_id):
        raise ValueError("bad snapshot id")
    snap = history_root() / name / snap_id
    meta = read_json(snap / "meta.json")
    entry = meta.get("entry")
    if not (snap / "skill" / "SKILL.md").is_file() or not isinstance(entry, dict):
        raise ValueError("that snapshot is gone or incomplete")
    found = updates.tracked(roots).get(name)
    if found is None:
        raise ValueError(f"{name} is not linked to a GitHub repo")
    if updates.job_running():
        raise RuntimeError("an update is still running")
    lock, current = found
    skills_dir = lock.parent / "skills"
    staged = skills_dir / f".atlas-new-{name}"
    shutil.rmtree(staged, ignore_errors=True)
    shutil.copytree(snap / "skill", staged, symlinks=True)
    try:
        snapshot(skills_dir / name, name, lock, current, reason="restore")
        updates.swap_in(skills_dir / name, staged)
    except OSError:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    updates.write_lock_entries(lock, {name: entry})
    updates.clear_cache()
    return {"name": name, "restored": snap_id, "at": meta.get("at", "")}
