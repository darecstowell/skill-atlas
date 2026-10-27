import json
import time
from pathlib import Path

import pytest

from conftest import get, post
from skill_atlas import manifest, serve, updates
from skill_atlas.harnesses import detect
from skill_atlas.scan import git_tree_hash, scan


def skill(skills_dir: Path, name: str) -> Path:
    d = skills_dir / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\nbody\n")
    return d


def entry(repo: str, path: str, sha: str) -> dict:
    return {"source": repo, "sourceType": "github", "skillPath": path, "skillFolderHash": sha}


@pytest.fixture
def home():
    home = Path.home()
    agents = home / ".agents"
    alpha = skill(agents / "skills", "alpha")
    skill(agents / "skills", "beta")
    (agents / ".skill-lock.json").write_text(
        json.dumps(
            {
                "version": 1,
                "skills": {
                    "alpha": entry("o/r", "skills/alpha/SKILL.md", git_tree_hash(alpha)),
                    "gone": entry("o/r", "skills/gone/SKILL.md", "abc"),
                },
            }
        )
    )
    (agents / ".atlas-lock.json").write_text(json.dumps({"sources": ["o/watched"]}))
    claude = home / ".claude"
    claude.mkdir()
    (claude / "skills").symlink_to(agents / "skills")
    (claude / "settings.json").write_text(json.dumps({"skillOverrides": {"beta": "off"}}))
    (home / ".gemini").mkdir()
    (home / ".gemini" / "settings.json").write_text(json.dumps({"skills": {"disabled": []}}))
    return home


@pytest.fixture
def data(home, tmp_path):
    return scan(tmp_path)


@pytest.fixture
def roots(home):
    return [home / ".agents", home / ".claude"]


def test_export_shape_and_tilde_paths(home, data, roots):
    m = manifest.export(data, roots)
    assert m["skill_atlas_manifest"] == 1
    assert m["exported_at"] and m["watched"] == ["o/watched"]
    by = {s["name"]: s for s in m["skills"]}
    assert by["alpha"]["source"] == "o/r"
    assert by["alpha"]["skillPath"] == "skills/alpha/SKILL.md"
    assert by["alpha"]["skillFolderHash"]
    assert by["beta"] == {"name": "beta", "dir": "~/.agents/skills/beta", "untracked": True}
    assert m["harness_states"]["claude-code"]["off"] == ["beta"]
    assert m["harness_states"]["gemini-cli"]["off"] == []
    assert str(home) not in json.dumps(m)


def test_plan_diffs_against_store(data, roots):
    alpha_hash = next(s for s in data["skills"] if s["name"] == "alpha")["origin"]
    m = {
        "skill_atlas_manifest": 1,
        "skills": [
            {
                "name": "alpha",
                **entry("o/r", "skills/alpha/SKILL.md", alpha_hash["skillFolderHash"]),
            },
            {"name": "beta", **entry("o/r", "skills/beta/SKILL.md", "other")},
            {"name": "newone", **entry("o/r", "skills/newone/SKILL.md", "x")},
            {"name": "ghost", "untracked": True},
            {"name": "evil", **entry("o/r", "../x/SKILL.md", "x")},
            "junk",
        ],
        "watched": ["o/watched", "https://github.com/o/new", "not a repo", 3],
        "harness_states": {
            "claude-code": {"off": ["alpha", "beta", "newone", "nothere"]},
            "codex": {"name": "Codex", "off": ["x"]},
        },
    }
    p = manifest.plan(m, data, roots)
    assert p["install"] == [{"name": "newone", "repo": "o/r", "path": "skills/newone/SKILL.md"}]
    assert [s["name"] for s in p["same"]] == ["alpha"]
    assert [s["name"] for s in p["differ"]] == ["beta"]
    assert p["untracked"] == [{"name": "ghost"}, {"name": "evil"}]
    assert p["harness"] == [
        {"harness": "claude-code", "name": "Claude Code", "off": ["alpha", "newone"]}
    ]
    assert p["skipped"] == [{"harness": "codex", "name": "Codex"}]
    assert p["watch"] == ["o/new"]


@pytest.mark.parametrize(
    "bad", [{}, {"skill_atlas_manifest": "1"}, {"skill_atlas_manifest": 99, "skills": []}]
)
def test_plan_refuses_other_files(bad, data, roots):
    with pytest.raises(ValueError):
        manifest.plan(bad, data, roots)


def test_restore_finds_missing_folders(roots):
    p = manifest.missing(roots)
    assert p["install"] == [{"name": "gone", "repo": "o/r", "path": "skills/gone/SKILL.md"}]
    assert manifest.missing([])["install"] == []


@pytest.fixture
def offline(monkeypatch):
    calls: list = []

    def install(repo, paths, job, roots):
        for p in paths:
            n = updates.skill_name(repo, p)
            skill(roots[0] / "skills", n)
            job["items"][n] = {"state": "done"}
        calls.append((repo, paths))

    monkeypatch.setattr(updates, "_install_source", install)
    monkeypatch.setattr(updates, "fetch_tree", lambda repo, ref: {"tree": []})
    return calls


def wait(job_id: str) -> dict:
    for _ in range(100):
        job = updates.JOBS[job_id]
        if job["done"]:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_apply_installs_switches_and_watches(home, data, roots, offline):
    m = {
        "skill_atlas_manifest": 1,
        "skills": [
            {"name": "one", **entry("o/r", "skills/one/SKILL.md", "x")},
            {"name": "two", **entry("p/q", "two/SKILL.md", "y")},
            {"name": "skip", **entry("o/r", "skills/skip/SKILL.md", "z")},
        ],
        "watched": ["o/new"],
        "harness_states": {
            "claude-code": {"off": ["alpha", "one"]},
            "gemini-cli": {"off": ["alpha"]},
        },
    }
    full = manifest.plan(m, data, roots)
    pick = {"install": ["one", "two"], "harness": ["claude-code", "gemini-cli"], "watch": ["o/new"]}
    found = detect({"main": home / ".claude"})
    r = manifest.apply(full, pick, data, roots, found, serve.write_setting)
    assert r["errors"] == [] and r["watched"] == 1 and r["switched"] == 3
    wait(r["job"]["id"])
    assert sorted(offline) == [("o/r", ["skills/one/SKILL.md"]), ("p/q", ["two/SKILL.md"])]
    assert not (home / ".agents" / "skills" / "skip").exists()
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    assert settings["skillOverrides"] == {"beta": "off", "alpha": "off", "one": "off"}
    gemini = json.loads((home / ".gemini" / "settings.json").read_text())
    assert gemini["skills"]["disabled"] == ["alpha"]
    assert updates.watched(roots) == ["o/new", "o/watched"]


def test_restore_endpoints(home, server, offline):
    serve.ROOTS["personal"] = home / ".claude"
    code, plan = get(server + "/api/restore")
    assert code == 200 and [i["name"] for i in plan["install"]] == ["gone"]
    code, r = post(server + "/api/import/apply", {"restore": True, "install": ["gone"]})
    assert code == 200
    wait(r["job"]["id"])
    assert (home / ".agents" / "skills" / "gone" / "SKILL.md").exists()
    assert get(server + "/api/restore")[1]["install"] == []
    code, m = get(server + "/api/export")
    assert code == 200 and m["skill_atlas_manifest"] == 1
    code, err = post(server + "/api/import/plan", {"manifest": {"skills": []}})
    assert code == 400 and "not a Skill Atlas manifest" in err["error"]
