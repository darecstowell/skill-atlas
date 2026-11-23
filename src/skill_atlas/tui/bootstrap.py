"""Find Textual for the TUI, or install it into a private folder after the user agrees.

Standard library only: this module runs before Textual can be imported.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata, resources
from pathlib import Path

NEED = "Textual 8.2"
UVX = 'uvx --from "git+https://github.com/darecstowell/skill-atlas[tui]" skill-atlas tui'


def requirements() -> bytes:
    return (resources.files("skill_atlas.tui") / "requirements.txt").read_bytes()


def folder() -> Path:
    """The private folder for this pin and this Python version."""
    digest = hashlib.sha256(requirements()).hexdigest()[:12]
    base = Path(os.environ.get("XDG_DATA_HOME") or "~/.local/share").expanduser()
    py = f"py{sys.version_info[0]}.{sys.version_info[1]}"
    return base / "skill-atlas" / "tui" / f"{digest}-{py}"


def supported(version: str | None) -> bool:
    found = re.match(r"(\d+)\.(\d+)", version or "")
    return found is not None and (8, 2) <= (int(found[1]), int(found[2])) < (9, 0)


def rerun() -> str:
    """The shell command that started Skill Atlas, for messages that say what to run."""
    arg0 = Path(sys.argv[0])
    if arg0.name == "__main__.py":
        launcher = arg0.resolve().parents[2] / "atlas"
        if launcher.is_file():
            return shlex.quote(str(launcher))
        return f"{shlex.quote(sys.executable)} -m skill_atlas"
    if arg0.suffix == ".pyz":
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(arg0))}"
    if shutil.which(arg0.name) == str(arg0):
        return arg0.name
    return shlex.quote(str(arg0))


def ensure(yes: bool = False) -> int:
    """Make Textual importable. Return 0 when it is ready, else the exit code."""
    if supported(_on_sys_path()):
        return 0
    target = folder()
    if supported(_in_folder(target)):
        _use(target)
        return 0
    command = installer()
    if command is None:
        _say(
            f"The TUI needs {NEED}. This Python has no pip, and uv is not on PATH.\n"
            f"Install uv (https://docs.astral.sh/uv/), then run:\n  {UVX}"
        )
        return 1
    later = f"  {rerun()} tui --yes"
    if not yes and not sys.stdin.isatty():
        _say(
            f"The TUI needs {NEED}, and it is not installed.\n"
            f"To install it into {target}, run:\n{later}"
        )
        return 2
    if not yes and not _agree(target):
        _say(f"Textual is not installed. To install it later, run:\n{later}")
        return 1
    if not _install(command, target):
        return 1
    _use(target)
    print(f"Installed Textual {_in_folder(target)} into {target}.", flush=True)
    return 0


def installer() -> list[str] | None:
    """The pip or uv command that installs into a folder, or None when neither exists."""
    if _has_pip():
        flags = ["--disable-pip-version-check", "--no-compile"]
        return [sys.executable, "-m", "pip", "install", *flags]
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip", "install", "--python", sys.executable]
    return None


def _has_pip() -> bool:
    return importlib.util.find_spec("pip") is not None


def _on_sys_path() -> str | None:
    if importlib.util.find_spec("textual") is None:
        return None
    try:
        return metadata.version("textual")
    except metadata.PackageNotFoundError:
        return None


def _in_folder(target: Path) -> str | None:
    if not (target / "textual").is_dir():
        return None
    for dist in metadata.distributions(name="textual", path=[str(target)]):
        return dist.version
    return None


def _use(target: Path) -> None:
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
    importlib.invalidate_caches()


def _say(message: str) -> None:
    print(message, file=sys.stderr)


def _agree(target: Path) -> bool:
    question = f"The TUI needs {NEED} (about 11 MB, pure Python). Install it into {target}? [Y/n] "
    try:
        answer = input(question)
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() in ("", "y", "yes")


def _install(command: list[str], target: Path) -> bool:
    """Install into a temp folder next to target, then rename it into place."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    except OSError as e:
        _say(f"Cannot write to {target.parent}: {e.strerror or e}.")
        return False
    try:
        with tempfile.TemporaryDirectory() as scratch:
            req = Path(scratch) / "requirements.txt"
            req.write_bytes(requirements())
            pins = ["--require-hashes", "--no-deps", "--only-binary", ":all:", "-r", str(req)]
            _say(f"Installing {NEED} into {target}…")
            code = subprocess.run([*command, "--target", str(tmp), *pins], check=False).returncode
        if code != 0:
            _say(
                f"Could not install {NEED}: pip exited with code {code}. Nothing was installed. "
                f"Check your network and the pip output above, then run: {rerun()} tui --yes"
            )
            return False
        if not supported(_in_folder(tmp)):
            _say(
                f"Could not install {NEED}: pip gave another version. Nothing was installed. "
                f"Run: {rerun()} tui --yes"
            )
            return False
        if not supported(_in_folder(target)):
            shutil.rmtree(target, ignore_errors=True)
            os.rename(tmp, target)
        return True
    except KeyboardInterrupt:
        _say("The install was stopped. Nothing was installed.")
        return False
    except OSError as e:
        _say(f"The install failed: {e}. Nothing was installed.")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
