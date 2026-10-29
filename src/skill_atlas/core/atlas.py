"""The real `AtlasAPI`: the reads and writes behind each `/api/...` route, for web and TUI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .. import (
    PACKAGE,
    REPO,
    __version__,
    assets,
    harnesses,
    history,
    manifest,
    overlap,
    profiles,
    remove,
    security,
    updates,
    usage,
)
from ..scan import (
    config_path,
    load_config,
    read_json_strict,
    scan,
    settings_state,
    store_home,
)

SAFE_NAME = re.compile(r"^[A-Za-z0-9][\w.-]*$")


def source_hash() -> str:
    """A hash of the Python files, so a process can tell that its code changed on disk."""
    if not PACKAGE.is_dir():
        return __version__
    h = hashlib.sha256()
    for path in sorted([*PACKAGE.glob("*.py"), *PACKAGE.glob("core/*.py")]):
        try:
            h.update(path.relative_to(PACKAGE).as_posix().encode() + b"\0" + path.read_bytes())
        except OSError:
            continue
    return h.hexdigest()[:12]


def write_setting(root: Path, kind: str, names: list[str], on: bool) -> None:
    write_settings(root, {kind: dict.fromkeys(names, on)})


def write_settings(root: Path, changes: dict[str, dict[str, bool]]) -> None:
    """Skill and plugin switches, {kind: {name: on}}, in one write of settings.json."""
    for kind in changes:
        if kind not in ("skill", "plugin"):
            raise ValueError(f"unknown kind {kind!r}")
    path = root / "settings.json"
    # Write through a symlink, so a settings file kept in a dotfiles repo stays linked.
    target = path.resolve()
    settings = read_json_strict(target)
    if target.exists() and not os.access(target, os.W_OK):
        raise ValueError(f"{target} is read-only, so the atlas cannot change it")
    backup = path.with_name("settings.json.atlas-bak")
    if target.exists() and not backup.exists():
        shutil.copy2(target, backup)

    for kind, states in changes.items():
        key = "skillOverrides" if kind == "skill" else "enabledPlugins"
        section = settings.get(key, {})
        if not isinstance(section, dict):
            raise ValueError(f"{key} in {target} is not an object. Fix the file, then try again.")
        if kind == "skill":
            for name, on in states.items():
                if on:
                    section.pop(name, None)
                else:
                    section[name] = "off"
        else:
            section.update(states)
        if section:
            settings[key] = section
        else:
            settings.pop(key, None)

    tmp = target.with_name("settings.json.atlas-tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    if target.exists():
        shutil.copymode(target, tmp)
    os.replace(tmp, target)


def reveal_file(path: str) -> None:
    """Show a file in the system file manager."""
    if sys.platform == "darwin":
        cmd = ["open", "-R", path]
    elif os.name == "nt":
        cmd = ["explorer", f"/select,{path}"]
    else:
        cmd = ["xdg-open", str(Path(path).parent)]
    if not shutil.which(cmd[0]):
        raise NotImplementedError(f"cannot show files on this system: {cmd[0]} is not installed")
    try:
        subprocess.run(cmd, check=False, timeout=10, capture_output=True)
    except subprocess.TimeoutExpired:
        pass  # the file manager is open; it only did not exit


def skill_name(name: str) -> str:
    if not SAFE_NAME.match(name):
        raise ValueError("bad skill name")
    return name


def skill_names(names: list[str]) -> list[str]:
    if not names or not all(SAFE_NAME.match(n) for n in names):
        raise ValueError("bad skill names")
    return names


def skill_source(repo: str, paths: list[str]) -> tuple[str, list[str]]:
    """A GitHub repo and the SKILL.md paths in it, checked."""
    repo = updates.parse_repo(repo)
    if not paths or not all(map(updates.safe_skill_path, paths)):
        raise ValueError("bad skill paths")
    return repo, paths


def _find(data: dict | None, path: str) -> dict | None:
    return next((s for s in data["skills"] if s["path"] == path), None) if data else None


def config_roots(repo: Path) -> dict[str, Path]:
    """The config roots in the user's config that exist here, the same set `scan` reads."""
    roots = load_config(repo)["config_roots"].items()
    found = {label: Path(os.path.expanduser(p)) for label, p in roots}
    return {label: p for label, p in found.items() if p.is_dir()}


