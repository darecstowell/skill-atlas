import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import pytest
from conftest import get

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
    # Other harnesses' logs must come from tmp_path, never from the real home.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for var in ("CODEX_HOME", "GEMINI_CLI_HOME", "COPILOT_HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(var, str(tmp_path / "harness" / var))
    monkeypatch.setattr(usage, "CACHE", tmp_path / "out" / "usage-index.json")
    monkeypatch.setattr(
        usage,
        "_state",
        {"running": False, "done": 0, "total": 0, "finished": 0.0, "agg": None, "error": None},
    )


def test_parse_skill_call():
    assert usage.parse_line(skill_line("show-me").encode()) == [
        ["2026-10-01T12:00:00.000Z", "s1", "show-me", "proj", "claude-code"]
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
    assert s["harnesses"] == {"claude-code": 3}
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
    monkeypatch.setattr(usage, "read_events", lambda p, o, *a: seen.append(o) or real(p, o, *a))
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
def server_root(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    write(tmp_path / "root" / "projects" / "p" / "a.jsonl", skill_line("show-me"))
    return tmp_path / "root"


def test_usage_endpoint(server):
    assert get(f"{server}/api/usage", token="wrong")[0] == 403
    code, data = get(f"{server}/api/usage")
    assert code == 200
    assert set(data) == {
        "status",
        "error",
        "progress",
        "counters",
        "skills",
        "first_day",
        "today",
    }
    for _ in range(100):
        if data["status"] == "ready" and data["skills"]:
            break
        threading.Event().wait(0.05)
        usage._state["finished"] = 0.0
        data = get(f"{server}/api/usage")[1]
    assert data["skills"]["show-me"]["projects"] == {"proj": 1}
    assert data["progress"] == [1, 1]


def test_non_object_line():
    assert usage.parse_line(b'["Skill"]') == []


def test_unwritable_cache_still_counts(tmp_path):
    write(tmp_path / "projects" / "a.jsonl", skill_line("one"))
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    files = usage.index([tmp_path], blocker / "cache.json")
    assert [e[2] for f in files.values() for e in f["events"]] == ["one"]


@pytest.mark.parametrize(
    "cache",
    ["[]", '{"files": []}', '{"files": {"x": {"size": "1"}}}', '{"files": {"x": {"events": 3}}}'],
)
def test_odd_cache_is_ignored(tmp_path, cache):
    write(tmp_path / "projects" / "a.jsonl", skill_line("one"))
    (tmp_path / "cache.json").write_text(cache)
    files = usage.index([tmp_path], tmp_path / "cache.json")
    assert [e[2] for f in files.values() for e in f["events"]] == ["one"]


def test_replaced_file_is_read_from_the_start(tmp_path):
    f = write(tmp_path / "projects" / "a.jsonl", skill_line("one"))
    cache = tmp_path / "cache.json"
    usage.index([tmp_path], cache)
    new = write(tmp_path / "new.jsonl", skill_line("two"), skill_line("three"))
    new.replace(f)
    files = usage.index([tmp_path], cache)
    assert [e[2] for e in files[str(f)]["events"]] == ["two", "three"]


def test_long_pass_saves_checkpoints(tmp_path, monkeypatch):
    for n in range(3):
        write(tmp_path / "projects" / f"{n}.jsonl", skill_line(f"s{n}"))
    saves = []
    monkeypatch.setattr(usage, "CHECKPOINT_SECONDS", -1)
    monkeypatch.setattr(usage, "save", lambda cache, files: saves.append(len(files)))
    usage.index([tmp_path], tmp_path / "cache.json")
    assert saves == [1, 2, 3, 3]


def test_counters_odd_values(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / ".claude.json").write_text(
        json.dumps({"skillUsage": {"a": {"usageCount": "many", "lastUsedAt": None}, "b": 3}})
    )
    assert usage.counters([root]) == {"a": {"count": 0, "last": None}}


def test_failed_pass_reports_an_error(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(usage, "index", boom)
    usage._run([tmp_path])
    snap = usage.snapshot([])
    assert "disk gone" in snap["error"] and not usage._state["running"]


def jl(*records) -> str:
    return "".join(json.dumps(r) + "\n" for r in records)


def codex_log(tmp_path, *records) -> Path:
    f = tmp_path / "harness" / "CODEX_HOME" / "sessions" / "2026" / "10" / "01"
    f = f / "rollout-2026-10-01T12-00-00-01a15ac4-3386-71c2-ab6e-5410088c6fce.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(jl(*records))
    return f


def codex_call(cmd, ts="2026-10-01T12:00:00Z", name="exec"):
    payload = {"type": "custom_tool_call", "name": name, "input": cmd}
    return {"timestamp": ts, "type": "response_item", "payload": payload}


CODEX_META = {
    "timestamp": "2026-10-01T11:59:00Z",
    "type": "session_meta",
    "payload": {"id": "sess-1", "cwd": "/w/app", "base_instructions": {"text": "x/SKILL.md"}},
}


def events(files):
    return [e for f in files.values() for e in f["events"]]


def test_codex_skill_reads_and_mentions(tmp_path):
    mention = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "<skill>\n<name>grilling</name>\n</skill>"}],
    }
    codex_log(
        tmp_path,
        CODEX_META,
        codex_call('tools.exec_command({cmd:"cat /h/.codex/skills/imagegen/SKILL.md"})'),
        codex_call("*** Begin Patch\n+++ /h/skills/new/SKILL.md", name="apply_patch"),
        {"timestamp": "2026-10-01T12:05:00Z", "type": "response_item", "payload": mention},
        {"timestamp": "2026-10-01T12:06:00Z", "type": "turn_context", "payload": {"cwd": "/w/b"}},
        {
            "timestamp": "2026-10-01T12:07:00Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell",
                "arguments": json.dumps({"command": ["sed", "-n", "1p", "a/acli/SKILL.md"]}),
            },
        },
    )
    assert events(usage.index([], tmp_path / "cache.json")) == [
        ["2026-10-01T12:00:00Z", "sess-1", "imagegen", "app", "codex"],
        ["2026-10-01T12:05:00Z", "sess-1", "grilling", "app", "codex"],
        ["2026-10-01T12:07:00Z", "sess-1", "acli", "b", "codex"],
    ]


