"""Build dist/skill-atlas.pyz, a single file that runs with `python3 skill-atlas.pyz`."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = "import sys\nfrom skill_atlas.__main__ import main\n\nsys.exit(main())\n"


def build(out: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        shutil.copytree(
            ROOT / "src" / "skill_atlas",
            stage / "skill_atlas",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (stage / "__main__.py").write_text(MAIN, encoding="utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(stage, out, interpreter="/usr/bin/env python3", compressed=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "dist" / "skill-atlas.pyz")
    out = build(ap.parse_args().out)
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
