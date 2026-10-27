"""Check GitHub-sourced skills for updates and install them, one tarball per repo."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import history
from scan import (
    ATLAS_LOCK,
    as_dict,
    git_tree_hash,
    parse_frontmatter,
    read_json,
    read_json_strict,
    skill_lock_path,
)

CACHE_SECONDS = 600
TREE_TIMEOUT = 20
_cache: dict = {}
_tarballs: dict[tuple[str, str], tuple[float, bytes]] = {}
JOBS: dict[str, dict] = {}
_job_lock = threading.Lock()
# Why the last GitHub call in this thread failed, so errors can say more than "could not read".
_net = threading.local()
_why: dict[str, str] = {}


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------


def parse_repo(text: str) -> str:
    """owner/repo from a GitHub URL or an owner/repo string."""
    m = re.match(
        r"^(?:https?://github\.com/|git@github\.com:)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$",
        text.strip(),
    )
    if not m:
        raise ValueError(f"not a GitHub repo: {text!r}")
    return f"{m.group(1)}/{m.group(2)}"


def _gh(args: list[str], binary: bool = False, timeout: int = 60):
    _net.timed_out = False
    if not shutil.which("gh"):
        return None
    try:
        out = subprocess.run(
            ["gh", "api", *args],
            capture_output=True,
            timeout=timeout,
            text=not binary,
            env={**os.environ, "GH_PROMPT_DISABLED": "1"},
        )
    except subprocess.TimeoutExpired:
        _net.timed_out = True
        return None
    except OSError:
        return None
    return out.stdout if out.returncode == 0 else None


def _reason(err: OSError) -> str:
    if isinstance(err, urllib.error.HTTPError):
        if err.code in (403, 429) and err.headers.get("X-RateLimit-Remaining") == "0":
            return "GitHub rate limit reached. Run `gh auth login` to raise it"
        if err.code == 404:
            return "not found. A private repo needs `gh auth login`"
        return f"GitHub answered {err.code}"
    cause = getattr(err, "reason", err)
    if isinstance(cause, ssl.SSLCertVerificationError):
        return "Python cannot check GitHub's certificate. Install your Python's certificates"
    if isinstance(cause, (socket.timeout, TimeoutError)):
        return "GitHub did not answer in time"
    return "no connection to GitHub"


def _https(url: str, timeout: int = 30) -> bytes | None:
    _net.reason = ""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "skill-atlas", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.read()
    except OSError as e:
        _net.reason = _reason(e)
        return None


def fetch_tree(repo: str, ref: str) -> dict | None:
    # gh first: it is signed in, so the 60-an-hour anonymous API limit does not apply.
    out = _gh([f"repos/{repo}/git/trees/{ref}?recursive=1"], timeout=TREE_TIMEOUT)
    if out is None and _net.timed_out:
        # The network is the problem, so HTTPS would only wait again.
        _why[repo] = "GitHub did not answer in time"
        return None
    if out is None:
        url = f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
        raw = _https(url, timeout=TREE_TIMEOUT)
        if raw is None:
            _why[repo] = _net.reason
        out = raw.decode("utf-8", "replace") if raw else None
    try:
        tree = json.loads(out) if out else None
    except ValueError:
        tree = None
    if isinstance(tree, dict) and isinstance(tree.get("tree"), list):
        _why.pop(repo, None)
        return tree
    return None


def tree_error(repo: str) -> str:
    """A message for a repo whose tree could not be read."""
    why = _why.get(repo)
    return f"could not read {repo} from GitHub" + (f": {why}" if why else "")


def fetch_tarball(repo: str, ref: str, max_age: float = 0) -> bytes | None:
    cached = _tarballs.get((repo, ref))
    if cached and time.time() - cached[0] < max_age:
        return cached[1]
    # codeload is not rate limited; gh covers private repos.
    blob = _https(f"https://codeload.github.com/{repo}/tar.gz/{ref}", timeout=120) or _gh(
        [f"repos/{repo}/tarball/{ref}"], binary=True
    )
    if blob:
        _tarballs[(repo, ref)] = (time.time(), blob)
    return blob


def cached_tarball(repo: str, ref: str) -> bytes:
    """The repo's tarball, at most CACHE_SECONDS old. Raises ValueError with the reason."""
    blob = fetch_tarball(repo, ref, max_age=CACHE_SECONDS)
    if not blob:
        why = getattr(_net, "reason", "")
        raise ValueError(f"could not download {repo}" + (f": {why}" if why else ""))
    return blob


