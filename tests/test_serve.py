import errno
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from conftest import get, post, raw

import serve


def test_skill_off_then_on(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"theme": "dark"}))

    serve.write_setting(tmp_path, "skill", ["demo"], on=False)
    assert json.loads(settings.read_text()) == {"theme": "dark", "skillOverrides": {"demo": "off"}}
    assert json.loads((tmp_path / "settings.json.atlas-bak").read_text()) == {"theme": "dark"}

    serve.write_setting(tmp_path, "skill", ["demo"], on=True)
    assert json.loads(settings.read_text()) == {"theme": "dark"}


def test_plugin_toggle(tmp_path):
    serve.write_setting(tmp_path, "plugin", ["p@m"], on=False)
    assert json.loads((tmp_path / "settings.json").read_text()) == {
        "enabledPlugins": {"p@m": False}
    }


def test_unknown_kind(tmp_path):
    with pytest.raises(ValueError):
        serve.write_setting(tmp_path, "theme", ["x"], on=True)


def test_token_required(server):
    assert post(f"{server}/api/toggle", {}, token="wrong")[0] == 403


def test_toggle_endpoint(server, tmp_path):
    body = {"root": "claude-code", "kind": "skill", "name": "demo", "on": False}
    code, data = post(f"{server}/api/toggle", body)
    assert code == 200
    assert data["skillOverrides"] == {"demo": "off"}


@pytest.mark.parametrize("names", [[], ["../etc"], ["a/b"], [".hidden"]])
def test_bad_names_refused(server, names):
    assert post(f"{server}/api/delete", {"names": names})[0] == 400


@pytest.mark.parametrize("paths", [[], ["/abs/SKILL.md"], ["a/../SKILL.md"], ["a/README.md"]])
def test_bad_paths_refused(server, paths):
    assert post(f"{server}/api/install", {"repo": "owner/repo", "paths": paths})[0] == 400


@pytest.fixture
def skill_md(tmp_path, monkeypatch):
    md = tmp_path / "demo" / "SKILL.md"
    md.parent.mkdir()
    md.write_text("---\nname: demo\n---\n# Demo\n")
    monkeypatch.setattr(serve, "scan", lambda repo: {"skills": [{"path": str(md)}]})
    return md


def test_skill_text(server, skill_md):
    q = urllib.parse.quote(str(skill_md))
    assert get(f"{server}/api/skill?path={q}") == (200, {"text": skill_md.read_text()})


def test_skill_unknown_path(server, skill_md, tmp_path):
    q = urllib.parse.quote(str(tmp_path / "other" / "SKILL.md"))
    assert get(f"{server}/api/skill?path={q}")[0] == 400


def test_skill_needs_token(server, skill_md):
    q = urllib.parse.quote(str(skill_md))
    assert get(f"{server}/api/skill?path={q}", token="wrong")[0] == 403


def test_repos(server, monkeypatch):
    seen = []

    def fetch(repos):
        seen.append(repos)
        return {r: {"stars": 1} for r in repos}

    monkeypatch.setattr(serve.assets, "fetch", fetch)
    body = {"repos": ["o/a", "https://github.com/o/a.git", "o/b"]}
    assert post(f"{server}/api/repos", body) == (200, {"o/a": {"stars": 1}, "o/b": {"stars": 1}})
    assert seen == [["o/a", "o/b"]]


def test_repos_bad(server, monkeypatch):
    monkeypatch.setattr(serve.assets, "fetch", lambda repos: {})
    assert post(f"{server}/api/repos", {"repos": ["not a repo"]})[0] == 400


def test_bind_skips_a_taken_port():
    taken = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    port = taken.server_address[1]
    try:
        server = serve.bind(port)
        assert server.server_address[1] != port
        server.server_close()
    finally:
        taken.server_close()


def test_toggle_writes_through_a_symlink(tmp_path):
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text("{}")
    root = tmp_path / "root"
    root.mkdir()
    (root / "settings.json").symlink_to(real)
    serve.write_setting(root, "skill", ["demo"], on=False)
    assert (root / "settings.json").is_symlink()
    assert json.loads(real.read_text()) == {"skillOverrides": {"demo": "off"}}


