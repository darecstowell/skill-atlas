"""Avatars, social previews, and image paths for source repos, cached for an hour."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from updates import fetch_tree

CACHE_SECONDS = 3600
MAX_IMAGES = 200
IMAGE = re.compile(r"\.(png|jpe?g|gif|webp|avif)$", re.I)
# Folders that hold test data or vendored code, never a picture of the skill.
SKIP = {"node_modules", "vendor", "test", "tests", "testdata", "fixtures", "sponsors"}
_cache: dict[str, tuple[float, dict]] = {}


def images(tree: dict) -> list[str]:
    out = [
        e["path"]
        for e in tree["tree"]
        if e["type"] == "blob"
        and IMAGE.search(e["path"])
        and not SKIP & {p.lower() for p in e["path"].split("/")[:-1]}
    ]
    return out[:MAX_IMAGES]


def _meta(repos: list[str]) -> dict[str, dict]:
    """One GraphQL call for every repo. A missing repo leaves a gap, not a failure."""
    fields = (
        "openGraphImageUrl usesCustomOpenGraphImage description stargazerCount owner { avatarUrl }"
    )
    parts = []
    for i, repo in enumerate(repos):
        owner, name = repo.split("/", 1)
        parts.append(
            f"r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ {fields} }}"
        )
    try:
        # gh exits non-zero when one repo is missing, but stdout still has the rest.
        out = subprocess.run(
            ["gh", "api", "graphql", "-f", "query={" + " ".join(parts) + "}"],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "GH_PROMPT_DISABLED": "1"},
        ).stdout
        data = (json.loads(out) if out else {}).get("data") or {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    meta = {}
    for i, repo in enumerate(repos):
        r = data.get(f"r{i}")
        if r:
            meta[repo] = {
                "avatar": r["owner"]["avatarUrl"],
                "banner": r["openGraphImageUrl"],
                "custom_banner": r["usesCustomOpenGraphImage"],
                "description": r["description"] or "",
                "stars": r["stargazerCount"],
            }
    return meta


def fetch(repos: list[str]) -> dict[str, dict]:
    now = time.time()
    stale = [r for r in repos if r not in _cache or now - _cache[r][0] > CACHE_SECONDS]
    if stale:
        meta = _meta(stale)
        with ThreadPoolExecutor(max_workers=8) as pool:
            trees = list(pool.map(lambda r: fetch_tree(r, "HEAD"), stale))
        for repo, tree in zip(stale, trees, strict=True):
            _cache[repo] = (now, {**meta.get(repo, {}), "images": images(tree) if tree else []})
    return {r: _cache[r][1] for r in repos}
