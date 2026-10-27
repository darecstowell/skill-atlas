"""Find skills an agent may confuse: similar descriptions, and same-name copies that differ."""

from __future__ import annotations

import difflib
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import scan

# On ~400 real skills, pairs at 0.36+ do one job (to-prd, to-spec); most under it share a topic.
THRESHOLD = 0.36
LIMIT = 5
MAX_DIFF_LINES = 4000

_STOP = """a about after all also an and any are as at be been before but by can do does for from
    has have help how i if in into is it its may more most must need needs no not of on one only
    or other our out over same should so some such than that the their them then there these they
    this those through to too up us use used uses using via want wants was we what when where which
    while who why will with without you your
    agent agents ask asks asked claude user users skill skills mention mentions mentioned
    trigger triggers triggered e g eg etc like something whenever always never even"""
STOPWORDS = frozenset(_STOP.split())
WORD = re.compile(r"[a-z][a-z0-9]+")


def tokens(text: str) -> list[str]:
    """Content words, lowercased, with stopwords dropped and a plain plural -s cut."""
    out = []
    for w in WORD.findall(text.lower()):
        if w in STOPWORDS:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def vectors(texts: list[str]) -> list[dict[str, float]]:
    """Unit-length TF-IDF vectors. Rare words weigh more, so shared boilerplate counts little."""
    docs = [Counter(tokens(t)) for t in texts]
    df: Counter = Counter()
    for d in docs:
        df.update(d.keys())
    n = len(docs)
    out = []
    for d in docs:
        v = {w: (1 + math.log(c)) * (1 + math.log((1 + n) / (1 + df[w]))) for w, c in d.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        out.append({w: x / norm for w, x in v.items()})
    return out


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


def _candidates(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("harnesses") and r.get("status") != "stale"]


def similar(records: list[dict]) -> dict[str, list[dict]]:
    """Per skill path, up to LIMIT other skills (one per name) whose descriptions overlap a lot."""
    live = [r for r in _candidates(records) if r.get("description")]
    vecs = vectors([f"{r['name'].replace('-', ' ')} {r['description']}" for r in live])
    sets = [set(r["harnesses"]) for r in live]
    best: dict[str, dict[str, dict]] = defaultdict(dict)
    for i, a in enumerate(live):
        for j in range(i + 1, len(live)):
            b = live[j]
            if a["name"] == b["name"] or a["description"] == b["description"]:
                continue
            if not sets[i] & sets[j]:
                continue
            score = cosine(vecs[i], vecs[j])
            if score < THRESHOLD:
                continue
            for me, other in ((a, b), (b, a)):
                seen = best[me["path"]].get(other["name"])
                if seen is None or score > seen["score"]:
                    best[me["path"]][other["name"]] = {
                        "path": other["path"],
                        "name": other["name"],
                        "score": round(score, 3),
                    }
    return {
        p: sorted(found.values(), key=lambda x: (-x["score"], x["name"]))[:LIMIT]
        for p, found in best.items()
    }


def _tree(path: str, cache: dict) -> str:
    """The folder's git tree hash without SKILL.md, so it shows if the other files differ."""
    if path not in cache:
        try:
            cache[path] = scan.git_tree_hash(Path(path), skip=("SKILL.md",))
        except OSError:
            cache[path] = ""
    return cache[path]


def diverged(records: list[dict]) -> dict[str, list[dict]]:
    """Per skill path, the other copies with the same name whose SKILL.md text is different."""
    by_name: dict[str, list[dict]] = defaultdict(list)
    for r in _candidates(records):
        by_name[r["name"]].append(r)
    texts: dict[str, str] = {}
    mtimes: dict[str, float] = {}
    trees: dict[str, str] = {}
    out: dict[str, list[dict]] = {}
    for group in by_name.values():
        if len({r["dir"] for r in group}) < 2:
            continue
        for r in group:
            try:
                texts[r["path"]] = Path(r["path"]).read_text(encoding="utf-8", errors="replace")
                mtimes[r["path"]] = Path(r["path"]).stat().st_mtime
            except OSError:
                texts[r["path"]] = ""
                mtimes[r["path"]] = 0.0
        if len({texts[r["path"]] for r in group}) < 2:
            continue
        for me in group:
            copies = []
            for other in group:
                if other is me or texts[other["path"]] == texts[me["path"]]:
                    continue
                a, b = mtimes[me["path"]], mtimes[other["path"]]
                copies.append(
                    {
                        "path": other["path"],
                        "dir": other["dir"],
                        "newer": "this" if a > b else "other" if b > a else "same",
                        "trees_differ": _tree(me["dir"], trees) != _tree(other["dir"], trees),
                    }
                )
            if copies:
                out[me["path"]] = copies
    return out


_cache: dict = {"key": None, "similar": {}, "diverged": {}}


def _key(records: list[dict]) -> tuple:
    return tuple(
        (
            r["path"],
            r.get("modified"),
            r.get("skill_md_bytes"),
            r.get("bytes"),
            r.get("file_count"),
            r.get("status"),
            tuple(r.get("harnesses") or []),
        )
        for r in records
    )


def annotate(records: list[dict]) -> None:
    """Add `similar` and `copies` to each record. Reuses the last result while nothing changed."""
    key = _key(records)
    if _cache["key"] != key:
        _cache.update(key=key, similar=similar(records), diverged=diverged(records))
    for r in records:
        r["similar"] = _cache["similar"].get(r["path"], [])
        r["copies"] = _cache["diverged"].get(r["path"], [])


def diff(a: str, b: str) -> dict:
    """A unified line diff of two SKILL.md files, as tagged lines for the page."""
    left = Path(a).read_text(encoding="utf-8", errors="replace").splitlines()
    right = Path(b).read_text(encoding="utf-8", errors="replace").splitlines()
    lines = []
    for ln in list(difflib.unified_diff(left, right, lineterm="", n=3))[2:]:
        op = ln[:1]
        lines.append({"op": op, "text": ln if op == "@" else ln[1:]})
    added = sum(1 for x in lines if x["op"] == "+")
    removed = sum(1 for x in lines if x["op"] == "-")
    return {
        "lines": lines[:MAX_DIFF_LINES],
        "truncated": len(lines) > MAX_DIFF_LINES,
        "added": added,
        "removed": removed,
    }
