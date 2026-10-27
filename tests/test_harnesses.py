import json
import os
from pathlib import Path

import pytest

import harnesses
from scan import scan


def skill(folder: Path, name: str) -> Path:
    md = folder / name / "SKILL.md"
    md.parent.mkdir(parents=True)
    md.write_text(f"---\nname: {name}\ndescription: d\n---\nbody\n")
    return md


def by_id(roots=None):
    return {h.id: h for h in harnesses.detect(roots or {})}


def records(h, *mds):
    return [{"name": md.parent.name, "path": str(md), "harnesses": [h.id]} for md in mds]


def test_detect_needs_the_home_folder():
    home = Path.home()
    assert by_id() == {}
    (home / ".codex").mkdir()
    (home / ".cursor").mkdir()
    assert sorted(by_id()) == ["codex", "cursor"]
    two = by_id({"personal": home / ".claude", "work": home / ".claude-work"})
    assert two["claude-code:work"].label == "Claude Code · work"
    assert by_id({"main": home / ".claude"})["claude-code"].label == "Claude Code"


def test_scan_shares_one_folder_between_harnesses(tmp_path):
    home = Path.home()
    skill(home / ".agents" / "skills", "shared")
    skill(home / ".codex" / "skills", "codex-only")
    (home / ".claude").mkdir()
    (home / ".claude" / "skills").symlink_to(home / ".agents" / "skills")
    (home / ".cursor").mkdir()
    data = scan(tmp_path)
    loaded = {s["name"]: s["harnesses"] for s in data["skills"]}
    assert loaded == {
        "shared": ["claude-code", "codex", "cursor"],
        "codex-only": ["codex", "cursor"],
    }
    store = {s["name"]: s["store"] for s in data["skills"]}
    assert store == {"shared": True, "codex-only": False}
    assert data["store"] == str(home / ".agents")


def test_codex_switch_keeps_the_rest_of_the_file():
    home = Path.home()
    md = skill(home / ".agents" / "skills", "demo")
    other = skill(home / ".agents" / "skills", "other")
    (home / ".codex").mkdir()
    config = home / ".codex" / "config.toml"
    config.write_text(
        'model = "x"\n\n[[skills.config]]\nname = "other"\nenabled = false\n\n'
        '[tui]\ntheme = "dark"\n'
    )
    h = by_id()["codex"]
    assert harnesses.off_names(h, records(h, md, other)) == ["other"]

    harnesses.set_skills(h, records(h, md), on=False)
    assert harnesses.off_names(h, records(h, md, other)) == ["demo", "other"]
    harnesses.set_skills(h, records(h, md, other), on=True)
    assert harnesses.off_names(h, records(h, md, other)) == []
    text = config.read_text()
    assert 'model = "x"' in text and '[tui]\ntheme = "dark"' in text and "skills.config" not in text
    assert (home / ".codex" / "config.toml.atlas-bak").exists()


@pytest.mark.parametrize(
    ("hid", "folder", "file", "read"),
    [
        ("gemini-cli", ".gemini", "settings.json", lambda d: d["skills"]["disabled"]),
        ("copilot-cli", ".copilot", "settings.json", lambda d: d["disabledSkills"]),
    ],
)
def test_name_list_switches(hid, folder, file, read):
    home = Path.home()
    md = skill(home / folder / "skills", "demo")
    (home / folder / file).write_text(json.dumps({"keep": 1}))
    h = by_id()[hid]
    harnesses.set_skills(h, records(h, md), on=False)
    data = json.loads((home / folder / file).read_text())
    assert read(data) == ["demo"] and data["keep"] == 1
    assert harnesses.off_names(h, records(h, md)) == ["demo"]
    harnesses.set_skills(h, records(h, md), on=True)
    assert harnesses.off_names(h, records(h, md)) == []


def test_opencode_switch_beats_a_glob():
    xdg = Path(os.environ["XDG_CONFIG_HOME"])
    md = skill(xdg / "opencode" / "skills", "demo")
    config = xdg / "opencode" / "opencode.json"
    config.write_text(json.dumps({"permission": {"skill": {"*": "deny"}}}))
    h = by_id()["opencode"]
    assert harnesses.off_names(h, records(h, md)) == ["demo"]
    harnesses.set_skills(h, records(h, md), on=True)
    assert json.loads(config.read_text())["permission"]["skill"] == {"*": "deny", "demo": "allow"}
    assert harnesses.off_names(h, records(h, md)) == []


def test_no_switch_and_broken_files():
    home = Path.home()
    md = skill(home / ".cursor" / "skills", "demo")
    h = by_id()["cursor"]
    with pytest.raises(NotImplementedError):
        harnesses.set_skills(h, records(h, md), on=False)
    (home / ".gemini").mkdir()
    (home / ".gemini" / "settings.json").write_text("[1]")
    g = by_id()["gemini-cli"]
    with pytest.raises(ValueError):
        harnesses.set_skills(g, records(g, md), on=False)