def test_codex_append_keeps_session_context(tmp_path):
    f = codex_log(tmp_path, CODEX_META, codex_call("cat s/one/SKILL.md"))
    cache = tmp_path / "cache.json"
    usage.index([], cache)
    with f.open("a") as fh:
        fh.write(jl(codex_call("cat s/two/SKILL.md", ts="2026-10-01T13:00:00Z")))
    assert [e[1:4] for e in events(usage.index([], cache))] == [
        ["sess-1", "one", "app"],
        ["sess-1", "two", "app"],
    ]


def test_codex_session_falls_back_to_file_name(tmp_path):
    codex_log(tmp_path, codex_call("cat s/one/SKILL.md"))
    assert events(usage.index([], tmp_path / "cache.json"))[0][1] == (
        "01a15ac4-3386-71c2-ab6e-5410088c6fce"
    )


def gemini_dir(tmp_path, project_id="dev") -> Path:
    d = tmp_path / "harness" / "GEMINI_CLI_HOME" / ".gemini" / "tmp" / project_id / "chats"
    d.mkdir(parents=True)
    return d


def activate(name, call_id="c1", status="success", ts="2026-10-01T12:00:00Z"):
    call = {"id": call_id, "name": "activate_skill", "args": {"name": name}, "status": status}
    return {"id": "m1", "timestamp": ts, "type": "gemini", "toolCalls": [call]}


def test_gemini_jsonl_counts_each_call_once(tmp_path):
    d = gemini_dir(tmp_path)
    (d.parent / ".project_root").write_text("/w/my-app\n")
    (d / "session-2026-10-01T12-00-abc.jsonl").write_text(
        jl(
            {"sessionId": "g-1", "projectHash": "h", "kind": "main"},
            activate("grilling", status="executing"),
            activate("grilling"),
            {"$set": {"lastUpdated": "2026-10-01T12:00:01Z"}},
            activate("grilling"),
            activate("acli", call_id="c2", status="error"),
            {"id": "m2", "timestamp": "2026-10-01T12:00:00Z", "type": "user", "content": "hi"},
        )
    )
    assert events(usage.index([], tmp_path / "cache.json")) == [
        ["2026-10-01T12:00:00Z", "g-1", "grilling", "my-app", "gemini-cli"]
    ]


def test_gemini_json_and_hashed_project(tmp_path):
    path = "/w/hashed-app"
    d = gemini_dir(tmp_path, hashlib.sha256(path.encode()).hexdigest())
    (d.parent.parent.parent / "projects.json").write_text(json.dumps({"projects": {path: "x"}}))
    chat = {"sessionId": "g-2", "messages": [activate("one"), activate("two", call_id="c2")]}
    (d / "session-2026-10-01T12-00-def.json").write_text(json.dumps(chat))
    cache = tmp_path / "cache.json"
    assert [e[2:] for e in events(usage.index([], cache))] == [
        ["one", "hashed-app", "gemini-cli"],
        ["two", "hashed-app", "gemini-cli"],
    ]
    chat["messages"] = chat["messages"][:1]
    (d / "session-2026-10-01T12-00-def.json").write_text(json.dumps(chat, indent=1))
    assert [e[2] for e in events(usage.index([], cache))] == ["one"]


def test_gemini_unknown_hash_has_no_project(tmp_path):
    d = gemini_dir(tmp_path, "f" * 64)
    (d / "session-x.json").write_text(json.dumps({"messages": [activate("one")]}))
    assert events(usage.index([], tmp_path / "cache.json"))[0][3] == ""


