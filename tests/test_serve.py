import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

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


@pytest.fixture
def server(tmp_path):
    serve.ROOTS.clear()
    serve.ROOTS["personal"] = tmp_path
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    serve.ROOTS.clear()


def post(url, body, token=serve.TOKEN):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"X-Atlas-Token": token}, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_token_required(server):
    assert post(f"{server}/api/toggle", {}, token="wrong")[0] == 403


def test_toggle_endpoint(server, tmp_path):
    body = {"root": "personal", "kind": "skill", "name": "demo", "on": False}
    code, data = post(f"{server}/api/toggle", body)
    assert code == 200
    assert data["skillOverrides"] == {"demo": "off"}


@pytest.mark.parametrize("names", [[], ["../etc"], ["a/b"], [".hidden"]])
def test_bad_names_refused(server, names):
    assert post(f"{server}/api/delete", {"names": names})[0] == 400


@pytest.mark.parametrize("paths", [[], ["/abs/SKILL.md"], ["a/../SKILL.md"], ["a/README.md"]])
def test_bad_paths_refused(server, paths):
    assert post(f"{server}/api/install", {"repo": "owner/repo", "paths": paths})[0] == 400


def get(url, token=serve.TOKEN):
    req = urllib.request.Request(url, headers={"X-Atlas-Token": token})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


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
