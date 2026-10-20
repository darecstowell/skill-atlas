import re
import shutil
import subprocess
from pathlib import Path

import pytest

from build import render_page

TEMPLATE = Path(__file__).resolve().parent.parent / "template" / "index.html"


def test_render_inlines_data():
    page = render_page({"skills": [], "marker": "</script>"}, api_token="t0k")
    assert "__SKILL_ATLAS_DATA__" not in page
    assert '</script>"' not in page


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_script_parses(tmp_path):
    scripts = re.findall(r"<script>(.*?)</script>", TEMPLATE.read_text(), re.S)
    assert scripts
    for i, src in enumerate(scripts):
        f = tmp_path / f"s{i}.js"
        f.write_text(src.replace("__SKILL_ATLAS_DATA__", "{}"))
        subprocess.run(["node", "--check", str(f)], check=True)
