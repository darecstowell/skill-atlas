import json
import os
import re
import time
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from skill_atlas import history, updates
from skill_atlas.core.api import AtlasAPI
from skill_atlas.core.atlas import Atlas, config_roots
from skill_atlas.core.demo import MARKETING, DemoAtlas
from skill_atlas.scan import git_tree_hash, parse_frontmatter

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 28, 9, 41, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def demo() -> DemoAtlas:
    """One shared atlas for tests that only read."""
    return DemoAtlas(now=NOW)


@pytest.fixture
def fresh() -> DemoAtlas:
    return DemoAtlas(n=50, now=NOW)


def by_name(data: dict, name: str, scope: str = "personal") -> dict:
    return next(s for s in data["skills"] if s["name"] == name and s["scope"] == scope)


def finish(api: AtlasAPI, job: dict) -> dict:
    seen = [job]
    while not job["done"]:
        got = api.job(job["id"])
        assert got is not None and len(seen) < 50
        job = got
        seen.append(job)
    return {"last": job, "states": {i["state"] for j in seen for i in j["items"].values()}}


# --------------------------------------------------------------------------
# contract


def test_demo_is_an_atlas_api() -> None:
    api: AtlasAPI = DemoAtlas(n=50)
    assert callable(api.data)


def test_mypy_checks_this_file(monkeypatch: pytest.MonkeyPatch) -> None:
    mypy = pytest.importorskip("mypy.api")
    monkeypatch.setenv("MYPYPATH", os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests")]))
    out, err, code = mypy.run(["--config-file", str(ROOT / "pyproject.toml"), __file__])
    assert code == 0, out + err


def test_same_seed_same_data() -> None:
    a, b = DemoAtlas(now=NOW), DemoAtlas(now=NOW)
    assert a.data() == b.data()
    assert a.usage() == b.usage() and a.updates() == b.updates()
    other = DemoAtlas(seed=8, now=NOW).data()
    assert other["count"] == a.data()["count"]
    assert other["skills"] != a.data()["skills"]


def test_data_is_a_copy(demo: DemoAtlas) -> None:
    data = demo.data()
    data["skills"].clear()
    assert demo.data()["count"] == len(demo.data()["skills"]) > 0


@pytest.mark.parametrize("n", [50, 400, 1000])
def test_count_follows_n(n: int) -> None:
    count = DemoAtlas(n=n, now=NOW).data()["count"]
    assert count == max(n, 203)


# --------------------------------------------------------------------------
# shapes, against the real atlas over a small home


def skill(folder: Path, name: str, text: str = "") -> Path:
    d = folder / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text or f"---\nname: {name}\ndescription: d\n---\n# {name}\n")
    return d


