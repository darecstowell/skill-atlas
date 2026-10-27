"""Move personal skills to the Trash, and put them back."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from scan import ATLAS_LOCK, read_json_strict, skill_lock_path


def _default_trash() -> tuple[Path | None, Path | None]:
    """The Trash folder, plus the freedesktop info folder on Linux. None where there is no Trash."""
    if sys.platform == "darwin":
        return Path.home() / ".Trash", None
    if os.name == "posix":
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        return base / "Trash" / "files", base / "Trash" / "info"
    return None, None


TRASH, TRASH_INFO = _default_trash()
_last: dict = {}


def _write_json(path: Path, data: dict) -> None:
    path = path.resolve()
    tmp = path.with_name(path.name + ".atlas-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _section(data: dict, key: str) -> dict:
    v = data.get(key)
    return v if isinstance(v, dict) else {}


def _put_entries(path: Path, key: str, entries: dict) -> None:
    if entries:
        data = read_json_strict(path)
        data[key] = {**_section(data, key), **entries}
        _write_json(path, data)


def _trash_dir() -> Path:
    if TRASH is None:
        raise NotImplementedError("Delete needs a Trash folder, and this system has none.")
    if TRASH_INFO is not None:
        TRASH.mkdir(parents=True, exist_ok=True)
        TRASH_INFO.mkdir(parents=True, exist_ok=True)
    if not TRASH.is_dir():
        raise NotImplementedError(f"Delete needs a Trash folder, and {TRASH} is not there.")
    return TRASH


def _move_to_trash(src: Path, trash: Path, stamp: str) -> Path:
    dest = trash / f"{src.name} {stamp}"
    n = 1
    while dest.exists() or (TRASH_INFO and (TRASH_INFO / f"{dest.name}.trashinfo").exists()):
        n += 1
        dest = trash / f"{src.name} {stamp} {n}"
    if TRASH_INFO is not None:
        when = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        (TRASH_INFO / f"{dest.name}.trashinfo").write_text(
            f"[Trash Info]\nPath={quote(str(src))}\nDeletionDate={when}\n", encoding="utf-8"
        )
    # shutil.move falls back to a copy when the Trash is on another disk.
    shutil.move(str(src), str(dest))
    return dest


def _take_back(dest: Path, src: Path) -> None:
    shutil.move(str(dest), str(src))
    if TRASH_INFO is not None:
        (TRASH_INFO / f"{dest.name}.trashinfo").unlink(missing_ok=True)


def trash(names: list[str], roots: list[Path]) -> dict:
    """Move each skill folder to the Trash and drop its lock entries and on/off setting."""
    npx_lock = skill_lock_path(roots[0])
    skills_dir = npx_lock.parent / "skills"

    for name in names:
        src = skills_dir / name
        # Only real skill folders right under the skills folder.
        if src.parent != skills_dir or not (src / "SKILL.md").exists():
            raise ValueError(f"not a personal skill: {name}")
    # Read every file first, so a broken one stops the delete before anything moves.
    files = [(lock, "skills") for lock in (npx_lock, npx_lock.with_name(ATLAS_LOCK))]
    files += [(root / "settings.json", "skillOverrides") for root in roots]
    contents = {path: read_json_strict(path) for path, _ in files}
    trash_dir = _trash_dir()

    stamp = time.strftime("%H.%M.%S")
    moved: dict[str, str] = {}
    try:
        for name in names:
            moved[name] = str(_move_to_trash(skills_dir / name, trash_dir, stamp))
    except OSError:
        for name, dest in moved.items():
            _take_back(Path(dest), skills_dir / name)
        raise

    record: dict[str, dict] = {"folders": moved, "locks": {}, "settings": {}}
    for path, key in files:
        data = contents[path]
        section = _section(data, key)
        removed = {n: section.pop(n) for n in names if n in section}
        if removed:
            _write_json(path, data)
        record["locks" if key == "skills" else "settings"][str(path)] = removed

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
            _take_back(Path(dest), skills_dir / name)
            restored.append(name)
    for lock, entries in _last["locks"].items():
        _put_entries(Path(lock), "skills", entries)
    for path, entries in _last["settings"].items():
        _put_entries(Path(path), "skillOverrides", entries)
    _last.clear()
    return {"restored": sorted(restored)}
