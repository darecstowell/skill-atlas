import builtins
import hashlib
import io
import os
import subprocess
import sys
import types
from importlib import metadata
from pathlib import Path

import pytest

import skill_atlas.__main__ as entry
from skill_atlas import serve, tui
from skill_atlas.tui import bootstrap

SRC = Path(__file__).resolve().parents[2] / "src"


class Tty(io.StringIO):
    def isatty(self):
        return True


def fake_textual(target, version="8.2.8"):
    (target / "textual").mkdir(parents=True)
    (target / "textual" / "__init__.py").write_text("", encoding="utf-8")
    info = target / f"textual-{version}.dist-info"
    info.mkdir()
    meta = f"Metadata-Version: 2.1\nName: textual\nVersion: {version}\n"
    (info / "METADATA").write_text(meta, encoding="utf-8")


def never(*args, **kwargs):
    raise AssertionError("must not be called")


@pytest.fixture
def missing(tmp_path, monkeypatch):
    """Textual is not on sys.path, and the private folder is under tmp_path."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "stdin", Tty())
    monkeypatch.setattr(bootstrap, "_on_sys_path", lambda: None)
    monkeypatch.setattr(bootstrap, "_has_pip", lambda: True)
    return bootstrap.folder()


@pytest.fixture
def runs(monkeypatch):
    """Fake pip: writes Textual into --target and records each command."""
    calls = []

    def run(cmd, check=False):
        req = Path(cmd[cmd.index("-r") + 1])
        calls.append({"cmd": cmd, "requirements": req.read_bytes()})
        fake_textual(Path(cmd[cmd.index("--target") + 1]))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    return calls


def test_textual_on_sys_path_needs_nothing(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(bootstrap.subprocess, "run", never)
    before = list(sys.path)
    assert bootstrap._on_sys_path() == metadata.version("textual")
    assert bootstrap.ensure() == 0
    assert sys.path == before


def test_textual_in_private_folder_goes_on_sys_path(missing, monkeypatch):
    monkeypatch.setattr(bootstrap, "_on_sys_path", lambda: "0.86.0")
    monkeypatch.setattr(bootstrap.subprocess, "run", never)
    fake_textual(missing)
    assert bootstrap.ensure() == 0
    assert sys.path[0] == str(missing)


def test_no_tty_prints_the_command_and_exits_2(missing, monkeypatch, capsys, runs):
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(builtins, "input", never)
    assert bootstrap.ensure() == 2
    err = capsys.readouterr().err
    assert "needs Textual 8.2, and it is not installed" in err
    assert str(missing) in err
    assert err.rstrip().endswith("tui --yes")
    assert runs == []


def test_yes_installs_without_a_question(missing, monkeypatch, capsys, runs):
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(builtins, "input", never)
    assert bootstrap.ensure(yes=True) == 0
    [call] = runs
    cmd = call["cmd"]
    assert cmd[:4] == [sys.executable, "-m", "pip", "install"]
    assert cmd[-6:-2] == ["--require-hashes", "--no-deps", "--only-binary", ":all:"]
    tmp = Path(cmd[cmd.index("--target") + 1])
    assert tmp.parent == missing.parent and tmp.name.startswith(".")
    assert call["requirements"] == bootstrap.requirements()
    assert bootstrap._in_folder(missing) == "8.2.8"
    assert not tmp.exists()
    assert sys.path[0] == str(missing)
    assert capsys.readouterr().out == f"Installed Textual 8.2.8 into {missing}.\n"


def test_enter_means_yes(missing, monkeypatch, runs):
    asked = []
    monkeypatch.setattr(builtins, "input", lambda q: asked.append(q) or "")
    assert bootstrap.ensure() == 0
    assert asked == [
        f"The TUI needs Textual 8.2 (about 11 MB, pure Python). Install it into {missing}? [Y/n] "
    ]
    assert len(runs) == 1


def test_n_declines(missing, monkeypatch, capsys, runs):
    monkeypatch.setattr(builtins, "input", lambda q: "n")
    assert bootstrap.ensure() == 1
    assert runs == []
    assert not missing.parent.exists()
    assert "To install it later, run:" in capsys.readouterr().err


def test_no_pip_falls_back_to_uv(missing, monkeypatch, runs):
    monkeypatch.setattr(bootstrap, "_has_pip", lambda: False)
    monkeypatch.setattr(
        bootstrap.shutil, "which", lambda name: "/opt/bin/uv" if name == "uv" else None
    )
    assert bootstrap.ensure(yes=True) == 0
    cmd = runs[0]["cmd"]
    assert cmd[:5] == ["/opt/bin/uv", "pip", "install", "--python", sys.executable]
    assert "--require-hashes" in cmd
    assert bootstrap._in_folder(missing) == "8.2.8"


def test_no_pip_and_no_uv_prints_uvx(missing, monkeypatch, capsys, runs):
    monkeypatch.setattr(bootstrap, "_has_pip", lambda: False)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: None)
    monkeypatch.setattr(builtins, "input", never)
    assert bootstrap.ensure() == 1
    assert bootstrap.UVX in capsys.readouterr().err
    assert runs == []


@pytest.mark.parametrize("failure", ["exit", "interrupt"])
def test_failed_install_leaves_nothing(missing, monkeypatch, capsys, failure):
    def run(cmd, check=False):
        target = Path(cmd[cmd.index("--target") + 1])
        (target / "textual").mkdir()
        if failure == "interrupt":
            raise KeyboardInterrupt
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    assert bootstrap.ensure(yes=True) == 1
    assert not missing.exists()
    assert list(missing.parent.iterdir()) == []
    assert "Nothing was installed." in capsys.readouterr().err


def test_folder_changes_with_the_pin(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    names = []
    for pin in (b"textual==8.2.8\n", b"textual==8.2.9\n"):
        monkeypatch.setattr(bootstrap, "requirements", lambda pin=pin: pin)
        target = bootstrap.folder()
        assert target.parent == tmp_path / "skill-atlas" / "tui"
        assert target.name.startswith(hashlib.sha256(pin).hexdigest()[:12])
        names.append(target.name)
    assert names[0] != names[1]


def test_requirements_pin_textual_with_hashes():
    text = bootstrap.requirements().decode()
    assert "textual==8.2.8" in text
    assert "uv pip compile" in text
    assert text.count("--hash=sha256:") >= 2 * text.count("==")


@pytest.mark.parametrize(
    ("version", "ok"), [("8.2.0", True), ("8.9.1", True), ("8.1.9", False), ("9.0.0", False)]
)
def test_supported_versions(version, ok):
    assert bootstrap.supported(version) is ok


def test_tui_command_goes_to_launch(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "argv", ["skill-atlas", "tui", "--demo"])
    monkeypatch.setattr(tui, "launch", lambda argv: seen.append(argv) or 0)
    monkeypatch.setattr(serve, "main", never)
    assert entry.main() == 0
    assert seen == [["--demo"]]


def test_other_arguments_go_to_serve(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["skill-atlas", "--port", "9"])
    monkeypatch.setattr(tui, "launch", never)
    monkeypatch.setattr(serve, "main", lambda: 7)
    assert entry.main() == 7


def test_help_mentions_tui(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["skill-atlas", "--help"])
    with pytest.raises(SystemExit):
        entry.main()
    out = capsys.readouterr().out
    assert "--port" in out
    assert out.endswith(f"\n\n{entry.TUI_HELP}\n")


def test_launch_runs_the_app_after_bootstrap(monkeypatch):
    app = types.ModuleType("skill_atlas.tui.app")
    app.run = lambda demo=False: 5 if demo else 4
    monkeypatch.setitem(sys.modules, "skill_atlas.tui.app", app)
    flags = []
    monkeypatch.setattr(bootstrap, "ensure", lambda yes=False: flags.append(yes) or 0)
    assert tui.launch(["--demo", "--yes"]) == 5
    assert tui.launch([]) == 4
    assert flags == [True, False]
    monkeypatch.setattr(bootstrap, "ensure", lambda yes=False: 2)
    assert tui.launch([]) == 2


SSH = "/dev/ttys001"


@pytest.fixture
def started(monkeypatch, capsys):
    """A fake app: each start records stderr so far and TEXTUAL_COLOR_SYSTEM."""
    for var in ("SSH_TTY", "COLORTERM", "TEXTUAL_COLOR_SYSTEM"):
        monkeypatch.delenv(var, raising=False)
    starts = []

    def run(demo=False):
        color = os.environ.get("TEXTUAL_COLOR_SYSTEM")
        starts.append({"err": capsys.readouterr().err, "color": color})
        return 0

    app = types.ModuleType("skill_atlas.tui.app")
    app.run = run
    monkeypatch.setitem(sys.modules, "skill_atlas.tui.app", app)
    monkeypatch.setattr(bootstrap, "ensure", lambda yes=False: 0)
    return starts


def test_truecolor_sets_the_color_system_before_the_app(started):
    assert tui.launch(["--truecolor"]) == 0
    assert started == [{"err": "", "color": "truecolor"}]


def test_ssh_without_true_color_prints_one_line_before_the_app(started, monkeypatch):
    monkeypatch.setenv("SSH_TTY", SSH)
    assert tui.launch([]) == 0
    assert started == [{"err": tui.limited_hint() + "\n", "color": None}]


@pytest.mark.parametrize(
    ("env", "argv"),
    [
        ({}, []),
        ({"SSH_TTY": SSH, "COLORTERM": "truecolor"}, []),
        ({"SSH_TTY": SSH, "COLORTERM": "24bit"}, []),
        ({"SSH_TTY": SSH, "TEXTUAL_COLOR_SYSTEM": "256"}, []),
        ({"SSH_TTY": SSH}, ["--truecolor"]),
    ],
)
def test_no_color_line_when_true_color_is_known_or_local(started, monkeypatch, env, argv):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert tui.launch(argv) == 0
    assert started[0]["err"] == ""


def test_no_color_line_when_bootstrap_stops(started, monkeypatch, capsys):
    monkeypatch.setenv("SSH_TTY", SSH)
    monkeypatch.setattr(bootstrap, "ensure", lambda yes=False: 2)
    assert tui.launch([]) == 2
    assert started == []
    assert tui.limited_hint() not in capsys.readouterr().err


def test_tui_help_lists_truecolor(capsys):
    with pytest.raises(SystemExit):
        tui.launch(["--help"])
    assert "--truecolor" in capsys.readouterr().out


def test_web_path_never_imports_textual():
    probe = (
        "import sys\n"
        "import skill_atlas.__main__, skill_atlas.serve, skill_atlas.tui\n"
        "assert not [m for m in sys.modules if m.split('.')[0] in ('textual', 'rich')]\n"
    )
    subprocess.run(
        [sys.executable, "-c", probe], check=True, env={**os.environ, "PYTHONPATH": str(SRC)}
    )