def clear_cache() -> None:
    """Forget the last check, after a change to the skills or the locks."""
    _cache.clear()


def folder_of(skill_path: str) -> str:
    return skill_path.rsplit("/", 1)[0] if "/" in skill_path else ""


def folder_sha(tree: dict, skill_path: str) -> str | None:
    folder = folder_of(skill_path)
    if not folder:
        return tree.get("sha")
    return next(
        (e["sha"] for e in tree["tree"] if e["type"] == "tree" and e["path"] == folder),
        None,
    )


# --------------------------------------------------------------------------
# locks: the npx `skills` lock, plus the atlas's own lock for skills linked here
# --------------------------------------------------------------------------


def from_github(e: dict) -> bool:
    """A lock entry that names a GitHub repo and a SKILL.md path in it."""
    return bool(
        e.get("sourceType") == "github" and isinstance(e.get("source"), str) and e.get("skillPath")
    )


def safe_skill_path(path: str) -> bool:
    """A SKILL.md path inside a repo, with no way out of it."""
    return path.endswith("SKILL.md") and not path.startswith("/") and ".." not in path.split("/")


def tracked(roots: list[Path]) -> dict[str, tuple[Path, dict]]:
    """Every checkable skill: name -> (lock file, entry). The npx lock wins over the atlas lock."""
    out: dict[str, tuple[Path, dict]] = {}
    for npx_lock in {skill_lock_path(r) for r in roots}:
        for lock in (npx_lock.with_name(ATLAS_LOCK), npx_lock):
            for name, e in as_dict(read_json(lock).get("skills")).items():
                if isinstance(e, dict) and from_github(e) and e.get("skillFolderHash"):
                    out[name] = (lock, e)
    return out


def write_json(path: Path, data: dict) -> None:
    path = path.resolve()  # write through a symlink, so a linked lock stays linked
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".atlas-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_lock(lock: Path) -> dict:
    data = read_json_strict(lock) or {"version": 1}
    data["skills"] = as_dict(data.get("skills"))
    return data


def write_lock_entries(lock: Path, entries: dict[str, dict]) -> None:
    data = _read_lock(lock)
    data["skills"].update(entries)
    write_json(lock, data)


def _atlas_lock(roots: list[Path]) -> Path:
    if not roots:
        raise ValueError("no Claude config folder found. Set config_roots in config.json")
    return skill_lock_path(roots[0]).with_name(ATLAS_LOCK)


def _edit_atlas_lock(roots: list[Path], change) -> None:
    lock = _atlas_lock(roots)
    data = _read_lock(lock)
    change(data)
    write_json(lock, data)


def mark_seen(roots: list[Path], repo: str, paths: list[str]) -> None:
    def change(data):
        seen = data["seen"] = as_dict(data.get("seen"))
        seen[repo] = sorted(set(seen.get(repo) or []) | set(paths))

    _edit_atlas_lock(roots, change)


def watched(roots: list[Path]) -> list[str]:
    """Repos you follow for new skills even when none of their skills is installed."""
    if not roots:
        return []
    sources = read_json(_atlas_lock(roots)).get("sources")
    return [s for s in sources if isinstance(s, str)] if isinstance(sources, list) else []


def watch(repo_text: str, on: bool, roots: list[Path]) -> dict:
    repo = parse_repo(repo_text)
    if on and not fetch_tree(repo, "HEAD"):
        raise ValueError(tree_error(repo))

    def change(data):
        sources = set(watched(roots))
        sources.add(repo) if on else sources.discard(repo)
        data["sources"] = sorted(sources)

    _edit_atlas_lock(roots, change)
    _cache.clear()
    return {"repo": repo, "watched": watched(roots)}


def skill_paths(tree: dict) -> list[str]:
    return [
        e["path"]
        for e in tree["tree"]
        if e["type"] == "blob" and e["path"].rsplit("/", 1)[-1] == "SKILL.md"
    ]


