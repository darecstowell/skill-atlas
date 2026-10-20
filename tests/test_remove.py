import json

import pytest

import remove


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / ".claude"
    skills = root / "skills"
    (skills / "demo").mkdir(parents=True)
    (skills / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n")
    (root / ".skill-lock.json").write_text(json.dumps({"skills": {"demo": {"source": "o/r"}}}))
    (root / "settings.json").write_text(json.dumps({"skillOverrides": {"demo": "off"}}))
    trash = tmp_path / "Trash"
    trash.mkdir()
    monkeypatch.setattr(remove, "TRASH", trash)
    return root


def test_trash_and_undo(home):
    assert remove.trash(["demo"], [home]) == {"trashed": ["demo"]}
    assert not (home / "skills" / "demo").exists()
    assert json.loads((home / ".skill-lock.json").read_text())["skills"] == {}
    assert json.loads((home / "settings.json").read_text())["skillOverrides"] == {}

    assert remove.undo() == {"restored": ["demo"]}
    assert (home / "skills" / "demo" / "SKILL.md").exists()
    assert "demo" in json.loads((home / ".skill-lock.json").read_text())["skills"]
    assert json.loads((home / "settings.json").read_text())["skillOverrides"] == {"demo": "off"}


def test_refuses_non_skill(home):
    (home / "skills" / "notes").mkdir()
    with pytest.raises(ValueError):
        remove.trash(["notes"], [home])


def test_undo_with_nothing():
    remove._last.clear()
    with pytest.raises(ValueError):
        remove.undo()
