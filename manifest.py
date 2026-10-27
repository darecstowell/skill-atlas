"""Export a skill set as a JSON manifest, plan an import, and restore skills with no folder."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import harnesses
import updates
from scan import git_tree_hash, skill_lock_path

VERSION = 1
KEY = "skill_atlas_manifest"


def tilde(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path == home or path.startswith(home + "/") else path


def _personal(data: dict) -> dict[str, dict]:
    return {s["dir_name"]: s for s in data["skills"] if s.get("scope") == "personal"}


def _tracked(origin: dict) -> bool:
    return bool(
        origin.get("sourceType") == "github"
        and isinstance(origin.get("source"), str)
        and origin.get("skillPath")
    )


def _off(data: dict, hid: str) -> list[str]:
    st = data["settings"].get(hid) or {}
    if "skillOverrides" in st:
        return sorted(k for k, v in st["skillOverrides"].items() if v == "off")
    return sorted(st.get("off") or [])


def export(data: dict, roots: list[Path]) -> dict:
    """The skill set as a manifest: sources, untracked names, watched repos, and off switches."""
    skills = []
    for name, s in sorted(_personal(data).items()):
        o = s.get("origin") or {}
        item: dict = {"name": name, "dir": tilde(s["dir"])}
        if _tracked(o):
            item.update(source=o["source"], skillPath=o["skillPath"], ref=o.get("ref") or "")
            item["skillFolderHash"] = o.get("skillFolderHash") or ""
        else:
            item["untracked"] = True
        skills.append(item)
    states = {
        hid: {"name": h["label"], "off": _off(data, hid)}
        for hid, h in data["harnesses"].items()
        if h.get("switch")
    }
    return {
        KEY: VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": data.get("host", ""),
        "skills": skills,
        "watched": updates.watched(roots),
        "harness_states": states,
    }


def _check(manifest: dict) -> None:
    v = manifest.get(KEY)
    if not isinstance(v, int):
        raise ValueError("this file is not a Skill Atlas manifest")
    if v > VERSION:
        raise ValueError(f"this manifest is version {v}. Update Skill Atlas to read it")
    if not isinstance(manifest.get("skills"), list):
        raise ValueError("the manifest has no skills list")


def _repo(text) -> str | None:
    try:
        return updates.parse_repo(text) if isinstance(text, str) else None
    except ValueError:
        return None


def _safe(path: str) -> bool:
    return path.endswith("SKILL.md") and not path.startswith("/") and ".." not in path.split("/")


def _local_hash(s: dict) -> str:
    h = (s.get("origin") or {}).get("skillFolderHash")
    if h:
        return h
    try:
        return git_tree_hash(Path(s["dir"]))
    except OSError:
        return ""


def _match_harness(hid: str, local: dict) -> str | None:
    if hid in local:
        return hid
    base = hid.split(":")[0]
    same = [k for k in local if k.split(":")[0] == base]
    return same[0] if len(same) == 1 else None


def plan(manifest: dict, data: dict, roots: list[Path]) -> dict:
    """What an import would do here: installs, skills already present, and settings to apply."""
    _check(manifest)
    local = _personal(data)
    store = skill_lock_path(roots[0]).parent / "skills" if roots else None
    install: list[dict] = []
    same: list[dict] = []
    differ: list[dict] = []
    untracked: list[dict] = []
    for item in manifest["skills"]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"]
        repo, path = _repo(item.get("source")), item.get("skillPath")
        if repo and isinstance(path, str) and _safe(path):
            name = updates.skill_name(repo, path)
        else:
            repo = path = None
        here = local.get(name)
        if here or (store and (store / name).exists()):
            want = item.get("skillFolderHash") or ""
            ours = _local_hash(here) if here else ""
            (same if not want or want == ours else differ).append({"name": name, "source": repo})
        elif repo and path:
            install.append({"name": name, "repo": repo, "path": path})
        else:
            untracked.append({"name": name})

    switchable = {k: h for k, h in data["harnesses"].items() if h.get("switch")}
    coming = {i["name"] for i in install}
    harness, skipped = [], []
    states = manifest.get("harness_states")
    for hid, st in (states if isinstance(states, dict) else {}).items():
        off = [str(n) for n in (st.get("off") if isinstance(st, dict) else None) or []]
        if not off:
            continue
        mine = _match_harness(str(hid), switchable)
        if mine is None:
            skipped.append({"harness": hid, "name": str((st or {}).get("name") or hid)})
            continue
        now = set(_off(data, mine))
        loaded = {s["name"] for s in data["skills"] if mine in s.get("harnesses", [])}
        names = sorted(n for n in set(off) - now if n in loaded or n in coming)
        if names:
            harness.append({"harness": mine, "name": switchable[mine]["label"], "off": names})

    watched = manifest.get("watched")
    found = {_repo(r) for r in (watched if isinstance(watched, list) else [])}
    watch = sorted(r for r in found if r and r not in updates.watched(roots))
    return {
        "install": install,
        "same": same,
        "differ": differ,
        "untracked": untracked,
        "harness": harness,
        "skipped": skipped,
        "watch": watch,
    }


def missing(roots: list[Path]) -> dict:
    """Lock entries in the skill store whose folder is gone, as an import plan."""
    out: dict = {
        k: [] for k in ("install", "same", "differ", "untracked", "harness", "skipped", "watch")
    }
    if not roots:
        return out
    lock = skill_lock_path(roots[0])
    skills_dir = lock.parent / "skills"
    for name, (path, e) in sorted(updates.tracked(roots).items()):
        if path.parent != lock.parent or (skills_dir / name).exists():
            continue
        if updates.skill_name(e["source"], e["skillPath"]) == name:
            out["install"].append({"name": name, "repo": e["source"], "path": e["skillPath"]})
        else:
            out["untracked"].append({"name": name})
    return out


def start_install(items: list[dict], roots: list[Path]) -> dict:
    """One background job that installs from several repos, through the update job runner."""
    by_repo: dict[str, list[str]] = {}
    for i in items:
        by_repo.setdefault(i["repo"], []).append(i["path"])
    if len(by_repo) == 1:
        repo, paths = next(iter(by_repo.items()))
        return updates.start_install(repo, paths, roots)

    def run(job: dict, roots: list[Path]) -> None:
        try:
            for repo, paths in by_repo.items():
                updates._install_source(repo, paths, job, roots)
        finally:
            updates._cache.clear()
            job["seconds"] = round(time.time() - job["started"], 1)
            job["done"] = True

    names = [updates.skill_name(r, p) for r, ps in by_repo.items() for p in ps]
    return updates._start_job(names, run, roots)


def apply(
    full: dict,
    pick: dict,
    data: dict,
    roots: list[Path],
    found: list[harnesses.Harness],
    write_setting,
) -> dict:
    """Run the parts of a plan the user kept: watches and switches now, installs as a job."""
    want = {k: set(map(str, pick.get(k) or [])) for k in ("install", "harness", "watch")}
    items = [i for i in full["install"] if i["name"] in want["install"]]
    errors: list[str] = []
    watched = 0
    for repo in full["watch"]:
        if repo in want["watch"]:
            try:
                updates.watch(repo, True, roots)
                watched += 1
            except ValueError as e:
                errors.append(str(e))
    by_id = {h.id: h for h in found}
    store = skill_lock_path(roots[0]).parent / "skills"
    switched = 0
    for st in full["harness"]:
        h = by_id.get(st["harness"])
        if h is None or st["harness"] not in want["harness"]:
            continue
        try:
            if h.switch == "claude":
                write_setting(h.home, "skill", st["off"], False)
            else:
                known = {s["name"]: s for s in data["skills"] if h.id in s.get("harnesses", [])}
                recs = [
                    known.get(n) or {"name": n, "path": str(store / n / "SKILL.md")}
                    for n in st["off"]
                ]
                harnesses.set_skills(h, recs, False)
            switched += len(st["off"])
        except (ValueError, OSError, NotImplementedError) as e:
            errors.append(f"{h.name}: {e}")
    job = updates.job_view(start_install(items, roots)) if items else None
    return {"job": job, "watched": watched, "switched": switched, "errors": errors}
