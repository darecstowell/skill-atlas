"""Scan every place agent harnesses load skills from and emit one record per skill."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import harnesses
import tokens

HOME = Path.home()


# --------------------------------------------------------------------------
# frontmatter
# --------------------------------------------------------------------------

SCALAR_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal YAML subset: scalars, quoted scalars, block scalars, one nesting level, lists."""
    lines = text.removeprefix("\ufeff").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text

    body = "\n".join(lines[end + 1 :])
    data: dict = {}
    i = 1
    while i < end:
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if raw[:1] in (" ", "\t"):  # stray indent at top level
            i += 1
            continue

        m = SCALAR_KEY.match(raw)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2).strip()

        # block scalar: |, >, |-, >- ...
        if rest[:1] in ("|", ">"):
            fold = rest[0] == ">"
            chunk = []
            i += 1
            while i < end and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                chunk.append(lines[i].strip())
                i += 1
            data[key] = (" " if fold else "\n").join(c for c in chunk if c or not fold).strip()
            continue

        # inline list
        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            data[key] = [_unquote(p) for p in inner.split(",") if p.strip()] if inner else []
            i += 1
            continue

        # nested block (map or list) when the value is empty
        if rest == "":
            child_lines = []
            i += 1
            while i < end and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                child_lines.append(lines[i])
                i += 1
            items = [c.strip()[2:].strip() for c in child_lines if c.strip().startswith("- ")]
            if items:
                data[key] = [_unquote(v) for v in items]
            else:
                child: dict = {}
                for c in child_lines:
                    cm = SCALAR_KEY.match(c.strip())
                    if cm:
                        child[cm.group(1)] = _unquote(cm.group(2))
                data[key] = child
            continue

        data[key] = _unquote(rest)
        i += 1

    return data, body


def as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        return [p.strip() for p in v.split(",") if p.strip()]
    return [str(v)]


def as_dict(v) -> dict:
    return v if isinstance(v, dict) else {}


# --------------------------------------------------------------------------
# host config
# --------------------------------------------------------------------------


def read_json(path: Path) -> dict:
    """The JSON object in a file, or {} when it is missing, unreadable, or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def read_json_strict(path: Path) -> dict:
    """Like read_json, but for writers: a file that exists and is not a JSON object is an error."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot read {path}: {e}. Fix the file, then try again.") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a JSON object. Fix the file, then try again.")
    return data


@dataclass
class HostConfig:
    """Everything read out of one ~/.claude-style config root."""

    label: str
    root: Path
    settings: dict = field(default_factory=dict)
    installed_plugins: dict = field(default_factory=dict)
    marketplaces: dict = field(default_factory=dict)

    @classmethod
    def load(cls, label: str, root: Path) -> HostConfig:
        return cls(
            label=label,
            root=root,
            settings=read_json(root / "settings.json"),
            installed_plugins=as_dict(
                read_json(root / "plugins" / "installed_plugins.json").get("plugins")
            ),
            marketplaces=read_json(root / "plugins" / "known_marketplaces.json"),
        )

    def plugin_enabled(self, ref: str):
        plugins = self.settings.get("enabledPlugins")
        return plugins.get(ref) if isinstance(plugins, dict) else None

    def plugin_installs(self, ref: str) -> list[dict]:
        installs = self.installed_plugins.get(ref)
        return [i for i in installs if isinstance(i, dict)] if isinstance(installs, list) else []


def settings_state(root: Path) -> dict:
    """The two keys the viewer can toggle, read fresh from one root's settings.json."""
    s = read_json(root / "settings.json")
    return {
        "path": str(root / "settings.json"),
        "skillOverrides": as_dict(s.get("skillOverrides")),
        "enabledPlugins": as_dict(s.get("enabledPlugins")),
    }


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# skill record
# --------------------------------------------------------------------------


def git_tree_hash(path: Path) -> str:
    """The git tree SHA of a folder, as GitHub reports it, to spot local edits."""
    entries = []
    for child in path.iterdir():
        if child.name == ".git":
            continue
        if child.is_symlink():
            # Git stores a link as its target text, and following it could loop.
            data = os.readlink(child).encode()
            mode, key = b"120000", child.name
            sha = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
        elif child.is_dir():
            mode, sha, key = b"40000", git_tree_hash(child), child.name + "/"
        else:
            data = child.read_bytes()
            mode = b"100755" if os.access(child, os.X_OK) else b"100644"
            sha = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
            key = child.name
        entries.append((key, mode + b" " + child.name.encode() + b"\0" + bytes.fromhex(sha)))
    body = b"".join(e for _, e in sorted(entries))
    return hashlib.sha1(b"tree %d\0" % len(body) + body).hexdigest()


