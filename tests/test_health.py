import json
import os
from pathlib import Path

from health import skill_problems, store_health
from scan import build_record, parse_frontmatter


def make(root: Path, folder: str, text: str) -> Path:
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(text)
    return md


def codes(md: Path) -> list[str]:
    text = md.read_text()
    fm, body = parse_frontmatter(text)
    return [p["code"] for p in skill_problems(md, text, fm, body)]


def test_clean_skill_has_no_problems(tmp_path):
    md = make(tmp_path, "demo", "---\nname: demo\ndescription: Does a thing\n---\n# Body\n")
    assert codes(md) == []


def test_frontmatter_missing_unclosed_unparsable(tmp_path):
    assert codes(make(tmp_path, "a", "# No frontmatter\n")) == ["frontmatter-missing"]
    assert codes(make(tmp_path, "b", "---\nname: b\n# body\n")) == ["frontmatter-unclosed"]
    assert codes(make(tmp_path, "c", "---\n  - just a list\n---\n")) == ["frontmatter-unparsable"]


def test_empty_frontmatter_reports_missing_fields(tmp_path):
    assert codes(make(tmp_path, "e", "---\n---\nbody\n")) == ["name-missing", "description-missing"]


def test_name_rules(tmp_path):
    md = make(tmp_path, "demo", "---\nname: Demo_Skill\ndescription: x\n---\n")
    assert codes(md) == ["name-format", "name-mismatch"]
    long = "a" * 65
    md = make(tmp_path, long, f"---\nname: {long}\ndescription: x\n---\n")
    assert codes(md) == ["name-format"]
    md = make(tmp_path, "bad--name", "---\nname: bad--name\ndescription: x\n---\n")
    assert codes(md) == ["name-format"]


def test_description_too_long(tmp_path):
    md = make(tmp_path, "d", f"---\nname: d\ndescription: {'w' * 1025}\n---\n")
    assert codes(md) == ["description-long"]


def test_unknown_boolean_values(tmp_path):
    md = make(
        tmp_path,
        "b",
        "---\nname: b\ndescription: x\ndisable-model-invocation: yes\nuser-invocable: False\n---\n",
    )
    problems = skill_problems(md, md.read_text(), *parse_frontmatter(md.read_text()))
    assert [p["code"] for p in problems] == ["bool-value"]
    assert "disable-model-invocation" in problems[0]["message"]


def test_missing_files_links_and_symlinks(tmp_path):
    body = (
        "See [guide](references/guide.md) and [ok](references/ok.md#top).\n"
        "Run `scripts/run.py` and `scripts/gone.py`. Web: [x](https://example.com).\n"
        "The project file `src/app.py` is not ours.\n"
        "```\n[fenced](nope.md)\n```\n"
    )
    md = make(tmp_path, "f", f"---\nname: f\ndescription: x\n---\n{body}")
    (md.parent / "references").mkdir()
    (md.parent / "references" / "ok.md").write_text("ok")
    (md.parent / "scripts").mkdir()
    (md.parent / "scripts" / "run.py").write_text("")
    os.symlink(tmp_path / "nowhere", md.parent / "scripts" / "dead")
    problems = skill_problems(md, md.read_text(), *parse_frontmatter(md.read_text()))
    found = {(p["code"], p["level"], p.get("path")) for p in problems}
    assert found == {
        ("broken-link", "error", "references/guide.md"),
        ("missing-file", "warn", "scripts/gone.py"),
        ("broken-symlink", "error", "scripts/dead"),
    }


def test_build_record_carries_problems(tmp_path):
    md = make(tmp_path, "r", "---\nname: other\ndescription: x\n---\n")
    rec = build_record(md, scope="personal")
    assert [p["code"] for p in rec["problems"]] == ["name-mismatch"]
    assert all(p["message"] and p["hint"] for p in rec["problems"])


def test_store_health_ghosts_and_broken_installs(tmp_path):
    store = tmp_path / ".agents" / "skills"
    make(store, "kept", "---\nname: kept\ndescription: x\n---\n")
    (store / "empty").mkdir()
    (store / ".hidden").mkdir()
    os.symlink(tmp_path / "gone", store / "dangling")
    lock = {"skills": {"kept": {}, "ghost": {"source": "o/r"}}}
    (store.parent / ".skill-lock.json").write_text(json.dumps(lock))
    (store.parent / ".atlas-lock.json").write_text(json.dumps({"skills": {"phantom": {}}}))

    h = store_health([store.resolve()], store.resolve())
    got = {(p["code"], p["skill"]) for p in h["problems"]}
    assert got == {
        ("ghost-lock", "ghost"),
        ("ghost-lock", "phantom"),
        ("no-skill-md", "empty"),
        ("broken-symlink", "dangling"),
    }
    assert (h["errors"], h["warnings"]) == (1, 3)


def test_store_health_without_store(tmp_path):
    assert store_health([], None) == {"problems": [], "errors": 0, "warnings": 0}
