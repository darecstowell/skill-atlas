"""Move personal skills to the macOS Trash, and put them back."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from scan import ATLAS_LOCK, read_json, skill_lock_path

TRASH = Path.home() / ".Trash"
_last: dict = {}


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".atlas-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def _pop_entries(path: Path, key: str, names: list[str]) -> dict:
    data = read_json(path)
    removed = {n: data[key].pop(n) for n in names if n in data.get(key, {})}
    if removed:
        _write_json(path, data)
    return removed


def _put_entries(path: Path, key: str, entries: dict) -> None:
    if entries:
        data = read_json(path)
        data.setdefault(key, {}).update(entries)
        _write_json(path, data)


def trash(names: list[str], roots: list[Path]) -> dict:
    """Move each skill folder to the Trash and drop its lock entries and on/off setting."""
    npx_lock = skill_lock_path(roots[0])
    skills_dir = npx_lock.parent / "skills"
    record: dict[str, dict] = {"folders": {}, "locks": {}, "settings": {}}

    for name in names:
        src = skills_dir / name
        # Only real skill folders right under the skills folder.
        if src.parent != skills_dir or not (src / "SKILL.md").exists():
            raise ValueError(f"not a personal skill: {name}")
    stamp = time.strftime("%H.%M.%S")
    for name in names:
        dest = TRASH / f"{name} {stamp}"
        os.rename(skills_dir / name, dest)
        record["folders"][name] = str(dest)

    for lock in (npx_lock, npx_lock.with_name(ATLAS_LOCK)):
        record["locks"][str(lock)] = _pop_entries(lock, "skills", names)
    for root in roots:
        path = root / "settings.json"
        record["settings"][str(path)] = _pop_entries(path, "skillOverrides", names)

    _last.clear()
    _last.update(record, skills_dir=str(skills_dir))
    return {"trashed": sorted(record["folders"])}


def undo() -> dict:
    """Put back everything the last trash() call removed."""
    if not _last:
        raise ValueError("nothing to undo")
    skills_dir = Path(_last["skills_dir"])
    restored = []
    for name, dest in _last["folders"].items():
        if Path(dest).exists() and not (skills_dir / name).exists():
            os.rename(dest, skills_dir / name)
            restored.append(name)
    for lock, entries in _last["locks"].items():
        _put_entries(Path(lock), "skills", entries)
    for path, entries in _last["settings"].items():
        _put_entries(Path(path), "skillOverrides", entries)
    _last.clear()
    return {"restored": sorted(restored)}
