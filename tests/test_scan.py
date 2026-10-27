import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scan import as_list, git_tree_hash, parse_frontmatter, scan


def test_frontmatter_scalars_lists_and_maps():
    fm, body = parse_frontmatter(
        "---\n"
        'name: "demo"\n'
        "description: Does a thing\n"
        "allowed-tools:\n  - Read\n  - Bash\n"
        "metadata:\n  version: 1.2\n"
        "---\n# Body\n"
    )
    assert fm["name"] == "demo"
    assert fm["description"] == "Does a thing"
    assert fm["allowed-tools"] == ["Read", "Bash"]
    assert fm["metadata"] == {"version": "1.2"}
    assert body.strip() == "# Body"


def test_frontmatter_missing():
    fm, body = parse_frontmatter("# Just a body\n")
    assert fm == {}
    assert "Just a body" in body


def test_as_list():
    assert as_list(None) == []
    assert as_list(["a", "b"]) == ["a", "b"]
    assert as_list("a, b") == ["a", "b"]


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_git_tree_hash_matches_git(tmp_path):
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: skill\n---\n")
    run = skill / "scripts" / "run.sh"
    run.write_text("#!/bin/sh\necho hi\n")
    run.chmod(0o755)

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git("add", ".")
    assert git_tree_hash(skill) == git("rev-parse", f"{git('write-tree')}:skill")


def test_read_json_shapes(tmp_path):
    from scan import read_json, read_json_strict

    f = tmp_path / "f.json"
    assert read_json(f) == {} and read_json_strict(f) == {}
    f.write_text("[1, 2]")
    assert read_json(f) == {}
    with pytest.raises(ValueError, match="JSON object"):
        read_json_strict(f)
    f.write_text("{broken")
    assert read_json(f) == {}
    with pytest.raises(ValueError, match="Fix the file"):
        read_json_strict(f)


def test_frontmatter_with_bom_and_crlf():
    fm, _ = parse_frontmatter("﻿---\r\nname: demo\r\ndescription: x\r\n---\r\nbody")
    assert fm == {"name": "demo", "description": "x"}


def test_git_tree_hash_symlink_loop(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("x\n")
    (skill / "loop").symlink_to(".")
    got = git_tree_hash(skill)
    if shutil.which("git"):

        def git(*args):
            return subprocess.run(
                ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
            ).stdout.strip()

        git("init", "-q")
        git("add", ".")
        assert got == git("rev-parse", f"{git('write-tree')}:skill")


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return home


def repo_with(tmp_path, config) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "config.json").write_text(config if isinstance(config, str) else json.dumps(config))
    return repo


def skill(root, name, text="---\nname: {name}\ndescription: d\n---\nbody\n"):
    md = root / "skills" / name / "SKILL.md"
    md.parent.mkdir(parents=True)
    if isinstance(text, bytes):
        md.write_bytes(text)
    else:
        md.write_text(text.format(name=name))
    return md


@pytest.mark.parametrize(
    "config",
    [
        "{not json",
        "[]",
        {"config_roots": ["~/.claude"], "project_roots": "~/nowhere", "project_scan_depth": "x"},
        {"config_roots": {"main": "~/.claude", "gone": "~/missing"}, "project_roots": [3]},
    ],
)
def test_scan_odd_config(tmp_path, home, config):
    skill(home / ".claude", "demo")
    data = scan(repo_with(tmp_path, config))
    assert data["config_roots"] == {"main": str(home / ".claude")}
    assert [s["name"] for s in data["skills"]] == ["demo"]


def test_scan_no_roots(tmp_path, home):
    data = scan(repo_with(tmp_path, {}))
    assert data["config_roots"] == {} and data["skills"] == []


def test_scan_claude_config_dir(tmp_path, home, monkeypatch):
    work = tmp_path / ".claude-work"
    skill(work, "only-here")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(work))
    data = scan(repo_with(tmp_path, {}))
    assert data["config_roots"] == {"claude-work": str(work)}
    assert [s["name"] for s in data["skills"]] == ["only-here"]


def test_scan_odd_files(tmp_path, home):
    root = home / ".claude"
    skill(root, "latin", b"---\nname: latin\ndescription: caf\xe9\n---\n")
    skill(root, "fine")
    (root / "skills" / "broken").mkdir()
    (root / "skills" / "broken" / "SKILL.md").symlink_to(tmp_path / "nowhere")
    (root / "settings.json").write_text("[]")
    data = scan(repo_with(tmp_path, {}))
    assert {s["name"]: s["description"] for s in data["skills"]} == {
        "fine": "d",
        "latin": "caf�",
    }
    assert data["settings"]["main"]["skillOverrides"] == {}


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs file modes")
def test_scan_skips_unreadable_skill(tmp_path, home):
    md = skill(home / ".claude", "secret")
    skill(home / ".claude", "fine")
    md.chmod(0)
    try:
        data = scan(repo_with(tmp_path, {}))
    finally:
        md.chmod(0o644)
    assert [s["name"] for s in data["skills"]] == ["fine"]


def test_config_lookup_order(tmp_path, monkeypatch):
    from scan import config_path

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.delenv("SKILL_ATLAS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config_path(repo) == repo / "config.json"
    user = tmp_path / "xdg" / "skill-atlas" / "config.json"
    user.parent.mkdir(parents=True)
    user.write_text("{}")
    assert config_path(repo) == user
    monkeypatch.setenv("SKILL_ATLAS_CONFIG", str(tmp_path / "mine.json"))
    assert config_path(repo) == tmp_path / "mine.json"


def test_init_writes_detected_roots(tmp_path, monkeypatch):
    from scan import write_user_config

    home = tmp_path / "home"
    for d in (".claude", ".claude-work", ".claude-none", ".claude-STALE-archive"):
        (home / d).mkdir(parents=True)
    for d in (".claude-work", ".claude-STALE-archive"):
        (home / d / "settings.json").write_text("{}")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    path = write_user_config()
    cfg = json.loads(path.read_text())
    assert cfg["config_roots"] == {"main": "~/.claude", "work": "~/.claude-work"}
    assert cfg["project_roots"] == []
    with pytest.raises(FileExistsError):
        write_user_config()
    assert write_user_config(force=True) == path


@pytest.mark.parametrize(
    ("flags", "invocation"),
    [
        ("", "auto + manual"),
        ("disable-model-invocation: true\n", "manual only"),
        ("user-invocable: false\n", "auto only"),
        ("disable-model-invocation: true\nuser-invocable: false\n", "neither"),
    ],
)
def test_scan_invocation_flags(tmp_path, home, flags, invocation):
    skill(home / ".claude", "demo", "---\nname: demo\ndescription: d\n" + flags + "---\nbody\n")
    (rec,) = scan(repo_with(tmp_path, {}))["skills"]
    assert rec["invocation"] == invocation