class Atlas:
    """Reads and changes the skills under `config_roots`, which it reads again on each call."""

    def __init__(
        self,
        config_roots: dict[str, Path],
        repo: Path,
        *,
        scanner: Callable[[Path], dict] = scan,
        info: Callable[[], dict] | None = None,
    ) -> None:
        self.config_roots = config_roots
        self.repo = repo
        self.scanner = scanner
        self.build = source_hash()
        self.info = info or self._build_info
        self.last_scan: dict = {}

    def _build_info(self) -> dict:
        return {"build": self.build, "stale": source_hash() != self.build}

    def _scan(self) -> dict:
        return self.scanner(self.repo)

    def _skills(self) -> list[dict]:
        return self._scan()["skills"]

    def _detect(self) -> list[harnesses.Harness]:
        return harnesses.detect(dict(self.config_roots))

    def server_info(self) -> dict:
        """The build this process runs, and whether the code on disk is newer."""
        return self.info()

    def roots(self) -> list[Path]:
        """The skill store first, where installs and deletes go, then each Claude Code root."""
        home = store_home(dict(self.config_roots))
        if home is None:
            raise ValueError(
                "no skills folder found. Install a skill, or set config_roots in the config"
            )
        return list(dict.fromkeys([home, *self.config_roots.values()]))

    def page_scan(self) -> dict:
        """A fresh scan, kept so per-skill calls need not scan again."""
        self.last_scan["data"] = data = self._scan()
        return data

    def scanned_record(self, path: str) -> dict:
        """Only skills the scan itself reported, so a caller cannot reach arbitrary files."""
        rec = _find(self.last_scan.get("data"), path) or _find(self.page_scan(), path)
        if rec is None:
            raise ValueError("unknown skill path")
        return rec

    # Reads

    def now(self) -> datetime:
        return datetime.now().astimezone()

    def data(self) -> dict:
        where = str(config_path(self.repo)).replace(str(Path.home()), "~", 1)
        return {**self.page_scan(), "server": self.server_info(), "config_path": where}

    def skill_text(self, path: str) -> str:
        want = self.scanned_record(path)["path"]
        return Path(want).read_text(encoding="utf-8", errors="replace")

    def usage(self) -> dict:
        return usage.snapshot(list(self.config_roots.values()))

    def updates(self, refresh: bool = False) -> dict:
        return updates.check(self.roots(), refresh=refresh)

    def diff(self, name: str) -> dict:
        return history.diff(skill_name(name), self.roots())

    def history(self, name: str) -> dict:
        return history.listing(skill_name(name))

    def snapshot_diff(self, name: str, snap_id: str) -> dict:
        return history.snapshot_diff(skill_name(name), snap_id, self.roots())

    def compare(self, a: str, b: str) -> dict:
        return overlap.diff(self.scanned_record(a)["path"], self.scanned_record(b)["path"])

    def security(self, path: str) -> dict:
        rec = self.scanned_record(path)
        return security.report(Path(rec["path"]).parent, rec["allowed_tools"])

    def profiles(self) -> dict:
        return profiles.listing()

    def export(self) -> dict:
        return manifest.export(self._scan(), self.roots())

    def restore_plan(self) -> dict:
        return manifest.missing(self.roots())

    def job(self, job_id: str) -> dict | None:
        job = updates.JOBS.get(job_id)
        return None if job is None else updates.job_view(job)

    def repos(self, repos: list[str]) -> dict:
        """Stars and images for up to 50 GitHub repos."""
        return assets.fetch(sorted({updates.parse_repo(r) for r in repos})[:50])

    def available_text(self, repo: str, path: str) -> str:
        """The SKILL.md of a skill a repo offers, from raw.githubusercontent.com."""
        repo, (path,) = skill_source(repo, [path])
        return updates.fetch_raw(repo, path)

    # Writes

    def toggle(self, root: str, kind: str, names: list[str], on: bool) -> dict:
        """Turn skills or a plugin on or off in one harness, and return that harness's new state."""
        h = {h.id: h for h in self._detect()}.get(root)
        if h is None:
            raise ValueError(f"unknown harness {root!r}")
        if h.switch == "claude":
            write_setting(h.home, kind, names, on)
            return settings_state(h.home)
        if kind != "skill":
            raise ValueError(f"{h.name} has no plugin switch")
        mine = [s for s in self._skills() if s["name"] in names and h.id in s["harnesses"]]
        if not mine:
            raise ValueError(f"{h.name} does not load {', '.join(names)}")
        harnesses.set_skills(h, mine, on)
        return harnesses.state(h, self._skills())

    def reveal(self, path: str) -> None:
        reveal_file(self.scanned_record(path)["path"])

    def watch(self, repo: str, on: bool) -> dict:
        return updates.watch(repo, on, self.roots())

    def available(self, repo: str, paths: list[str]) -> dict:
        repo, paths = skill_source(repo, paths)
        return updates.describe(repo, paths, self.roots())

    def install(self, repo: str, paths: list[str]) -> dict:
        repo, paths = skill_source(repo, paths)
        return updates.job_view(updates.start_install({repo: paths}, self.roots()))

    def dismiss(self, repo: str, paths: list[str]) -> dict:
        repo, paths = skill_source(repo, paths)
        return updates.dismiss(repo, paths, self.roots())

    def rollback(self, name: str, snap_id: str) -> dict:
        return history.rollback(skill_name(name), snap_id, self.roots())

    def profile(self, action: str, req: dict) -> dict:
        return profiles.handle(action, req, self._detect, self._skills, write_settings)

    def _import(self, req: dict) -> tuple[dict, dict, list[Path]]:
        data, rs = self._scan(), self.roots()
        if req.get("restore"):
            return manifest.missing(rs), data, rs
        return manifest.plan(dict(req["manifest"]), data, rs), data, rs

    def import_plan(self, req: dict) -> dict:
        return self._import(req)[0]

    def import_apply(self, req: dict) -> dict:
        full, data, rs = self._import(req)
        return manifest.apply(full, req, data, rs, self._detect(), write_setting)

    def undo_delete(self) -> dict:
        return remove.undo()

    def update(self, names: list[str]) -> dict:
        return updates.job_view(updates.start_update(skill_names(names), self.roots()))

    def link(self, names: list[str], repo: str) -> dict:
        return updates.link(skill_names(names), repo, self.roots())

    def delete(self, names: list[str]) -> dict:
        return remove.trash(skill_names(names), self.roots())


def default() -> Atlas:
    """The Atlas over this machine's config, as `atlas` serves it."""
    return Atlas(config_roots(REPO), REPO)