ATLAS_LOCK = ".atlas-lock.json"


def skill_lock_path(root: Path) -> Path:
    return (root / "skills").resolve().parent / ".skill-lock.json"


def bundle_stats(skill_dir: Path) -> dict:
    files, total, kinds = 0, 0, set()
    for p in skill_dir.rglob("*"):
        if p.is_file() and not p.name.startswith("."):
            files += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
            rel = p.relative_to(skill_dir)
            if len(rel.parts) > 1:
                kinds.add(rel.parts[0])
    return {"file_count": files, "bytes": total, "subdirs": sorted(kinds)}


def _record(skill_md: Path, **kw) -> dict | None:
    """One skill's record, or None when its files cannot be read."""
    try:
        return build_record(skill_md, **kw)
    except OSError as e:
        print(f"skill-atlas: skipped {skill_md}: {e}", file=sys.stderr)
        return None


def build_record(skill_md: Path, *, scope: str, **extra) -> dict:
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    fm, body = parse_frontmatter(text)
    skill_dir = skill_md.parent
    meta = fm.get("metadata")
    if not isinstance(meta, dict):
        meta = {}

    known = {
        "name",
        "description",
        "metadata",
        "license",
        "allowed-tools",
        "argument-hint",
        "references",
        "inputs",
        "version",
        "model",
        "compatibility",
        "disable-model-invocation",
        "user-invocable",
    }
    stat = skill_md.stat()
    headings = len(re.findall(r"^##+ ", body, re.M))

    rec = {
        "name": str(fm.get("name") or skill_dir.name),
        "dir_name": skill_dir.name,
        "description": re.sub(r"\s+", " ", str(fm.get("description", ""))).strip(),
        "scope": scope,
        "manual_only": str(fm.get("disable-model-invocation", "")).lower() == "true",
        "claude_only": str(fm.get("user-invocable", "")).lower() == "false",
        "version": str(fm.get("version") or meta.get("version") or ""),
        "license": str(fm.get("license") or ""),
        "model": str(fm.get("model") or ""),
        "allowed_tools": as_list(fm.get("allowed-tools")),
        "argument_hint": str(fm.get("argument-hint") or ""),
        "compatibility": as_list(fm.get("compatibility")),
        "path": str(skill_md),
        "dir": str(skill_dir),
        "modified": iso(stat.st_mtime),
        "skill_md_bytes": stat.st_size,
        "words": len(body.split()),
        "headings": headings,
        "extra_frontmatter": {k: v for k, v in fm.items() if k not in known},
        "body_preview": "\n".join(ln for ln in body.split("\n") if ln.strip())[:600],
    }
    rec.update(bundle_stats(skill_dir))
    rec.update(tokens.costs(str(rec["name"]), str(rec["description"]), body))
    rec.update(extra)
    rec.setdefault("invoke", rec["name"])
    return rec


# --------------------------------------------------------------------------
# collectors
# --------------------------------------------------------------------------


def global_dirs(found: list[harnesses.Harness]) -> dict[Path, list[harnesses.Harness]]:
    """Each real skill folder, with the harnesses that read it. Symlinked folders count once."""
    dirs: dict[Path, list[harnesses.Harness]] = {}
    for h in found:
        for d in h.dirs:
            if d.is_dir():
                dirs.setdefault(d.resolve(), []).append(h)
    return dirs


def lock_entries(skills_dir: Path, cache: dict) -> dict:
    """The lock entries kept beside one real skills folder. Atlas links first, so npx wins."""
    if skills_dir not in cache:
        lock = skills_dir.parent / ".skill-lock.json"
        entries: dict = {}
        for path in (lock.with_name(ATLAS_LOCK), lock):
            found = as_dict(read_json(path).get("skills"))
            entries.update({k: v for k, v in found.items() if isinstance(v, dict)})
        cache[skills_dir] = entries
    return cache[skills_dir]


def store_home(roots: dict[str, Path]) -> Path | None:
    """Where installs and deletes happen: ~/.agents, as npx skills uses, else the first root."""
    agents = Path.home() / ".agents"
    if (agents / "skills").is_dir():
        return agents
    return next(iter(roots.values()), None)


