import json
import os
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest

from conftest import get
from skill_atlas import remove, serve, updates
from skill_atlas.core.api import AtlasAPI
from skill_atlas.core.atlas import Atlas, config_roots, default
from skill_atlas.scan import user_config_path

ROOT = Path(__file__).resolve().parent.parent


def skill(folder: Path, name: str) -> Path:
    md = folder / name / "SKILL.md"
    md.parent.mkdir(parents=True)
    md.write_text(f"---\nname: {name}\ndescription: d\n---\nbody\n")
    return md


@pytest.fixture
def claude() -> Path:
    """A Claude Code root in the test home, with the skills alpha and beta, named in the config."""
    root = Path.home() / ".claude"
    for name in ("alpha", "beta"):
        skill(root / "skills", name)
    (root / "settings.json").write_text(json.dumps({"theme": "dark"}))
    cfg = user_config_path()
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"config_roots": {"main": str(root)}}))
    return root


@pytest.fixture
def atlas(claude: Path, tmp_path: Path) -> Atlas:
    return Atlas({"main": claude}, tmp_path)


def test_atlas_is_an_atlas_api(tmp_path: Path) -> None:
    api: AtlasAPI = Atlas({}, tmp_path)
    assert callable(api.data)


def test_mypy_checks_this_file(monkeypatch: pytest.MonkeyPatch) -> None:
    mypy = pytest.importorskip("mypy.api")
    monkeypatch.setenv("MYPYPATH", os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests")]))
    out, err, code = mypy.run(["--config-file", str(ROOT / "pyproject.toml"), __file__])
    assert code == 0, out + err


def test_default_reads_the_config_roots(claude: Path, tmp_path: Path) -> None:
    assert config_roots(tmp_path) == {"main": claude}
    assert default().config_roots == {"main": claude}


def test_toggle_off_then_on(atlas: Atlas, claude: Path) -> None:
    state = atlas.toggle("claude-code", "skill", ["alpha"], on=False)
    assert state["skillOverrides"] == {"alpha": "off"}
    settings = json.loads((claude / "settings.json").read_text())
    assert settings == {"theme": "dark", "skillOverrides": {"alpha": "off"}}
    assert atlas.toggle("claude-code", "skill", ["alpha"], on=True)["skillOverrides"] == {}
    assert json.loads((claude / "settings.json").read_text()) == {"theme": "dark"}


def test_toggle_refuses_an_unknown_harness(atlas: Atlas) -> None:
    with pytest.raises(ValueError, match="unknown harness"):
        atlas.toggle("nope", "skill", ["alpha"], on=False)


def test_toggle_in_a_harness_with_its_own_switch(atlas: Atlas) -> None:
    skill(Path.home() / ".gemini" / "skills", "gamma")
    assert atlas.toggle("gemini-cli", "skill", ["gamma"], on=False)["off"] == ["gamma"]
    with pytest.raises(ValueError, match="no plugin switch"):
        atlas.toggle("gemini-cli", "plugin", ["p@m"], on=False)
    with pytest.raises(ValueError, match="does not load"):
        atlas.toggle("gemini-cli", "skill", ["alpha"], on=False)


def test_only_scanned_paths_are_reachable(atlas: Atlas, claude: Path, tmp_path: Path) -> None:
    md = claude / "skills" / "alpha" / "SKILL.md"
    assert atlas.skill_text(str(md)) == md.read_text()
    other = tmp_path / "secret.md"
    other.write_text("secret\n")
    for call in (atlas.skill_text, atlas.security, atlas.reveal):
        with pytest.raises(ValueError, match="unknown skill path"):
            call(str(other))
    with pytest.raises(ValueError, match="unknown skill path"):
        atlas.compare(str(md), str(other))


def test_scanned_record_reuses_the_last_scan(tmp_path: Path) -> None:
    calls: list[Path] = []

    def scanner(repo: Path) -> dict:
        calls.append(repo)
        return {"skills": [{"path": "/a/SKILL.md"}]}

    atlas = Atlas({}, tmp_path, scanner=scanner)
    atlas.page_scan()
    assert atlas.scanned_record("/a/SKILL.md") == {"path": "/a/SKILL.md"}
    assert calls == [tmp_path]
    with pytest.raises(ValueError):
        atlas.scanned_record("/b/SKILL.md")
    assert len(calls) == 2


@pytest.mark.parametrize("name", ["", "../x", "a/b", ".hidden", "-flag"])
def test_bad_skill_names_are_refused(
    atlas: Atlas, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remove, "trash", lambda *a: pytest.fail("trashed"))
    monkeypatch.setattr(updates, "start_update", lambda *a: pytest.fail("updated"))
    for one in (atlas.history, atlas.diff):
        with pytest.raises(ValueError, match="bad skill name"):
            one(name)
    with pytest.raises(ValueError, match="bad skill name"):
        atlas.snapshot_diff(name, "20260101T000000000Z")
    for many in (atlas.delete, atlas.update):
        for names in ([name], ["alpha", name], []):
            with pytest.raises(ValueError, match="bad skill names"):
                many(names)


@pytest.mark.parametrize("paths", [[], ["/abs/SKILL.md"], ["a/../SKILL.md"], ["a/README.md"]])
def test_bad_skill_paths_are_refused(atlas: Atlas, paths: list[str]) -> None:
    with pytest.raises(ValueError, match="bad skill paths"):
        atlas.install("owner/repo", paths)


def test_data_matches_the_route(atlas: Atlas, claude: Path, server: str) -> None:
    serve.ROOTS.clear()
    serve.ROOTS["main"] = claude
    code, body = get(f"{server}/api/data")
    mine = atlas.data()
    assert code == 200 and set(mine["server"]) == {"build", "stale"}
    assert mine["config_path"].endswith(".json")
    for key in ("generated_at", "server"):
        del body[key], mine[key]
    assert body == mine
    assert [s["name"] for s in mine["skills"]] == ["alpha", "beta"]


def test_available_text_reads_raw_github(atlas: Atlas, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, float]] = []

    class Body:
        def __enter__(self) -> "Body":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return b"---\nname: x\n---\n"

    def urlopen(req: urllib.request.Request, timeout: float) -> Body:
        seen.append((req.full_url, timeout))
        if "gone" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", Message(), None)
        return Body()

    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)
    assert atlas.available_text("o/r", "skills/a b/SKILL.md") == "---\nname: x\n---\n"
    assert seen == [("https://raw.githubusercontent.com/o/r/HEAD/skills/a%20b/SKILL.md", 20)]
    with pytest.raises(OSError, match="not found"):
        atlas.available_text("o/r", "skills/gone/SKILL.md")
    with pytest.raises(ValueError, match="bad skill paths"):
        atlas.available_text("o/r", "/etc/SKILL.md")
    with pytest.raises(ValueError, match="not a GitHub repo"):
        atlas.available_text("not a repo", "SKILL.md")
