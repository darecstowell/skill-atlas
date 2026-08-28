"""Scan every place Claude Code loads skills from and emit one record per skill."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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
    lines = text.split("\n")
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
            items = [l.strip()[2:].strip() for l in child_lines if l.strip().startswith("- ")]
            if items:
                data[key] = [_unquote(v) for v in items]
            else:
                child: dict = {}
                for l in child_lines:
                    cm = SCALAR_KEY.match(l.strip())
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


# --------------------------------------------------------------------------
# host config
# --------------------------------------------------------------------------


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


@dataclass
class HostConfig:
    """Everything read out of one ~/.claude-style config root."""

    label: str
    root: Path
    settings: dict = field(default_factory=dict)
    installed_plugins: dict = field(default_factory=dict)
    marketplaces: dict = field(default_factory=dict)

    @classmethod
    def load(cls, label: str, root: Path) -> "HostConfig":
        return cls(
            label=label,
            root=root,
            settings=read_json(root / "settings.json"),
            installed_plugins=read_json(root / "plugins" / "installed_plugins.json").get("plugins", {}),
            marketplaces=read_json(root / "plugins" / "known_marketplaces.json"),
        )

    def plugin_enabled(self, ref: str):
        return self.settings.get("enabledPlugins", {}).get(ref)

    def plugin_installs(self, ref: str) -> list[dict]:
        return self.installed_plugins.get(ref, [])


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# skill record
# --------------------------------------------------------------------------


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


def build_record(skill_md: Path, *, scope: str, **extra) -> dict:
    text = skill_md.read_text(errors="replace")
    fm, body = parse_frontmatter(text)
    skill_dir = skill_md.parent
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}

    known = {
        "name", "description", "metadata", "license", "allowed-tools", "argument-hint",
        "references", "inputs", "version", "model", "compatibility", "disable-model-invocation",
    }
    stat = skill_md.stat()
    headings = len(re.findall(r"^##+ ", body, re.M))

    rec = {
        "name": str(fm.get("name") or skill_dir.name),
        "dir_name": skill_dir.name,
        "description": re.sub(r"\s+", " ", str(fm.get("description", ""))).strip(),
        "scope": scope,
        "manual_only": str(fm.get("disable-model-invocation", "")).lower() == "true",
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
        "body_preview": "\n".join(l for l in body.split("\n") if l.strip())[:600],
    }
    rec.update(bundle_stats(skill_dir))
    rec.update(extra)
    rec.setdefault("invoke", rec["name"])
    return rec


# --------------------------------------------------------------------------
# collectors
# --------------------------------------------------------------------------


def collect_personal(host: HostConfig, lock_index: dict, seen: dict) -> list[dict]:
    root = host.root / "skills"
    if not root.exists():
        return []
    real = root.resolve()
    out = []
    for skill_md in sorted(real.glob("*/SKILL.md")):
        key = str(skill_md.resolve())
        if key in seen:
            seen[key]["config_roots"].append(host.label)
            continue
        rec = build_record(
            skill_md,
            scope="personal",
            config_roots=[host.label],
            status="enabled",
            source_root=str(real),
            origin=lock_index.get(skill_md.parent.name, {}),
        )
        seen[key] = rec
        out.append(rec)
    return out


def collect_plugins(host: HostConfig, seen: dict) -> list[dict]:
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
                install = next((i for i in installs if i.get("installPath") == str(version_dir)), {})
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
                        continue
                    rec = build_record(
                        skill_md,
                        scope="plugin",
                        config_roots=[host.label],
                        status=status,
                        plugin=plugin_dir.name,
                        plugin_ref=ref,
                        marketplace=marketplace_dir.name,
                        marketplace_source=(host.marketplaces.get(marketplace_dir.name) or {}).get("source", {}),
                        plugin_version=version_dir.name,
                        plugin_scope=install.get("scope", ""),
                        plugin_project=install.get("projectPath", ""),
                        installed_at=install.get("installedAt", ""),
                        last_updated=install.get("lastUpdated", ""),
                        commit=(install.get("gitCommitSha") or "")[:7],
                        source_root=str(version_dir),
                    )
                    rec["invoke"] = f"{plugin_dir.name}:{rec['name']}"
                    seen[key] = rec
                    out.append(rec)
    return out


def collect_projects(project_roots: list[Path], depth: int, seen: dict) -> list[dict]:
    out = []
    for root in project_roots:
        if not root.exists():
            continue
        candidates = []
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
                    rec = build_record(
                        skill_md,
                        scope="project",
                        config_roots=[],
                        status="project-only",
                        project=project_dir.name,
                        project_path=str(project_dir),
                        holder=holder,
                        source_root=str(skills_dir),
                    )
                    seen[key] = rec
                    out.append(rec)
    return out


# --------------------------------------------------------------------------


def load_config(repo: Path) -> dict:
    cfg = read_json(repo / "config.json")
    cfg.setdefault("config_roots", {"personal": "~/.claude"})
    cfg.setdefault("project_roots", [])
    cfg.setdefault("project_scan_depth", 3)
    return cfg


def scan(repo: Path) -> dict:
    cfg = load_config(repo)
    hosts = [
        HostConfig.load(label, Path(os.path.expanduser(p)))
        for label, p in cfg["config_roots"].items()
        if Path(os.path.expanduser(p)).exists()
    ]

    lock_index: dict = {}
    for host in hosts:
        skills_dir = host.root / "skills"
        if skills_dir.exists():
            lock = read_json(skills_dir.resolve().parent / ".skill-lock.json").get("skills", {})
            lock_index.update(lock)

    seen: dict = {}
    records: list[dict] = []
    for host in hosts:
        records += collect_personal(host, lock_index, seen)
        records += collect_plugins(host, seen)
    records += collect_projects(
        [Path(os.path.expanduser(p)) for p in cfg["project_roots"]],
        int(cfg["project_scan_depth"]),
        seen,
    )

    for r in records:
        r["config_roots"] = sorted(set(r.get("config_roots") or []))
        r["invocation"] = "manual only" if r["manual_only"] else "auto + manual"

    records.sort(key=lambda r: (r["scope"], r["name"].lower()))
    bundled_off = any(h.settings.get("disableBundledSkills") for h in hosts)

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "host": os.uname().nodename,
        "config_roots": {h.label: str(h.root) for h in hosts},
        "bundled_skills_disabled": bundled_off,
        "count": len(records),
        "skills": records,
    }


if __name__ == "__main__":
    repo = Path(__file__).resolve().parent
    json.dump(scan(repo), sys.stdout, indent=2)
    print()