def collect_global(
    dirs: dict[Path, list[harnesses.Harness]], store: Path | None, seen: dict
) -> list[dict]:
    out = []
    locks: dict = {}
    for real, readers in dirs.items():
        ids = [h.id for h in readers]
        roots = [
            h.label.removeprefix("Claude Code · ") or "main"
            for h in readers
            if h.switch == "claude"
        ]
        for skill_md in sorted(real.glob("*/SKILL.md")):
            key = str(skill_md.resolve())
            if key in seen:
                seen[key]["harnesses"] += ids
                seen[key]["config_roots"] += roots
                continue
            home = skill_md.resolve().parent.parent
            rec = _record(
                skill_md,
                scope="personal",
                harnesses=list(ids),
                config_roots=list(roots),
                status="enabled",
                source_root=str(real),
                store=home == store,
                origin=lock_entries(home, locks).get(skill_md.parent.name, {}),
            )
            if rec is None:
                continue
            locked = rec["origin"].get("skillFolderHash", "")
            try:
                rec["local_edits"] = bool(locked) and git_tree_hash(skill_md.parent) != locked
            except OSError:
                rec["local_edits"] = False
            seen[key] = rec
            out.append(rec)
    return out


def collect_plugins(host: HostConfig, harness_id: str, seen: dict) -> list[dict]:
    cache = host.root / "plugins" / "cache"
    if not cache.exists():
        return []
    out = []
    for marketplace_dir in sorted(p for p in cache.iterdir() if p.is_dir()):
        for plugin_dir in sorted(p for p in marketplace_dir.iterdir() if p.is_dir()):
            ref = f"{plugin_dir.name}@{marketplace_dir.name}"
            installs = host.plugin_installs(ref)
            live_paths = {i.get("installPath") for i in installs}
            enabled = host.plugin_enabled(ref)
            for version_dir in sorted(p for p in plugin_dir.iterdir() if p.is_dir()):
                is_live = str(version_dir) in live_paths
                install = next(
                    (i for i in installs if i.get("installPath") == str(version_dir)),
                    {},
                )
                if not is_live:
                    status = "stale"
                elif enabled is False:
                    status = "disabled"
                elif enabled is True:
                    status = "enabled"
                else:
                    status = "installed"
                for skill_md in sorted(version_dir.glob("skills/*/SKILL.md")):
                    key = str(skill_md.resolve())
                    if key in seen:
                        seen[key]["config_roots"].append(host.label)
                        seen[key]["harnesses"].append(harness_id)
                        continue
                    rec = _record(
                        skill_md,
                        scope="plugin",
                        config_roots=[host.label],
                        harnesses=[harness_id],
                        status=status,
                        plugin=plugin_dir.name,
                        plugin_ref=ref,
                        marketplace=marketplace_dir.name,
                        marketplace_source=as_dict(host.marketplaces.get(marketplace_dir.name)).get(
                            "source", {}
                        ),
                        plugin_version=version_dir.name,
                        plugin_scope=install.get("scope", ""),
                        plugin_project=install.get("projectPath", ""),
                        installed_at=install.get("installedAt", ""),
                        last_updated=install.get("lastUpdated", ""),
                        commit=(install.get("gitCommitSha") or "")[:7],
                        source_root=str(version_dir),
                    )
                    if rec is None:
                        continue
                    rec["invoke"] = f"{plugin_dir.name}:{rec['name']}"
                    seen[key] = rec
                    out.append(rec)
    return out


def collect_projects(project_roots: list[Path], depth: int, seen: dict) -> list[dict]:
    out = []
    for root in project_roots:
        if not root.exists():
            continue
        candidates: list[Path] = []
        for holder in (".claude", ".agents"):
            for level in range(1, max(depth, 1) + 1):
                candidates += root.glob("/".join(["*"] * level) + f"/{holder}/skills")
        for skills_dir in sorted(set(candidates)):
            holder = skills_dir.parent.name
            if not skills_dir.is_dir():
                continue
            project_dir = skills_dir.parent.parent
            for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
                key = str(skill_md.resolve())
                if key in seen:
                    continue
                rec = _record(
                    skill_md,
                    scope="project",
                    config_roots=[],
                    harnesses=[],
                    status="project-only",
                    project=project_dir.name,
                    project_path=str(project_dir),
                    holder=holder,
                    source_root=str(skills_dir),
                )
                if rec is None:
                    continue
                seen[key] = rec
                out.append(rec)
    return out


# --------------------------------------------------------------------------


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "skill-atlas" / "config.json"


def config_path(repo: Path) -> Path:
    """$SKILL_ATLAS_CONFIG, else the user file, else a config.json next to the code."""
    env = os.environ.get("SKILL_ATLAS_CONFIG")
    if env:
        return Path(env).expanduser()
    user = user_config_path()
    return user if user.exists() else repo / "config.json"