@pytest.mark.parametrize("text", ["{broken", "[]", '{"skillOverrides": "off"}'])
def test_toggle_refuses_a_bad_settings_file(tmp_path, text):
    (tmp_path / "settings.json").write_text(text)
    with pytest.raises(ValueError, match="Fix the file"):
        serve.write_setting(tmp_path, "skill", ["demo"], on=False)
    assert (tmp_path / "settings.json").read_text() == text


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs file modes")
def test_toggle_refuses_a_read_only_file(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    settings.chmod(0o444)
    with pytest.raises(ValueError, match="read-only"):
        serve.write_setting(tmp_path, "skill", ["demo"], on=False)
    assert settings.read_text() == "{}"


def test_unknown_api_is_json(server, monkeypatch):
    code, data, headers = raw(f"{server}/api/nope")
    assert (code, data["error"]) == (404, "unknown API call /api/nope")
    assert headers["X-Atlas-Build"] == serve.BUILD
    assert raw(f"{server}/api/nope", "POST", b"{}")[0] == 404


def test_stale_server_says_restart(server, monkeypatch):
    monkeypatch.setattr(serve, "BUILD", "older")
    code, data, _ = raw(f"{server}/api/new-thing")
    assert code == 404
    assert "./atlas" in data["error"] and data["server"] == {"build": "older", "stale": True}
    assert get(f"{server}/api/version")[1]["stale"] is True


def test_wrong_token_says_reload(server):
    assert "Reload the page" in get(f"{server}/api/data", token="old")[1]["error"]


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"[]", 400),
        (b"{broken", 400),
        (b'{"names": "demo"}', 400),
        (b'{"repos": "o/a"}', 400),
    ],
)
def test_bad_bodies_get_json_errors(server, body, code):
    path = "/api/repos" if b"repos" in body else "/api/delete"
    got = raw(f"{server}{path}", "POST", body)
    assert got[0] == code and "error" in got[1]


def test_huge_body_refused(server):
    import http.client

    host, port = server.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port))
    conn.putrequest("POST", "/api/toggle")
    conn.putheader("X-Atlas-Token", serve.TOKEN)
    conn.putheader("Content-Length", str(serve.MAX_BODY + 1))
    conn.endheaders()
    res = conn.getresponse()
    assert res.status == 413 and "too large" in json.loads(res.read())["error"]
    conn.close()


def test_handler_crash_is_a_json_500(server, monkeypatch):
    def boom(repo):
        raise ZeroDivisionError("bad luck")

    monkeypatch.setattr(serve, "scan", boom)
    code, data = get(f"{server}/api/data")
    assert code == 500 and "bad luck" in data["error"]


def test_reveal_without_a_file_manager(server, skill_md, monkeypatch):
    monkeypatch.setattr(serve.shutil, "which", lambda name: None)
    code, data = post(f"{server}/api/reveal", {"path": str(skill_md)})
    assert code == 501 and "not installed" in data["error"]


def test_no_config_root(server):
    serve.ROOTS.clear()
    code, data = get(f"{server}/api/updates")
    assert code == 400 and "config_roots" in data["error"]


def test_gone_job(server):
    code, data = get(f"{server}/api/jobs/abc")
    assert code == 404 and "restarted" in data["error"]


def test_closed_browser_is_quiet():
    class Gone:
        def write(self, b):
            raise BrokenPipeError

        def flush(self):
            raise BrokenPipeError

    h = serve.Handler.__new__(serve.Handler)
    h.wfile = Gone()
    h.request_version, h.requestline, h.command = "HTTP/1.1", "GET / HTTP/1.1", "GET"
    h.close_connection = False
    h._json(200, {"ok": True})
    assert h.close_connection


def test_bind_skips_a_reserved_port(monkeypatch):
    real = serve.ThreadingHTTPServer
    tried = []

    def fake(addr, handler):
        tried.append(addr[1])
        if len(tried) == 1:
            raise OSError(errno.EACCES, "reserved")
        return real(("127.0.0.1", 0), handler)

    monkeypatch.setattr(serve, "ThreadingHTTPServer", fake)
    server = serve.bind(5000)
    server.server_close()
    assert tried == [5000, 5001]


def test_texture_served(server):
    with urllib.request.urlopen(f"{server}/bg/paper.webp") as r:
        assert r.headers["Content-Type"] == "image/webp"
        assert r.read(4) == b"RIFF"
    for bad in ("/bg/..%2Fserve.py", "/bg/missing.webp", "/bg/serve.py"):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(server + bad)
        assert e.value.code == 404
