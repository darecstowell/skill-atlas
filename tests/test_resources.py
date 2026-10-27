import subprocess
import sys
from importlib.resources import files
from pathlib import Path

from skill_atlas import WEB, build, serve

ROOT = Path(__file__).resolve().parent.parent


def test_page_and_textures_load_through_importlib_resources():
    web = files("skill_atlas") / "web"
    assert "__SKILL_ATLAS_DATA__" in (web / "index.html").read_text(encoding="utf-8")
    assert (web / "bg" / "linen.webp").read_bytes()[:4] == b"RIFF"
    assert (serve.TEXTURES / "linen.webp").read_bytes() == (WEB / "bg" / "linen.webp").read_bytes()


def test_build_copies_textures(tmp_path):
    build.copy_textures(tmp_path / "bg")
    assert sorted(p.name for p in tmp_path.joinpath("bg").iterdir()) == sorted(
        f.name for f in (WEB / "bg").iterdir() if f.name.endswith(".webp")
    )


def test_pyz_reads_web_files_from_the_zip(tmp_path):
    pyz = tmp_path / "skill-atlas.pyz"
    script = ROOT / "scripts" / "build_pyz.py"
    subprocess.run([sys.executable, str(script), "--out", str(pyz)], check=True)
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "import skill_atlas\n"
        "from skill_atlas import serve\n"
        "from skill_atlas.build import render_page\n"
        "assert sys.argv[1] in str(skill_atlas.__file__)\n"
        "assert 'api_token' in render_page({}, api_token='t')\n"
        "assert (serve.TEXTURES / 'linen.webp').read_bytes()[:4] == b'RIFF'\n"
        "assert serve.BUILD == skill_atlas.__version__\n"
        "assert serve.server_info()['stale'] is False\n"
        "assert sys.argv[1] not in str(skill_atlas.REPO)\n"
    )
    subprocess.run([sys.executable, "-I", "-c", probe, str(pyz)], check=True, cwd=tmp_path)
    help_run = [sys.executable, str(pyz), "--help"]
    out = subprocess.run(help_run, check=True, capture_output=True, text=True).stdout
    assert "--port" in out


def test_plugin_version_matches_package():
    import json

    import skill_atlas

    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin["version"] == skill_atlas.__version__