def load_config(repo: Path) -> dict:
    """The config with defaults. Wrong types fall back, and CLAUDE_CONFIG_DIR joins the roots."""
    cfg = read_json(config_path(repo))
    roots = cfg.get("config_roots")
    if not isinstance(roots, dict) or not roots:
        roots = {"main": "~/.claude"}
    roots = {str(k): str(v) for k, v in roots.items() if isinstance(v, str) and v}
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env and Path(env).expanduser().resolve() not in {
        Path(p).expanduser().resolve() for p in roots.values()
    }:
        label = Path(env).expanduser().name.lstrip(".") or "config"
        while label in roots:
            label += "-env"
        roots[label] = env
    projects = cfg.get("project_roots")
    if isinstance(projects, str):
        projects = [projects]
    if not isinstance(projects, list):
        projects = []
    try:
        depth = int(cfg.get("project_scan_depth", 3))
    except (TypeError, ValueError):
        depth = 3
    only = cfg.get("harnesses")
    return {
        **cfg,
        "harnesses": [str(h) for h in only] if isinstance(only, list) else None,
        "config_roots": roots,
        "project_roots": [str(p) for p in projects if isinstance(p, str) and p],
        "project_scan_depth": depth,
    }


# Copies people keep around, not roots Claude Code runs from.
SPARE = re.compile(r"archive|backup|bak|old|stale|copy", re.I)


def detect_roots() -> dict[str, str]:
    """~/.claude, CLAUDE_CONFIG_DIR, and each ~/.claude-<name> that has a settings.json."""
    home = Path.home()
    roots = {"main": "~/.claude"} if (home / ".claude").is_dir() else {}
    for d in sorted(home.glob(".claude-*")):
        if d.is_dir() and (d / "settings.json").is_file() and not SPARE.search(d.name):
            roots[d.name.removeprefix(".claude-")] = "~/" + d.name
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env and env not in roots.values():
        roots.setdefault(Path(env).expanduser().name.lstrip(".") or "config", env)
    return roots or {"main": "~/.claude"}


def write_user_config(force: bool = False) -> Path:
    """Write a starter config with the roots found here. Never replaces a file unasked."""
    path = user_config_path()
    if path.exists() and not force:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = {"config_roots": detect_roots(), "project_roots": [], "project_scan_depth": 3}
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return path


def scan(repo: Path) -> dict:
    cfg = load_config(repo)
    hosts = [
        HostConfig.load(label, Path(os.path.expanduser(p)))
        for label, p in cfg["config_roots"].items()
        if Path(os.path.expanduser(p)).is_dir()
    ]

    found = harnesses.detect({h.label: h.root for h in hosts}, cfg["harnesses"])
    claude_ids = {h.home: h.id for h in found if h.switch == "claude"}
    home = store_home({h.label: h.root for h in hosts})
    store = (home / "skills").resolve() if home else None

    seen: dict = {}
    records: list[dict] = collect_global(global_dirs(found), store, seen)
    for host in hosts:
        if host.root in claude_ids:
            records += collect_plugins(host, claude_ids[host.root], seen)
    records += collect_projects(
        [Path(os.path.expanduser(p)) for p in cfg["project_roots"]],
        int(cfg["project_scan_depth"]),
        seen,
    )

    for r in records:
        r["config_roots"] = sorted(set(r.get("config_roots") or []))
        r["harnesses"] = list(dict.fromkeys(r.get("harnesses") or []))
        r["invocation"] = {
            (False, False): "auto + manual",
            (True, False): "manual only",
            (False, True): "auto only",
            (True, True): "neither",
        }[(r["manual_only"], r["claude_only"])]

    records.sort(key=lambda r: (r["scope"], r["name"].lower()))
    bundled_off = any(h.settings.get("disableBundledSkills") for h in hosts)

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "host": platform.node(),
        "config_roots": {h.label: str(h.root) for h in hosts},
        "bundled_skills_disabled": bundled_off,
        "harnesses": {
            h.id: {**h.view(), "store": any(d.is_dir() and d.resolve() == store for d in h.dirs)}
            for h in found
        },
        "store": str(home) if home else "",
        "settings": {
            h.id: settings_state(h.home) if h.switch == "claude" else harnesses.state(h, records)
            for h in found
        },
        "count": len(records),
        "skills": records,
    }


if __name__ == "__main__":
    repo = Path(__file__).resolve().parent
    json.dump(scan(repo), sys.stdout, indent=2)
    print()
