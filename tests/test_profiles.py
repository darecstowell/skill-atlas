import json
import os
from collections import Counter
from pathlib import Path

import pytest
from conftest import get, post

import harnesses
import profiles
import serve
from scan import scan


def skill(folder: Path, name: str) -> None:
    md = folder / name / "SKILL.md"
    md.parent.mkdir(parents=True)
    md.write_text(f"---\nname: {name}\ndescription: d\n---\nbody\n")


@pytest.fixture
def home(tmp_path):
    """A Claude Code root with two skills and a plugin, and Gemini CLI with two skills."""
    home = Path.home()
    claude = home / ".claude"
    for n in ("alpha", "beta"):
        skill(claude / "skills", n)
    version = claude / "plugins" / "cache" / "mkt" / "kit" / "1.0"
    skill(version / "skills", "tool")
    installs = {"kit@mkt": [{"installPath": str(version), "scope": "user"}]}
    (claude / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": installs}))
    (claude / "settings.json").write_text(
        json.dumps({"theme": "dark", "enabledPlugins": {"kit@mkt": True}})
    )
    gemini = home / ".gemini"
    for n in ("gamma", "delta"):
        skill(gemini / "skills", n)
    (gemini / "settings.json").write_text(json.dumps({"keep": 1}))
    return home


def ctx(tmp_path):
    found = harnesses.detect({"main": Path.home() / ".claude"})
    return found, scan(tmp_path)["skills"]


def call(tmp_path, action, **req):
    return profiles.handle(
        action,
        req,
        lambda: ctx(tmp_path)[0],
        lambda: ctx(tmp_path)[1],
        serve.write_settings,
    )


def now(tmp_path):
    found, skills = ctx(tmp_path)
    return {h.id: profiles.current(h, skills) for h in found if h.switch}


def test_save_change_apply_and_undo(home, tmp_path):
    serve.write_setting(home / ".claude", "skill", ["beta"], on=False)
    call(tmp_path, "save", name="  Writing   mode ")
    saved = now(tmp_path)
    assert saved == {
        "claude-code": {"skills": {"alpha": True, "beta": False}, "plugins": {"kit@mkt": True}},
        "gemini-cli": {"skills": {"gamma": True, "delta": True}, "plugins": {}},
    }
    assert json.loads(profiles.path().read_text())["profiles"][0]["name"] == "Writing mode"

    serve.write_setting(home / ".claude", "skill", ["alpha"], on=False)
    serve.write_setting(home / ".claude", "skill", ["beta"], on=True)
    serve.write_setting(home / ".claude", "plugin", ["kit@mkt"], on=False)
    g = {h.id: h for h in ctx(tmp_path)[0]}["gemini-cli"]
    harnesses.set_skills(g, [s for s in ctx(tmp_path)[1] if s["name"] == "delta"], on=False)
    changed = now(tmp_path)

    p = call(tmp_path, "preview", name="Writing mode")
    assert p["changed"] == 4
    assert p["harnesses"]["claude-code"] | {"label": "x"} == {
        "label": "x",
        "found": True,
        "on": ["alpha"],
        "off": ["beta"],
        "plugins_on": ["kit@mkt"],
        "plugins_off": [],
        "missing": [],
    }
    assert p["harnesses"]["gemini-cli"]["on"] == ["delta"]

    r = call(tmp_path, "apply", name="Writing mode")
    assert now(tmp_path) == saved
    assert r["settings"]["claude-code"]["skillOverrides"] == {"beta": "off"}
    assert r["settings"]["gemini-cli"]["off"] == []
    assert json.loads((home / ".claude" / "settings.json").read_text())["theme"] == "dark"

    call(tmp_path, "apply", states=r["previous"])
    assert now(tmp_path) == changed


def test_apply_writes_each_file_once(home, tmp_path, monkeypatch):
    call(tmp_path, "save", name="all on")
    serve.write_settings(
        home / ".claude", {"skill": {"alpha": False}, "plugin": {"kit@mkt": False}}
    )
    g = {h.id: h for h in ctx(tmp_path)[0]}["gemini-cli"]
    harnesses.set_skills(g, [s for s in ctx(tmp_path)[1] if s["name"] == "gamma"], on=False)
    items = profiles.load()
    items[0]["harnesses"]["claude-code"]["skills"]["beta"] = False
    items[0]["harnesses"]["gemini-cli"]["skills"]["delta"] = False
    profiles._store(items)

    writes: Counter = Counter()
    real = os.replace

    def counted(src, dst):
        writes[Path(dst).name if Path(dst).parent.name != "skill-atlas" else "profiles"] += 1
        real(src, dst)

    monkeypatch.setattr(os, "replace", counted)
    r = call(tmp_path, "apply", name="all on")
    assert r["changed"] == 5
    assert dict(writes) == {"settings.json": 2}
    claude = json.loads((home / ".claude" / "settings.json").read_text())
    assert claude["skillOverrides"] == {"beta": "off"}
    assert claude["enabledPlugins"] == {"kit@mkt": True}
    assert json.loads((home / ".gemini" / "settings.json").read_text())["skills"] == {
        "disabled": ["delta"]
    }


def test_selection_profile_turns_the_rest_off(home, tmp_path):
    picked = {"skills": ["alpha", "gamma"], "plugins": []}
    call(tmp_path, "save", name="only", picked=picked, rest_off=True)
    call(tmp_path, "save", name="these", picked=picked, harnesses=["claude-code"])
    states = {p["name"]: p["harnesses"] for p in profiles.load()}
    assert states["these"] == {"claude-code": {"skills": {"alpha": True}, "plugins": {}}}
    assert states["only"]["gemini-cli"] == {
        "skills": {"gamma": True, "delta": False},
        "plugins": {},
    }

    call(tmp_path, "apply", name="only")
    assert now(tmp_path) == {
        "claude-code": {"skills": {"alpha": True, "beta": False}, "plugins": {"kit@mkt": False}},
        "gemini-cli": {"skills": {"gamma": True, "delta": False}, "plugins": {}},
    }
    assert call(tmp_path, "preview", name="these")["changed"] == 0


def test_preview_reports_what_is_gone(home, tmp_path):
    states = {
        "claude-code": {"skills": {"alpha": False, "gone": True}, "plugins": {"old@mkt": True}},
        "codex": {"skills": {"x": False}},
    }
    p = call(tmp_path, "preview", states=states)
    assert p["changed"] == 1
    assert p["harnesses"]["claude-code"]["missing"] == ["gone", "old@mkt"]
    assert (
        p["harnesses"]["codex"] | {"found": False, "missing": ["x"], "on": []}
        == p["harnesses"]["codex"]
    )


def test_names_rename_delete_restore(home, tmp_path):
    call(tmp_path, "save", name="a")
    with pytest.raises(RuntimeError):
        call(tmp_path, "save", name="a")
    call(tmp_path, "save", name="a", replace=True)
    call(tmp_path, "save", name="b")
    with pytest.raises(ValueError):
        call(tmp_path, "save", name=" ")
    with pytest.raises(RuntimeError):
        call(tmp_path, "rename", name="a", to="b")
    call(tmp_path, "rename", name="a", to="c")
    gone = call(tmp_path, "delete", name="b")["deleted"]
    assert [p["name"] for p in profiles.load()] == ["c"]
    listed = call(tmp_path, "restore", profile=gone)["profiles"]
    assert [p["name"] for p in listed] == ["c", "b"]
    assert listed[1]["on"] == 5 and listed[1]["off"] == 0


def test_nothing_to_save(tmp_path):
    with pytest.raises(ValueError):
        call(tmp_path, "save", name="empty")


def test_profile_endpoints(server, server_root):
    skill(server_root / "skills", "demo")
    cfg = profiles.path().with_name("config.json")
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"config_roots": {"personal": str(server_root)}}))
    assert get(f"{server}/api/profiles")[1]["profiles"] == []
    code, data = post(f"{server}/api/profiles/save", {"name": "p"})
    assert code == 200 and data["saved"] == "p"
    (server_root / "settings.json").write_text(json.dumps({"skillOverrides": {"demo": "off"}}))
    code, data = post(f"{server}/api/profiles/apply", {"name": "p"})
    assert code == 200 and data["settings"]["claude-code"]["skillOverrides"] == {}
    assert data["previous"] == {"claude-code": {"skills": {"demo": False}, "plugins": {}}}
    assert post(f"{server}/api/profiles/apply", {"name": "nope"})[0] == 400
    assert post(f"{server}/api/profiles/save", {"name": "p"})[0] == 409
    assert post(f"{server}/api/profiles/other", {})[0] == 404


def test_codex_mixed_states_in_one_write(tmp_path):
    home = Path.home()
    for n in ("one", "two"):
        skill(home / ".codex" / "skills", n)
    h = {x.id: x for x in harnesses.detect({})}["codex"]
    recs = {s["name"]: s for s in scan(tmp_path)["skills"]}
    harnesses.set_skills(h, [recs["one"]], on=False)
    harnesses.set_skill_states(h, [(recs["one"], True), (recs["two"], False)])
    assert harnesses.off_names(h, list(recs.values())) == ["two"]