@pytest.fixture
def real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Atlas]:
    """Two Claude Code roots, the skill store, a plugin, a project, and three more harnesses."""
    home = Path.home()
    agents = home / ".agents"
    alpha = skill(agents / "skills", "alpha")
    (alpha / "scripts").mkdir()
    (alpha / "scripts" / "run.sh").write_text("#!/bin/sh\ncurl https://api.github.com\n")
    skill(agents / "skills", "beta")
    entry = {
        "source": "o/r",
        "sourceType": "github",
        "sourceUrl": "https://github.com/o/r.git",
        "skillPath": "skills/alpha/SKILL.md",
        "skillFolderHash": git_tree_hash(alpha),
        "installedAt": "2026-01-01T00:00:00.000Z",
        "updatedAt": "2026-01-01T00:00:00.000Z",
    }
    (agents / ".skill-lock.json").write_text(json.dumps({"skills": {"alpha": entry}}))
    claude = home / ".claude"
    claude.mkdir()
    (claude / "skills").symlink_to(agents / "skills")
    version = claude / "plugins" / "cache" / "mkt" / "kit" / "1.0"
    skill(version / "skills", "tool")
    installs = {"kit@mkt": [{"installPath": str(version), "scope": "user"}]}
    (claude / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": installs}))
    (claude / "settings.json").write_text(json.dumps({"enabledPlugins": {"kit@mkt": True}}))
    work = home / ".claude-work"
    skill(work / "skills", "gamma")
    (work / "settings.json").write_text("{}")
    skill(home / "code" / "shop" / ".claude" / "skills", "delta")
    for d in (".codex", ".cursor", ".gemini"):
        (home / d).mkdir()
    (home / ".gemini" / "settings.json").write_text("{}")
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = {
        "config_roots": {"personal": "~/.claude", "work": "~/.claude-work"},
        "project_roots": ["~/code"],
    }
    (repo / "config.json").write_text(json.dumps(cfg))
    tree = {
        "sha": "root",
        "tree": [
            {"type": "tree", "path": "skills/alpha", "sha": "new"},
            {"type": "blob", "path": "skills/alpha/SKILL.md", "sha": "x"},
            {"type": "blob", "path": "skills/fresh/SKILL.md", "sha": "y"},
        ],
    }
    monkeypatch.setattr(updates, "fetch_tree", lambda repo, ref: tree)
    updates._cache.clear()
    history.snapshot(alpha, "alpha", agents / ".skill-lock.json", entry)
    yield Atlas(config_roots(repo), repo)
    updates._cache.clear()


def keys(rows) -> set[str]:
    return set().union(*(set(r) for r in rows))


def one_of(data: dict, scope: str) -> dict:
    return next(s for s in data["skills"] if s["scope"] == scope)


def test_data_shape_matches_a_real_scan(real: Atlas, demo: DemoAtlas) -> None:
    want, got = real.data(), demo.data()
    assert set(got) == set(want)
    for scope in ("personal", "plugin", "project"):
        assert set(one_of(got, scope)) == set(one_of(want, scope)), scope
        for rec in got["skills"]:
            if rec["scope"] == scope:
                assert set(rec) == set(one_of(want, scope)), rec["path"]
    assert keys(got["harnesses"].values()) == keys(want["harnesses"].values())
    assert set(got["settings"]["claude-code:work"]) == set(want["settings"]["claude-code:work"])
    assert set(got["settings"]["gemini-cli"]) == set(want["settings"]["gemini-cli"])
    assert got["settings"]["cursor"] == want["settings"]["cursor"] == {}
    assert set(got["health"]) == set(want["health"])
    assert set(got["server"]) == set(want["server"])
    assert set(by_name(got, "copywriting")["origin"]) == set(by_name(want, "alpha")["origin"])
    for k in ("security", "similar", "copies"):
        assert type(by_name(got, "copywriting")[k]) is type(by_name(want, "alpha")[k])
    assert set(by_name(got, "copywriting")["security"]) == set(by_name(want, "alpha")["security"])


def test_read_shapes_match(real: Atlas, demo: DemoAtlas) -> None:
    want, got = real.data(), demo.data()
    alpha = by_name(want, "alpha")
    risky = by_name(got, "repo-bootstrap")
    assert set(demo.security(risky["path"])) == set(real.security(alpha["path"]))
    assert keys(demo.security(risky["path"])["findings"]) <= keys(
        real.security(alpha["path"])["findings"]
    ) | {"host"}
    assert set(demo.history("copywriting")) == set(real.history("alpha"))
    assert keys(demo.history("copywriting")["snapshots"]) == keys(
        real.history("alpha")["snapshots"]
    )
    a, b = by_name(want, "alpha")["path"], by_name(want, "beta")["path"]
    pair = by_name(got, "copywriting"), by_name(got, "emil-ui-polish")
    assert set(demo.compare(pair[0]["path"], pair[1]["path"])) == set(real.compare(a, b))
    up_want, up_got = real.updates(refresh=True), demo.updates()
    assert set(up_got) == set(up_want)
    assert keys(a for v in up_got["available"].values() for a in v) == keys(
        a for v in up_want["available"].values() for a in v
    )
    ex_want, ex_got = real.export(), demo.export()
    assert set(ex_got) == set(ex_want)
    assert keys(ex_got["skills"]) == keys(ex_want["skills"])
    assert set(demo.restore_plan()) == set(real.restore_plan())
    real.profile("save", {"name": "x"})
    p_want, p_got = real.profiles()["profiles"], demo.profiles()["profiles"]
    assert keys(p_got) == keys(p_want)
    assert set(demo.repos(["mattpocock/skills"])["mattpocock/skills"]) == {
        "avatar", "banner", "custom_banner", "description", "stars", "images",
    }  # fmt: skip


def test_write_shapes_match(real: Atlas, fresh: DemoAtlas) -> None:
    data = fresh.data()
    assert set(fresh.toggle("claude-code:personal", "skill", ["acli"], False)) == set(
        real.toggle("claude-code:personal", "skill", ["beta"], False)
    )
    assert set(fresh.toggle("gemini-cli", "skill", ["acli"], False)) == set(
        real.toggle("gemini-cli", "skill", ["alpha"], False)
    )
    name = by_name(real.data(), "beta")["name"]
    job_want = real.update([name])
    while not job_want["done"]:
        time.sleep(0.01)
        job_want = real.job(job_want["id"]) or job_want
    job_got = finish(fresh, fresh.update(["acli"]))["last"]
    assert set(job_got) == set(job_want)
    failed = {"state": "failed", "error": "not linked to a GitHub repo"}
    assert job_got["items"] == {"acli": failed} and job_want["items"] == {name: failed}
    pv_want = real.profile("preview", {"states": {"gemini-cli": {"skills": {"alpha": True}}}})
    pv_got = fresh.profile("preview", {"states": {"gemini-cli": {"skills": {"acli": True}}}})
    assert set(pv_got) == set(pv_want)
    assert set(pv_got["harnesses"]["gemini-cli"]) == set(pv_want["harnesses"]["gemini-cli"])
    m = real.export()
    assert set(fresh.import_plan({"manifest": m})) == set(real.import_plan({"manifest": m}))
    assert len(data["skills"]) == data["count"]


# --------------------------------------------------------------------------
# content


def test_states_the_ui_needs(demo: DemoAtlas) -> None:
    data, upd, use = demo.data(), demo.updates(), demo.usage()
    skills = data["skills"]
    outdated = {n for n, st in upd["skills"].items() if st == "outdated"}
    assert len(outdated & {name for name, _ in MARKETING}) == 8
    assert [s["name"] for s in skills if s.get("local_edits")] == ["seo-audit"]
    assert sum(a["new"] for a in upd["available"]["mattpocock/skills"]) == 3
    assert "elevenlabs/skills" in upd["errors"] and "unknown" in upd["skills"].values()
    assert any(a["taken"] == "moved" for v in upd["available"].values() for a in v)
    assert any(a["taken"] == "taken" for v in upd["available"].values() for a in v)
    assert "vercel-labs/agent-skills" in upd["watched"]
    problems = sorted((len(s["problems"]), s["dir_name"]) for s in skills if s["problems"])
    assert problems[-1] == (6, "pdf-toolkit") and len(problems) >= 3
    levels = Counter(s["security"]["level"] for s in skills)
    assert levels["high"] == 1 and levels["medium"] >= 3 and levels["info"] > 50
    assert any(s["similar"] for s in skills) and any(s["copies"] for s in skills)
    stale = [s for s in skills if s["status"] == "stale"]
    assert stale and {s["plugin_version"] for s in stale} == {"4.0.3"}
    assert {s["marketplace"] for s in skills if s["scope"] == "plugin"} == {
        "anthropic-agent-skills", "superpowers-marketplace",
    }  # fmt: skip
    assert {s["status"] for s in skills if s["scope"] == "plugin"} >= {
        "enabled", "disabled", "installed", "stale",
    }  # fmt: skip
    assert sum(s["name"].startswith("acme-") and not s["origin"] for s in skills) >= 3
    assert any(not s["origin"] and not s["name"].startswith("acme-") for s in skills)
    assert {s["project"] for s in skills if s["scope"] == "project"} >= {"storefront"}
    assert any(not h["switch"] for h in data["harnesses"].values())
    assert {h["name"] for h in data["harnesses"].values()} == {
        "Claude Code", "Codex", "Cursor", "Gemini CLI", "Antigravity", "Copilot CLI", "OpenCode",
    }  # fmt: skip
    assert data["config_roots"] == {
        "personal": "/home/demo/.claude",
        "work": "/home/demo/.claude-work",
    }
    assert all(s["path"].startswith("/home/demo/") for s in skills)
    assert max(len(s["name"]) for s in skills) > 50
    assert max(len(s["description"]) for s in skills) > 1024
    assert any(re.search(r"[^\x00-\x7f]", s["description"]) for s in skills)
    costly = by_name(data, "enterprise-architecture-review")
    assert costly["tokens_listed"] > 200 and costly["invoke"] not in use["skills"]
    used = {k for k in use["skills"]} | set(use["counters"])
    assert sum(s["invoke"] not in used for s in skills) > len(skills) / 2
    first = datetime.fromisoformat(use["first_day"]).date()
    assert (datetime.fromisoformat(use["today"]).date() - first).days >= 7 * 25
    totals = sorted((sum(v["days"].values()) for v in use["skills"].values()), reverse=True)
    assert totals[0] > 10 * totals[len(totals) // 2]
    assert len(demo.profiles()["profiles"]) == 3
    assert len(demo.history("copywriting")["snapshots"]) == 5
    d = demo.diff("copywriting")
    assert {f["status"] for f in d["files"]} == {"added", "removed", "changed"}
    assert any(f.get("binary") for f in d["files"]) and d["added"] > 0 < d["removed"]
    assert demo.diff("seo-audit")["local_edits"] is True
    assert data["health"]["errors"] == 1 and data["health"]["warnings"] == 2


def test_skill_text_is_rich_markdown(demo: DemoAtlas) -> None:
    rec = by_name(demo.data(), "copywriting")
    text = demo.skill_text(rec["path"])
    fm, body = parse_frontmatter(text)
    assert fm["name"] == "copywriting" and fm["description"] == rec["description"]
    for pattern in (r"^# ", r"^## ", r"^### ", r"^- ", r"^```\w+", r"^\| --- \|", r"\]\(http"):
        assert re.search(pattern, body, re.M), pattern
    assert rec["words"] == len(body.split()) and rec["skill_md_bytes"] == len(text.encode())
    with pytest.raises(ValueError, match="unknown skill path"):
        demo.skill_text("/etc/passwd")


def test_repos(demo: DemoAtlas) -> None:
    got = demo.repos(["https://github.com/emilkowalski/skills.git", "nobody/nothing"])
    assert got["emilkowalski/skills"]["stars"] > 1000 and got["nobody/nothing"] == {"images": []}


# --------------------------------------------------------------------------
# writes


def test_toggle_shows_in_data(fresh: DemoAtlas) -> None:
    rec = by_name(fresh.data(), "grilling")
    assert "grilling" not in fresh.data()["settings"]["claude-code:personal"]["skillOverrides"]
    st = fresh.toggle("claude-code:personal", "skill", ["grilling"], False)
    assert st["skillOverrides"]["grilling"] == "off"
    assert fresh.data()["settings"]["claude-code:personal"]["skillOverrides"]["grilling"] == "off"
    fresh.toggle("claude-code:personal", "skill", ["grilling"], True)
    assert "grilling" not in fresh.data()["settings"]["claude-code:personal"]["skillOverrides"]

    assert "codex" in rec["harnesses"]
    assert fresh.toggle("codex", "skill", ["grilling"], False)["off"].count("grilling") == 1
    assert "grilling" in fresh.data()["settings"]["codex"]["off"]

    ref = "superpowers@superpowers-marketplace"
    fresh.toggle("claude-code:personal", "plugin", [ref], False)
    plugin = [s for s in fresh.data()["skills"] if s.get("plugin_ref") == ref]
    assert {s["status"] for s in plugin} == {"disabled", "stale"}

    with pytest.raises(NotImplementedError):
        fresh.toggle("cursor", "skill", ["grilling"], False)
    with pytest.raises(ValueError, match="no plugin switch"):
        fresh.toggle("codex", "plugin", [ref], False)
    with pytest.raises(ValueError, match="unknown harness"):
        fresh.toggle("nope", "skill", ["grilling"], False)


def test_update_job_reaches_done(fresh: DemoAtlas) -> None:
    before = fresh.updates()["skills"]
    names = ["copywriting", "emails", "cro", "paywalls", "launch"]
    assert all(before[n] == "outdated" for n in names)
    old = fresh.skill_text(by_name(fresh.data(), "copywriting")["path"])
    job = fresh.update(names)
    assert {i["state"] for i in job["items"].values()} == {"queued"}
    with pytest.raises(RuntimeError):
        fresh.update(["cro"])
    run = finish(fresh, job)
    assert run["states"] >= {"queued", "downloading", "installing", "done", "failed"}
    items = run["last"]["items"]
    assert items["paywalls"]["state"] == "failed" and items["paywalls"]["error"]
    assert {n for n, i in items.items() if i["state"] == "done"} == set(names) - {"paywalls"}
    after = fresh.updates()["skills"]
    assert [n for n in names if after[n] == "outdated"] == ["paywalls"]
    rec = by_name(fresh.data(), "copywriting")
    assert fresh.skill_text(rec["path"]) != old
    assert fresh.diff("copywriting")["files"] == []
    snaps = fresh.history("copywriting")["snapshots"]
    assert len(snaps) == 5 and snaps[0]["reason"] == "update"
    assert fresh.job(job["id"]) == run["last"]
    assert fresh.job("gone") is None


def test_snapshot_diff_previews_a_restore(fresh: DemoAtlas) -> None:
    snap = fresh.history("copywriting")["snapshots"][0]
    out = fresh.snapshot_diff("copywriting", snap["id"])
    assert set(out) == {"name", "id", "files", "added", "removed"}
    assert [f["path"] for f in out["files"]] == ["SKILL.md"]
    fresh.rollback("copywriting", snap["id"])
    assert fresh.snapshot_diff("copywriting", snap["id"])["files"] == []
    with pytest.raises(ValueError, match="bad snapshot id"):
        fresh.snapshot_diff("copywriting", "nope")


def test_rollback(fresh: DemoAtlas) -> None:
    snap = fresh.history("copywriting")["snapshots"][-1]
    out = fresh.rollback("copywriting", snap["id"])
    assert out == {"name": "copywriting", "restored": snap["id"], "at": snap["at"]}
    assert fresh.history("copywriting")["snapshots"][0]["reason"] == "restore"
    assert by_name(fresh.data(), "copywriting")["origin"]["skillFolderHash"].startswith(
        snap["hash"]
    )
    with pytest.raises(ValueError, match="bad snapshot id"):
        fresh.rollback("copywriting", "nope")


def test_install_new_skill(fresh: DemoAtlas) -> None:
    new = [a for a in fresh.updates()["available"]["mattpocock/skills"] if a["new"]]
    paths = [a["path"] for a in new]
    described = fresh.available("mattpocock/skills", paths)["skills"]
    assert set(described) == set(paths) and all(v["description"] for v in described.values())
    run = finish(fresh, fresh.install("mattpocock/skills", paths))
    assert {i["state"] for i in run["last"]["items"].values()} == {"done"}
    names = {s["name"] for s in fresh.data()["skills"]}
    assert {a["name"] for a in new} <= names
    left = fresh.updates()["available"]["mattpocock/skills"]
    assert not any(a["new"] for a in left)
    assert all(fresh.updates()["skills"][a["name"]] == "current" for a in new)


def test_delete_and_undo(fresh: DemoAtlas) -> None:
    fresh.toggle("claude-code:personal", "skill", ["acli"], False)
    count = fresh.data()["count"]
    assert fresh.delete(["acli", "grilling"]) == {"trashed": ["acli", "grilling"]}
    data = fresh.data()
    assert data["count"] == count - 2 and "acli" not in {s["name"] for s in data["skills"]}
    assert "acli" not in data["settings"]["claude-code:personal"]["skillOverrides"]
    assert "grilling" not in fresh.updates()["skills"]
    assert fresh.undo_delete() == {"restored": ["acli", "grilling"]}
    data = fresh.data()
    assert data["count"] == count
    assert data["settings"]["claude-code:personal"]["skillOverrides"]["acli"] == "off"
    with pytest.raises(ValueError, match="nothing to undo"):
        fresh.undo_delete()
    with pytest.raises(ValueError, match="not a personal skill"):
        fresh.delete(["gh-fix-ci"])


def test_profiles_apply_and_undo(fresh: DemoAtlas) -> None:
    before = fresh.data()["settings"]
    preview = fresh.profile("preview", {"name": "iOS release week"})
    assert preview["changed"] > 0
    out = fresh.profile("apply", {"name": "iOS release week"})
    assert fresh.profile("preview", {"name": "iOS release week"})["changed"] == 0
    fresh.profile("apply", {"states": out["previous"]})
    assert fresh.data()["settings"] == before
    missing = fresh.profile("preview", {"name": "Minimal context"})["harnesses"]
    assert "legacy-deploy" in missing["claude-code:personal"]["missing"]
    assert missing["windsurf"]["found"] is False
    fresh.profile("save", {"name": "  Now  "})
    fresh.profile("rename", {"name": "Now", "to": "Later"})
    with pytest.raises(RuntimeError):
        fresh.profile("save", {"name": "Later"})
    deleted = fresh.profile("delete", {"name": "Later"})["deleted"]
    fresh.profile("restore", {"profile": deleted})
    assert [p["name"] for p in fresh.profiles()["profiles"]][-1] == "Later"


def test_link_watch_dismiss(fresh: DemoAtlas) -> None:
    out = fresh.link(["acme-deploy", "acme-standup"], "acme-corp/agent-skills")
    assert out == {
        "repo": "acme-corp/agent-skills",
        "linked": ["acme-deploy"],
        "missing": ["acme-standup"],
    }
    assert by_name(fresh.data(), "acme-deploy")["origin"]["source"] == "acme-corp/agent-skills"
    assert "acme-deploy" in fresh.updates()["skills"]
    with pytest.raises(ValueError, match="could not read"):
        fresh.link(["acme-deploy"], "nobody/nothing")
    assert "anthropics/skills" not in fresh.updates()["watched"]
    with pytest.raises(ValueError, match="could not read"):
        fresh.watch("nobody/nothing", True)
    fresh.watch("vercel-labs/agent-skills", False)
    assert "vercel-labs/agent-skills" not in fresh.updates()["available"]
    fresh.watch("https://github.com/vercel-labs/agent-skills", True)
    assert "vercel-labs/agent-skills" in fresh.updates()["available"]
    paths = [a["path"] for a in fresh.updates()["available"]["mattpocock/skills"] if a["new"]]
    assert fresh.dismiss("mattpocock/skills", paths) == {
        "repo": "mattpocock/skills",
        "dismissed": 3,
    }
    assert not any(a["new"] for a in fresh.updates()["available"]["mattpocock/skills"])


def test_export_import_round_trip(fresh: DemoAtlas) -> None:
    m = fresh.export()
    assert m["skill_atlas_manifest"] == 1 and m["watched"] == ["vercel-labs/agent-skills"]
    plan = fresh.import_plan({"manifest": m})
    assert not plan["install"] and not plan["differ"] and plan["same"]
    restore = fresh.restore_plan()
    assert [i["name"] for i in restore["install"]] == ["ab-test-setup"]
    out = fresh.import_apply({"restore": True, "install": ["ab-test-setup"]})
    assert finish(fresh, out["job"])["last"]["items"]["ab-test-setup"]["state"] == "done"
    assert fresh.restore_plan()["install"] == []
    assert fresh.data()["health"]["warnings"] == 1


def test_clock_moves_without_now() -> None:
    api = DemoAtlas(n=50)
    stamp = datetime.fromisoformat(api.data()["generated_at"])
    assert abs(stamp - datetime.now().astimezone()) < timedelta(minutes=1)


def test_available_text_is_the_skill_an_install_would_bring(fresh: DemoAtlas) -> None:
    repo, items = next((r, a) for r, a in fresh.updates()["available"].items() if a)
    text = fresh.available_text(repo, items[0]["path"])
    fm, _ = parse_frontmatter(text)
    assert fm["name"] == items[0]["name"]
    with pytest.raises(OSError, match="did not answer"):
        fresh.available_text("elevenlabs/skills", "skills/x/SKILL.md")
    with pytest.raises(OSError, match="not found"):
        fresh.available_text(repo, "skills/nothing-here/SKILL.md")
    with pytest.raises(ValueError, match="bad skill paths"):
        fresh.available_text(repo, "../SKILL.md")
