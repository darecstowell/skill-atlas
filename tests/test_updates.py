import json
import subprocess
import urllib.error
from email.message import Message

import pytest

from skill_atlas import updates
from skill_atlas.updates import folder_of, folder_sha, parse_repo


@pytest.mark.parametrize(
    "text",
    [
        "owner/repo",
        "https://github.com/owner/repo",
        "https://github.com/owner/repo.git",
        "https://github.com/owner/repo/",
        "git@github.com:owner/repo.git",
    ],
)
def test_parse_repo_forms(text):
    assert parse_repo(text) == "owner/repo"


@pytest.mark.parametrize("text", ["", "repo", "https://gitlab.com/owner/repo", "a/b/c"])
def test_parse_repo_rejects(text):
    with pytest.raises(ValueError):
        parse_repo(text)


def test_folder_sha():
    tree = {
        "sha": "root",
        "tree": [
            {"type": "tree", "path": "skills/demo", "sha": "abc"},
            {"type": "blob", "path": "skills/demo/SKILL.md", "sha": "def"},
        ],
    }
    assert folder_of("skills/demo/SKILL.md") == "skills/demo"
    assert folder_sha(tree, "skills/demo/SKILL.md") == "abc"
    assert folder_sha(tree, "SKILL.md") == "root"
    assert folder_sha(tree, "skills/gone/SKILL.md") is None


@pytest.fixture
def no_gh(monkeypatch):
    monkeypatch.setattr(updates.shutil, "which", lambda name: None)


def test_rate_limit_is_named(monkeypatch, no_gh):
    headers = Message()
    headers["X-RateLimit-Remaining"] = "0"

    def urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "rate", headers, None)

    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)
    assert updates.fetch_tree("o/r", "HEAD") is None
    assert "rate limit" in updates.tree_error("o/r")


def test_offline_is_named(monkeypatch, no_gh):
    def urlopen(req, timeout):
        raise urllib.error.URLError(OSError("nodename nor servname provided"))

    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)
    assert updates.fetch_tree("o/off", "HEAD") is None
    assert updates.tree_error("o/off").endswith("no connection to GitHub")


def test_gh_timeout_skips_https(monkeypatch):
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/bin/gh")

    def run(*a, **k):
        assert k["timeout"] == updates.TREE_TIMEOUT
        raise subprocess.TimeoutExpired("gh", k["timeout"])

    def urlopen(*a, **k):
        raise AssertionError("no HTTPS after a timeout")

    monkeypatch.setattr(updates.subprocess, "run", run)
    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)
    assert updates.fetch_tree("o/slow", "HEAD") is None
    assert "in time" in updates.tree_error("o/slow")


def test_bad_tree_json(monkeypatch):
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/bin/gh")
    monkeypatch.setattr(
        updates.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="<html>", stderr=""),
    )
    assert updates.fetch_tree("o/r", "HEAD") is None


def test_lock_write_keeps_symlink_and_refuses_bad_json(tmp_path):
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"version": 1, "skills": {"a": {}}, "other": 1}))
    lock = tmp_path / ".skill-lock.json"
    lock.symlink_to(real)
    updates.write_lock_entries(lock, {"b": {"x": 1}})
    assert lock.is_symlink()
    assert json.loads(real.read_text()) == {
        "version": 1,
        "skills": {"a": {}, "b": {"x": 1}},
        "other": 1,
    }
    real.write_text("{broken")
    with pytest.raises(ValueError):
        updates.write_lock_entries(lock, {"c": {}})
    assert real.read_text() == "{broken"


def test_check_with_no_roots():
    updates._cache.clear()
    assert updates.check([], refresh=True)["skills"] == {}
    updates._cache.clear()


@pytest.mark.parametrize(
    "path, ok",
    [
        ("SKILL.md", True),
        ("skills/demo/SKILL.md", True),
        ("/etc/SKILL.md", False),
        ("skills/../../SKILL.md", False),
        ("skills/demo/README.md", False),
    ],
)
def test_safe_skill_path(path, ok):
    assert updates.safe_skill_path(path) is ok
