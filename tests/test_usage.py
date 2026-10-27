import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import serve
import usage


def skill_line(skill, ts="2026-10-01T12:00:00.000Z", session="s1", cwd="/x/proj"):
    content = [{"type": "tool_use", "name": "Skill", "input": {"skill": skill}}]
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts,
            "sessionId": session,
            "cwd": cwd,
            "message": {"role": "assistant", "content": content},
        }
    )


def command_line(name, ts="2026-10-01T12:00:00.000Z", session="s1", cwd="/x/proj", kind="user"):
    body = f"<command-message>{name}</command-message>\n<command-name>/{name}</command-name>"
    return json.dumps(
        {
            "type": kind,
            "timestamp": ts,
            "sessionId": session,
            "cwd": cwd,
            "message": {"role": "user", "content": body},
        }
    )


def write(path: Path, *lines: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines))
    return path


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "CACHE", tmp_path / "out" / "usage-index.json")
    monkeypatch.setattr(
        usage, "_state", {"running": False, "done": 0, "total": 0, "finished": 0.0, "agg": None}
    )


def test_parse_skill_call():
    assert usage.parse_line(skill_line("show-me").encode()) == [
        ["2026-10-01T12:00:00.000Z", "s1", "show-me", "proj"]
    ]


def test_parse_typed_command():
    assert usage.parse_line(command_line("grilling").encode())[0][2] == "grilling"


def test_system_commands_are_skipped():
    assert usage.parse_line(command_line("clear", kind="system").encode()) == []


def test_unrelated_and_broken_lines():
    assert usage.parse_line(b'{"type":"user","message":{"content":"hi"}}') == []
    assert usage.parse_line(b'{"name":"Skill" broken') == []


def test_worktree_project_name():
    assert usage.project_of("/a/my-app/.claude/worktrees/fix-123") == "my-app"
    assert usage.project_of("/a/my-app") == "my-app"
    assert usage.project_of("") == ""


def test_dedupe_within_ten_minutes(tmp_path):
    f = write(
        tmp_path / "projects" / "p" / "a.jsonl",
        command_line("grilling", ts="2026-10-01T12:00:00Z"),
        skill_line("grilling", ts="2026-10-01T12:01:00Z"),
        skill_line("grilling", ts="2026-10-01T12:30:00Z"),
        skill_line("grilling", ts="2026-10-01T12:31:00Z", session="s2"),
    )
    files = usage.index([tmp_path], tmp_path / "cache.json")
    agg = usage.aggregate(files)
    s = agg["skills"]["grilling"]
    assert sum(s["days"].values()) == 3
    assert s["projects"] == {"proj": 3}
    assert s["last"] == "2026-10-01T12:31:00Z"
    assert agg["first_day"] == next(iter(s["days"]))
    assert str(f) in files


def test_incremental_append_reads_only_new_bytes(tmp_path, monkeypatch):
    f = write(tmp_path / "projects" / "p" / "a.jsonl", skill_line("one"))
    cache = tmp_path / "cache.json"
    first = usage.index([tmp_path], cache)[str(f)]
    assert first["offset"] == f.stat().st_size

    seen = []
    real = usage.read_events
    monkeypatch.setattr(usage, "read_events", lambda p, o: seen.append(o) or real(p, o))
    with f.open("a") as fh:
        fh.write(skill_line("two") + "\n" + skill_line("partial")[:30])
    files = usage.index([tmp_path], cache)
    assert seen == [first["offset"]]
    assert [e[2] for e in files[str(f)]["events"]] == ["one", "two"]
    assert files[str(f)]["offset"] < f.stat().st_size

    seen.clear()
    usage.index([tmp_path], cache)
    assert seen == []


def test_shrunk_file_is_reindexed(tmp_path):
    f = write(tmp_path / "projects" / "a.jsonl", skill_line("one"), skill_line("two"))
    cache = tmp_path / "cache.json"
    usage.index([tmp_path], cache)
    write(f, skill_line("three"))
    files = usage.index([tmp_path], cache)
    assert [e[2] for e in files[str(f)]["events"]] == ["three"]


def test_missing_file_is_dropped(tmp_path):
    f = write(tmp_path / "projects" / "a.jsonl", skill_line("one"))
    cache = tmp_path / "cache.json"
    usage.index([tmp_path], cache)
    f.unlink()
    assert usage.index([tmp_path], cache) == {}
    assert json.loads(cache.read_text())["files"] == {}


def test_counters_sum_across_roots(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    personal, work = home / ".claude", tmp_path / "work"
    personal.mkdir(parents=True)
    work.mkdir()
    (home / ".claude.json").write_text(
        json.dumps({"skillUsage": {"grilling": {"usageCount": 3, "lastUsedAt": 1000}}})
    )
    (work / ".claude.json").write_text(
        json.dumps(
            {
                "skillUsage": {
                    "grilling": {"usageCount": 2, "lastUsedAt": 5000},
                    "acli": {"usageCount": 1, "lastUsedAt": 2000},
                }
            }
        )
    )
    # A state file inside ~/.claude is not the one Claude Code reads.
    (personal / ".claude.json").write_text(json.dumps({"skillUsage": {"ghost": {"usageCount": 9}}}))
    c = usage.counters([personal, work])
    assert c["grilling"] == {"count": 5, "last": usage.iso_ms(5000)}
    assert c["acli"]["count"] == 1
    assert "ghost" not in c


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    write(tmp_path / "root" / "projects" / "p" / "a.jsonl", skill_line("show-me"))
    serve.ROOTS.clear()
    serve.ROOTS["personal"] = tmp_path / "root"
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    serve.ROOTS.clear()


def get(url, token=serve.TOKEN):
    req = urllib.request.Request(url, headers={"X-Atlas-Token": token})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_usage_endpoint(server):
    assert get(f"{server}/api/usage", token="wrong")[0] == 403
    code, data = get(f"{server}/api/usage")
    assert code == 200
    assert set(data) == {"status", "progress", "counters", "skills", "first_day", "today"}
    for _ in range(100):
        if data["status"] == "ready" and data["skills"]:
            break
        threading.Event().wait(0.05)
        usage._state["finished"] = 0.0
        data = get(f"{server}/api/usage")[1]
    assert data["skills"]["show-me"]["projects"] == {"proj": 1}
    assert data["progress"] == [1, 1]