def test_copilot_skill_invoked(tmp_path):
    f = tmp_path / "harness" / "COPILOT_HOME" / "session-state" / "cp-1" / "events.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text(
        jl(
            {"type": "session.start", "data": {"context": {"cwd": "/w/cop-app"}}},
            {
                "type": "skill.invoked",
                "timestamp": "2026-10-01T12:00:00Z",
                "data": {"name": "acli", "path": "/s/acli/SKILL.md", "pluginName": "p"},
            },
            {"type": "skill.invoked", "data": {"name": "no-time"}},
            {"type": "user.message", "data": {"content": "skill.invoked"}},
        )
    )
    assert events(usage.index([], tmp_path / "cache.json")) == [
        ["2026-10-01T12:00:00Z", "cp-1", "acli", "cop-app", "copilot-cli"]
    ]


def opencode_db(tmp_path, parts) -> Path:
    db = tmp_path / "harness" / "XDG_DATA_HOME" / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE session (id TEXT, directory TEXT)")
    con.execute("CREATE TABLE part (id TEXT, session_id TEXT, time_created INTEGER, data TEXT)")
    con.execute("INSERT INTO session VALUES ('ses_1', '/w/oc-app')")
    con.executemany(
        "INSERT INTO part VALUES (?, 'ses_1', 1790000000000, ?)",
        [(str(i), p if isinstance(p, str) else json.dumps(p)) for i, p in enumerate(parts)],
    )
    con.commit()
    con.close()
    return db


def oc_part(name, status="completed", **state):
    return {
        "type": "tool",
        "tool": "skill",
        "state": {"status": status, "input": {"name": name}, **state},
    }


def test_opencode_database(tmp_path, monkeypatch):
    db = opencode_db(
        tmp_path,
        [
            oc_part("grilling", time={"start": 1790000100000}),
            oc_part("acli"),
            oc_part("broken", status="error"),
            {"type": "tool", "tool": "bash", "state": {"input": {"name": "skill"}}},
            "not json skill",
            "[1, 2, 3]",
        ],
    )
    cache = tmp_path / "cache.json"
    assert events(usage.index([], cache)) == [
        [usage.iso_ms(1790000100000), "ses_1", "grilling", "oc-app", "opencode"],
        [usage.iso_ms(1790000000000), "ses_1", "acli", "oc-app", "opencode"],
    ]
    calls = []
    real = usage.read_opencode
    monkeypatch.setitem(usage.WHOLE_READERS, "opencode", lambda p, c: calls.append(p) or real(p, c))
    usage.index([], cache)
    assert calls == []
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO part VALUES ('9', 'ses_1', 1790000200000, ?)", (json.dumps(oc_part("new")),)
    )
    con.commit()
    con.close()
    assert [e[2] for e in events(usage.index([], cache))] == ["grilling", "acli", "new"]
    assert calls == [db]


def test_opencode_is_opened_read_only(tmp_path, monkeypatch):
    db = opencode_db(tmp_path, [oc_part("one")])
    uris = []
    real = sqlite3.connect
    monkeypatch.setattr(usage.sqlite3, "connect", lambda u, **k: uris.append(u) or real(u, **k))
    usage.index([], tmp_path / "cache.json")
    assert uris == [f"{db.resolve().as_uri()}?mode=ro"]


def test_odd_harness_file_does_not_stop_the_pass(tmp_path):
    db = tmp_path / "harness" / "XDG_DATA_HOME" / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True)
    db.write_text("not a database")
    write(tmp_path / "projects" / "a.jsonl", skill_line("one"))
    files = usage.index([tmp_path], tmp_path / "cache.json")
    assert [e[2] for e in events(files)] == ["one"]


def test_version_one_cache_is_upgraded(tmp_path, monkeypatch):
    f = write(tmp_path / "projects" / "a.jsonl", skill_line("one"))
    st = f.stat()
    entry = {
        "size": st.st_size,
        "mtime": st.st_mtime_ns,
        "ino": st.st_ino,
        "offset": st.st_size,
        "events": [["2026-10-01T12:00:00Z", "s1", "cached", "proj"]],
    }
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"version": 1, "files": {str(f): entry}}))
    monkeypatch.setattr(usage, "read_events", lambda *a: pytest.fail("read again"))
    files = usage.index([tmp_path], cache)
    assert events(files) == [["2026-10-01T12:00:00Z", "s1", "cached", "proj", "claude-code"]]
    assert json.loads(cache.read_text())["version"] == 2
    assert usage.aggregate(files)["skills"]["cached"]["harnesses"] == {"claude-code": 1}


def test_harness_breakdown_and_separate_dedupe():
    ts = "2026-10-01T12:00:00Z"
    files = {
        "a": {"events": [[ts, "s", "grilling", "p", "codex"], [ts, "s", "grilling", "p"]]},
        "b": {"events": [["2026-10-01T12:01:00+00:00", "s", "grilling", "", "opencode"]]},
    }
    s = usage.aggregate(files)["skills"]["grilling"]
    assert s["harnesses"] == {"codex": 1, "claude-code": 1, "opencode": 1}
    assert s["last"] == "2026-10-01T12:01:00+00:00"
