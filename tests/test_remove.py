import json

import pytest

from skill_atlas import remove


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
    monkeypatch.setattr(remove, "TRASH_INFO", None)
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


def test_no_trash_keeps_the_skill(home, monkeypatch):
    monkeypatch.setattr(remove, "TRASH", None)
    with pytest.raises(NotImplementedError, match="Trash"):
        remove.trash(["demo"], [home])
    assert (home / "skills" / "demo" / "SKILL.md").exists()


def test_freedesktop_trash(home, tmp_path, monkeypatch):
    files, info = tmp_path / "xdg" / "files", tmp_path / "xdg" / "info"
    monkeypatch.setattr(remove, "TRASH", files)
    monkeypatch.setattr(remove, "TRASH_INFO", info)
    remove.trash(["demo"], [home])
    (dest,) = files.iterdir()
    note = (info / f"{dest.name}.trashinfo").read_text()
    assert f"Path={home / 'skills' / 'demo'}" in note and "DeletionDate=" in note
    remove.undo()
    assert (home / "skills" / "demo").exists() and not list(info.iterdir())


def test_failed_move_puts_back_the_others(home, monkeypatch):
    (home / "skills" / "second").mkdir()
    (home / "skills" / "second" / "SKILL.md").write_text("x")
    real, calls = remove.shutil.move, []

    def move(src, dest):
        calls.append(src)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(src, dest)

    monkeypatch.setattr(remove.shutil, "move", move)
    with pytest.raises(OSError):
        remove.trash(["demo", "second"], [home])
    assert (home / "skills" / "demo" / "SKILL.md").exists()
    assert "demo" in json.loads((home / ".skill-lock.json").read_text())["skills"]


def test_broken_lock_stops_the_delete(home):
    (home / ".skill-lock.json").write_text("{broken")
    with pytest.raises(ValueError, match="Fix the file"):
        remove.trash(["demo"], [home])
    assert (home / "skills" / "demo").exists()