def skill_name(repo: str, path: str) -> str:
    folder = folder_of(path)
    return folder.rsplit("/", 1)[-1] if folder else repo.split("/", 1)[1]


def _available(
    repo: str,
    tree: dict,
    entries: dict[str, dict],
    local: set[str],
    seen: dict,
    roots: list[Path],
) -> list[dict]:
    """Skills in the repo that are not installed. The first look only records a baseline."""
    paths = skill_paths(tree)
    if repo not in seen:
        mark_seen(roots, repo, paths)
        seen[repo] = paths
    installed_paths = {e["skillPath"] for e in entries.values()}
    installed_names = set(entries)
    out = []
    for path in paths:
        if path in installed_paths:
            continue
        name = skill_name(repo, path)
        out.append(
            {
                "name": name,
                "path": path,
                "new": path not in seen[repo],
                # Same name from this repo: the skill moved upstream. Else a clash.
                "taken": "moved" if name in installed_names else "taken" if name in local else "",
            }
        )
    return sorted(out, key=lambda a: (not a["new"], a["name"]))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------


def check(roots: list[Path], refresh: bool = False) -> dict:
    """Status per skill name: current, outdated, or unknown (not found upstream)."""
    if not refresh and _cache and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]

    by_source: dict[tuple[str, str], dict[str, dict]] = {}
    for name, (_, e) in tracked(roots).items():
        by_source.setdefault((e["source"], e.get("ref") or "HEAD"), {})[name] = e
    tracked_repos = {repo for repo, _ in by_source}
    for repo in watched(roots):
        if repo not in tracked_repos:
            by_source[(repo, "HEAD")] = {}

    statuses, errors, available = {}, {}, {}
    local = {
        p.name
        for r in roots
        for p in (skill_lock_path(r).parent / "skills").glob("*")
        if p.is_dir()
    }
    seen = as_dict(read_json(_atlas_lock(roots)).get("seen")) if roots else {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        trees = dict(zip(by_source, pool.map(lambda key: fetch_tree(*key), by_source), strict=True))
    for (repo, ref), tree in trees.items():
        if not tree:
            # No status at all, so a failed check never reads as "removed upstream".
            errors[repo] = tree_error(repo)
            continue
        for name, e in by_source[(repo, ref)].items():
            latest = folder_sha(tree, e["skillPath"])
            statuses[name] = (
                "unknown"
                if latest is None
                else "current"
                if latest == e["skillFolderHash"]
                else "outdated"
            )
        found = _available(repo, tree, by_source[(repo, ref)], local, seen, roots)
        if found or not by_source[(repo, ref)]:
            available[repo] = found

    data = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "skills": statuses,
        "errors": errors,
        "available": available,
        "watched": watched(roots),
    }
    _cache.update(at=time.time(), data=data)
    return data


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------


def folder_members(tar: tarfile.TarFile, folder: str) -> Iterator[tuple[str, tarfile.TarInfo]]:
    """Each member of one folder in a GitHub tarball, whose top folder is owner-repo-sha/."""
    for m in tar.getmembers():
        parts = m.name.split("/", 1)
        if len(parts) < 2:
            continue
        rel = parts[1]
        if folder:
            if not rel.startswith(folder + "/"):
                continue
            rel = rel[len(folder) + 1 :]
        if rel and not rel.startswith("/") and ".." not in rel.split("/"):
            yield rel, m


def _extract(tar: tarfile.TarFile, folder: str, dest: Path) -> None:
    for rel, m in folder_members(tar, folder):
        target = dest / rel
        if m.isdir():
            target.mkdir(parents=True, exist_ok=True)
        elif m.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(member_bytes(tar, m))
            target.chmod(0o755 if m.mode & 0o111 else 0o644)


