import os
import urllib.parse
from pathlib import Path

import pytest
from conftest import get

import overlap
import serve


def rec(tmp_path, name, desc, harnesses=("codex",), folder="a", text=None, status="enabled"):
    d = tmp_path / folder / name
    d.mkdir(parents=True, exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(text if text is not None else f"---\nname: {name}\ndescription: {desc}\n---\n")
    return {
        "name": name,
        "description": desc,
        "path": str(md),
        "dir": str(d),
        "harnesses": list(harnesses),
        "status": status,
    }


PRD = "Turn the current conversation into a product requirements document and file it as an issue."
SPEC = "Turn the current conversation into a product spec document and file it as an issue."
CSS = "Pick oklch colors, build tonal palettes, and check text contrast for dark mode."


def test_tokens_drop_stopwords_and_plurals():
    assert overlap.tokens("Use this skill when the user wants Palettes and colors") == [
        "palette",
        "color",
    ]


def test_similar_pairs_share_a_harness(tmp_path):
    a, b = rec(tmp_path, "to-prd", PRD), rec(tmp_path, "to-spec", SPEC)
    c = rec(tmp_path, "color", CSS)
    found = overlap.similar([a, b, c])
    assert [x["name"] for x in found[a["path"]]] == ["to-spec"]
    assert found[a["path"]][0]["score"] >= overlap.THRESHOLD
    assert [x["name"] for x in found[b["path"]]] == ["to-prd"]
    assert c["path"] not in found


def test_similar_skips_other_harnesses_names_and_exact_copies(tmp_path):
    a = rec(tmp_path, "to-prd", PRD, harnesses=["codex"])
    assert overlap.similar([a, rec(tmp_path, "to-spec", SPEC, harnesses=["cursor"])]) == {}
    assert overlap.similar([a, rec(tmp_path, "to-prd", SPEC, folder="b")]) == {}
    assert overlap.similar([a, rec(tmp_path, "prd-copy", PRD)]) == {}
    assert overlap.similar([a, rec(tmp_path, "spec-old", SPEC, status="stale")]) == {}


def test_similar_keeps_one_per_name_and_caps(tmp_path):
    base = rec(tmp_path, "to-prd", PRD)
    others = [rec(tmp_path, f"to-spec-{i}", SPEC + f" v{i}") for i in range(7)]
    others += [rec(tmp_path, "to-spec-0", SPEC + " v0", folder="b")]
    found = overlap.similar([base, *others])[base["path"]]
    assert len(found) == overlap.LIMIT
    assert len({x["name"] for x in found}) == overlap.LIMIT


def test_diverged_copies(tmp_path):
    a = rec(tmp_path, "demo", "d", folder="agents", text="---\nname: demo\n---\nold\n")
    b = rec(tmp_path, "demo", "d", folder="codex", text="---\nname: demo\n---\nnew\n")
    same = rec(tmp_path, "demo", "d", folder="cursor", text="---\nname: demo\n---\nold\n")
    os.utime(a["path"], (1000, 1000))
    os.utime(same["path"], (1000, 1000))
    os.utime(b["path"], (2000, 2000))
    out = overlap.diverged([a, b, same])
    assert [c["path"] for c in out[a["path"]]] == [b["path"]]
    assert out[a["path"]][0]["newer"] == "other"
    assert out[a["path"]][0]["trees_differ"] is False
    assert {c["path"] for c in out[b["path"]]} == {a["path"], same["path"]}
    assert all(c["newer"] == "this" for c in out[b["path"]])
    (Path(b["dir"]) / "scripts").mkdir()
    (Path(b["dir"]) / "scripts" / "run.sh").write_text("echo\n")
    assert overlap.diverged([a, b])[a["path"]][0]["trees_differ"] is True


def test_identical_copies_are_not_diverged(tmp_path):
    a = rec(tmp_path, "demo", "d", folder="agents")
    b = rec(tmp_path, "demo", "d", folder="codex")
    assert overlap.diverged([a, b]) == {}


def test_annotate_reuses_the_last_result(tmp_path, monkeypatch):
    recs = [rec(tmp_path, "to-prd", PRD), rec(tmp_path, "to-spec", SPEC)]
    overlap.annotate(recs)
    assert recs[0]["similar"] and recs[0]["copies"] == []
    monkeypatch.setattr(overlap, "similar", lambda r: pytest.fail("recomputed"))
    fresh = [{k: v for k, v in r.items() if k not in ("similar", "copies")} for r in recs]
    overlap.annotate(fresh)
    assert fresh[0]["similar"] == recs[0]["similar"]


def test_diff_keeps_frontmatter_lines(tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("---\nname: x\n---\nbody\n")
    b.write_text("name: x\n---\nbody\nmore\n")
    d = overlap.diff(str(a), str(b))
    assert d["lines"][0]["op"] == "@"
    assert {"op": "-", "text": "---"} in d["lines"]
    assert {"op": "+", "text": "more"} in d["lines"]
    assert (d["added"], d["removed"], d["truncated"]) == (1, 1, False)


def test_diff_endpoint_only_takes_scanned_paths(server, tmp_path, monkeypatch):
    a = rec(tmp_path, "demo", "d", folder="x", text="one\n")
    b = rec(tmp_path, "demo", "d", folder="y", text="two\n")
    monkeypatch.setattr(serve, "scan", lambda repo: {"skills": [a, b]})
    q = lambda p: urllib.parse.quote(p)  # noqa: E731
    code, data = get(f"{server}/api/compare?a={q(a['path'])}&b={q(b['path'])}")
    assert code == 200 and data["added"] == 1 and data["removed"] == 1
    other = tmp_path / "other.md"
    other.write_text("secret\n")
    assert get(f"{server}/api/compare?a={q(a['path'])}&b={q(str(other))}")[0] == 400
