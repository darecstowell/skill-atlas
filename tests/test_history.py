import io
import json
import tarfile
import time

import pytest

from conftest import get
from skill_atlas import history, updates
from skill_atlas.scan import git_tree_hash


@pytest.fixture(autouse=True)
def cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    updates._cache.clear()
    updates._tarballs.clear()
    yield tmp_path / "cache" / "skill-atlas" / "history"
    updates.JOBS.clear()


def tarball(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"o-r-abc123/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


UPSTREAM = {
    "skills/demo/SKILL.md": "---\nname: demo\n---\nline one\nline two new\n",
    "skills/demo/new.txt": "fresh\n",
    "skills/other/SKILL.md": "not this one\n",
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "agents"
    skill = root / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\nline one\nline two\n")
    (skill / "old.txt").write_text("gone soon\n")
    entry = {
        "source": "o/r",
        "sourceType": "github",
        "skillPath": "skills/demo/SKILL.md",
        "skillFolderHash": git_tree_hash(skill),
        "updatedAt": "2026-01-01T00:00:00.000Z",
    }
    lock = root / ".skill-lock.json"
    lock.write_text(json.dumps({"version": 1, "skills": {"demo": entry}}))
    blob = tarball(UPSTREAM)
    monkeypatch.setattr(updates, "fetch_tarball", lambda repo, ref, max_age=0: blob)
    tree = {"sha": "root", "tree": [{"type": "tree", "path": "skills/demo", "sha": "newsha"}]}
    monkeypatch.setattr(updates, "fetch_tree", lambda repo, ref: tree)
    return root


def lock_entry(root):
    return json.loads((root / ".skill-lock.json").read_text())["skills"]["demo"]


def run_update(root):
    job = updates.start_update(["demo"], [root])
    for _ in range(200):
        if job["done"]:
            break
        time.sleep(0.01)
    assert job["items"]["demo"]["state"] == "done", job["items"]


def test_diff_folders():
    out = history.diff_folders(
        {"a.md": b"one\ntwo\n", "gone.md": b"x\n", "same": b"s", "img.png": b"\x89PNG\0a"},
        {"a.md": b"one\nthree\n", "new.md": b"n1\nn2\n", "same": b"s", "img.png": b"\x89PNG\0b"},
    )
    by = {f["path"]: f for f in out["files"]}
    assert set(by) == {"a.md", "gone.md", "new.md", "img.png"}
    assert (by["a.md"]["status"], by["a.md"]["added"], by["a.md"]["removed"]) == ("changed", 1, 1)
    assert "-two" in by["a.md"]["diff"] and "+three" in by["a.md"]["diff"]
    assert (by["new.md"]["status"], by["new.md"]["added"]) == ("added", 2)
    assert (by["gone.md"]["status"], by["gone.md"]["removed"]) == ("removed", 1)
    assert by["img.png"]["binary"] and "diff" not in by["img.png"]
    assert (out["added"], out["removed"]) == (3, 2)


def test_diff_caps_long_files(monkeypatch):
    monkeypatch.setattr(history, "MAX_FILE_LINES", 10)
    out = history.diff_folders({}, {"big.md": "\n".join(map(str, range(50))).encode()})
    f = out["files"][0]
    assert f["added"] == 50 and len(f["diff"]) == 10 and f["truncated"]


def test_diff_against_tarball(store):
    out = history.diff("demo", [store])
    by = {f["path"]: f["status"] for f in out["files"]}
    assert by == {"SKILL.md": "changed", "new.txt": "added", "old.txt": "removed"}
    assert out["repo"] == "o/r" and out["local_edits"] is False
    (store / "skills" / "demo" / "SKILL.md").write_text("mine\n")
    assert history.diff("demo", [store])["local_edits"] is True


def test_diff_untracked(store):
    with pytest.raises(ValueError):
        history.diff("nope", [store])


def test_update_takes_a_snapshot(store, cache_home):
    before = lock_entry(store)
    run_update(store)
    assert (store / "skills" / "demo" / "new.txt").exists()
    snaps = history.listing("demo")["snapshots"]
    assert len(snaps) == 1 and snaps[0]["reason"] == "update"
    snap = cache_home / "demo" / snaps[0]["id"]
    assert (snap / "skill" / "old.txt").read_text() == "gone soon\n"
    assert json.loads((snap / "meta.json").read_text())["entry"] == before
    assert lock_entry(store)["skillFolderHash"] == "newsha"


def test_prune_keeps_five(store):
    skill = store / "skills" / "demo"
    for _ in range(7):
        history.snapshot(skill, "demo", store / ".skill-lock.json", {})
    assert len(history.listing("demo")["snapshots"]) == history.KEEP


def test_rollback_restores_files_and_lock(store):
    before = lock_entry(store)
    run_update(store)
    snap_id = history.listing("demo")["snapshots"][0]["id"]
    out = history.rollback("demo", snap_id, [store])
    assert out["restored"] == snap_id
    skill = store / "skills" / "demo"
    assert (skill / "old.txt").exists() and not (skill / "new.txt").exists()
    assert lock_entry(store) == before
    assert not (store / "skills" / ".atlas-new-demo").exists()
    snaps = history.listing("demo")["snapshots"]
    assert [s["reason"] for s in snaps] == ["restore", "update"]


def test_rollback_rejects_bad_ids(store):
    with pytest.raises(ValueError):
        history.rollback("demo", "../../etc", [store])
    with pytest.raises(ValueError):
        history.rollback("demo", "20260101T000000000Z", [store])


def test_rollback_waits_for_a_running_update(store, monkeypatch):
    history.snapshot(store / "skills" / "demo", "demo", store / ".skill-lock.json", {"x": 1})
    snap_id = history.listing("demo")["snapshots"][0]["id"]
    monkeypatch.setitem(updates.JOBS, "busy", {"done": False})
    with pytest.raises(RuntimeError):
        history.rollback("demo", snap_id, [store])
    assert (store / "skills" / "demo" / "old.txt").exists()


def test_endpoints_refuse_bad_names(server):
    for route in ("diff", "history"):
        code, err = get(f"{server}/api/{route}?name=../x")
        assert code == 400 and err["error"] == "bad skill name"