def member_bytes(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    f = tar.extractfile(member)
    return f.read() if f else b""


def swap_in(skill_dir: Path, staged: Path) -> None:
    """Replace a skill folder with a staged one in two renames."""
    old = skill_dir.with_name(f".atlas-old-{skill_dir.name}")
    shutil.rmtree(old, ignore_errors=True)
    if skill_dir.exists():
        os.rename(skill_dir, old)
    os.rename(staged, skill_dir)
    shutil.rmtree(old, ignore_errors=True)


def _update_source(repo: str, ref: str, names: list[str], job: dict, all_tracked: dict) -> None:
    items = job["items"]
    for n in names:
        items[n] = {"state": "downloading"}
    tree = fetch_tree(repo, ref)
    blob = fetch_tarball(repo, ref) if tree else None
    if not tree or not blob:
        for n in names:
            items[n] = {"state": "failed", "error": f"could not download {repo}"}
        return
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for n in names:
            lock, e = all_tracked[n]
            latest = folder_sha(tree, e["skillPath"])
            if latest is None:
                items[n] = {"state": "failed", "error": "folder not found upstream"}
                continue
            items[n] = {"state": "installing"}
            skills_dir = lock.parent / "skills"
            staged = skills_dir / f".atlas-new-{n}"
            shutil.rmtree(staged, ignore_errors=True)
            try:
                _extract(tar, folder_of(e["skillPath"]), staged)
                if not (staged / "SKILL.md").exists():
                    raise ValueError("no SKILL.md in the download")
                history.snapshot(skills_dir / n, n, lock, e)
                swap_in(skills_dir / n, staged)
                with job["lock"]:
                    write_lock_entries(
                        lock,
                        {n: {**e, "skillFolderHash": latest, "updatedAt": now_iso()}},
                    )
                items[n] = {"state": "done"}
            except (OSError, ValueError, tarfile.TarError) as err:
                shutil.rmtree(staged, ignore_errors=True)
                items[n] = {"state": "failed", "error": str(err)}


def _run_job(job: dict, roots: list[Path]) -> None:
    all_tracked = tracked(roots)
    by_source: dict[tuple[str, str], list[str]] = {}
    for name in job["items"]:
        if name not in all_tracked:
            job["items"][name] = {
                "state": "failed",
                "error": "not linked to a GitHub repo",
            }
            continue
        e = all_tracked[name][1]
        by_source.setdefault((e["source"], e.get("ref") or "HEAD"), []).append(name)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for (repo, ref), names in by_source.items():
            pool.submit(_update_source, repo, ref, names, job, all_tracked)


def start_update(names: list[str], roots: list[Path]) -> dict:
    """Start a background update job. Only one job runs at a time."""
    return _start_job(names, _run_job, roots)


def job_running() -> bool:
    return any(not j["done"] for j in JOBS.values())


def _start_job(
    names: list[str], work: Callable[[dict, list[Path]], None], roots: list[Path]
) -> dict:
    def run() -> None:
        try:
            work(job, roots)
        finally:
            _cache.clear()
            job["seconds"] = round(time.time() - job["started"], 1)
            job["done"] = True

    with _job_lock:
        if job_running():
            raise RuntimeError("another update is still running")
        job: dict = {
            "id": uuid.uuid4().hex[:12],
            "done": False,
            "started": time.time(),
            "lock": threading.Lock(),
            "items": {n: {"state": "queued"} for n in names},
        }
        JOBS.clear()
        JOBS[job["id"]] = job
    threading.Thread(target=run, daemon=True).start()
    return job


def job_view(job: dict) -> dict:
    return {k: v for k, v in job.items() if k != "lock"}


# --------------------------------------------------------------------------
# skills a source offers that are not installed
# --------------------------------------------------------------------------


def _repo_ref(repo: str, roots: list[Path]) -> str:
    return next(
        (e.get("ref") or "HEAD" for _, e in tracked(roots).values() if e["source"] == repo),
        "HEAD",
    )


def describe(repo: str, paths: list[str], roots: list[Path]) -> dict:
    """Name and description for each path, read from one tarball (cached for 10 minutes)."""
    blob = cached_tarball(repo, _repo_ref(repo, roots))
    wanted = set(paths)
    out = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for m in tar.getmembers():
            rel = m.name.split("/", 1)[1] if "/" in m.name else ""
            if rel in wanted and m.isfile():
                fm, _ = parse_frontmatter(member_bytes(tar, m).decode("utf-8", "replace"))
                out[rel] = {
                    "name": str(fm.get("name") or skill_name(repo, rel)),
                    "description": re.sub(r"\s+", " ", str(fm.get("description", ""))).strip(),
                }
    return {"repo": repo, "skills": out}


def dismiss(repo: str, paths: list[str], roots: list[Path]) -> dict:
    mark_seen(roots, repo, paths)
    _cache.clear()
    return {"repo": repo, "dismissed": len(paths)}


def _install_source(repo: str, paths: list[str], job: dict, roots: list[Path]) -> None:
    items = job["items"]
    names = {p: skill_name(repo, p) for p in paths}
    for n in names.values():
        items[n] = {"state": "downloading"}
    ref = _repo_ref(repo, roots)
    tree = fetch_tree(repo, ref)
    blob = fetch_tarball(repo, ref) if tree else None
    if not tree or not blob:
        for n in names.values():
            items[n] = {"state": "failed", "error": f"could not download {repo}"}
        return
    npx_lock = skill_lock_path(roots[0])
    skills_dir = npx_lock.parent / "skills"
    # Record new skills in the same lock as their siblings, so `npx skills` sees them too.
    siblings = [(lock, e) for lock, e in tracked(roots).values() if e["source"] == repo]
    lock = siblings[0][0] if siblings else npx_lock.with_name(ATLAS_LOCK)
    extra = {k: siblings[0][1][k] for k in ("ref",) if siblings and k in siblings[0][1]}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for path, n in names.items():
            sha = folder_sha(tree, path)
            if sha is None:
                items[n] = {"state": "failed", "error": "folder not found upstream"}
                continue
            if (skills_dir / n).exists():
                items[n] = {
                    "state": "failed",
                    "error": f"a skill named {n} is already installed",
                }
                continue
            items[n] = {"state": "installing"}
            staged = skills_dir / f".atlas-new-{n}"
            shutil.rmtree(staged, ignore_errors=True)
            try:
                _extract(tar, folder_of(path), staged)
                if not (staged / "SKILL.md").exists():
                    raise ValueError("no SKILL.md in the download")
                os.rename(staged, skills_dir / n)
                stamp = now_iso()
                entry = {
                    "source": repo,
                    "sourceType": "github",
                    "sourceUrl": f"https://github.com/{repo}.git",
                    "skillPath": path,
                    "skillFolderHash": sha,
                    "installedAt": stamp,
                    "updatedAt": stamp,
                    **extra,
                }
                with job["lock"]:
                    write_lock_entries(lock, {n: entry})
                items[n] = {"state": "done"}
            except (OSError, ValueError, tarfile.TarError) as err:
                shutil.rmtree(staged, ignore_errors=True)
                items[n] = {"state": "failed", "error": str(err)}
    with job["lock"]:
        mark_seen(roots, repo, paths)


def start_install(sources: dict[str, list[str]], roots: list[Path]) -> dict:
    """Install skills from source repos, {repo: [SKILL.md path]}, as one background job."""

    def run(job: dict, roots: list[Path]) -> None:
        for repo, paths in sources.items():
            _install_source(repo, paths, job, roots)

    names = [skill_name(repo, p) for repo, paths in sources.items() for p in paths]
    return _start_job(names, run, roots)


# --------------------------------------------------------------------------
# link an untracked skill to a GitHub repo
# --------------------------------------------------------------------------


def link(names: list[str], repo_text: str, roots: list[Path]) -> dict:
    """Find each skill's folder in the repo by name and record it in the atlas lock."""
    repo = parse_repo(repo_text)
    npx_lock = skill_lock_path(roots[0])
    skills_dir = npx_lock.parent / "skills"
    tree = fetch_tree(repo, "HEAD")
    if not tree:
        raise ValueError(tree_error(repo))
    skill_mds = skill_paths(tree)

    linked, missing = {}, []
    for name in names:
        matches = sorted((p for p in skill_mds if folder_of(p).rsplit("/", 1)[-1] == name), key=len)
        if not matches:
            missing.append(name)
            continue
        stamp = now_iso()
        linked[name] = {
            "source": repo,
            "sourceType": "github",
            "sourceUrl": f"https://github.com/{repo}.git",
            "skillPath": matches[0],
            # The local folder's hash, so the first check shows whether upstream differs.
            "skillFolderHash": git_tree_hash(skills_dir / name),
            "installedAt": stamp,
            "updatedAt": stamp,
        }
    if linked:
        write_lock_entries(npx_lock.with_name(ATLAS_LOCK), linked)
        _cache.clear()
    return {"repo": repo, "linked": sorted(linked), "missing": missing}
