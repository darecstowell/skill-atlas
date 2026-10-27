"""Scan the skills and write out/skills.json plus a self-contained out/index.html."""

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import REPO, WEB
from .scan import scan

OUT = REPO / "out"


def render_page(data: dict, api_token: str = "") -> str:
    """Inline the records into the template. No token means a read-only page."""
    payload = json.dumps({**data, "api_token": api_token}).replace("</", "<\\/")
    template = (WEB / "index.html").read_text(encoding="utf-8")
    return template.replace("__SKILL_ATLAS_DATA__", payload)


def copy_textures(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for f in (WEB / "bg").iterdir():
        if f.name.endswith(".webp"):
            (dest / f.name).write_bytes(f.read_bytes())


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Skill Atlas.")
    ap.add_argument("--open", action="store_true", help="open the page when it is built")
    ap.add_argument("--json", action="store_true", help="print the raw records to stdout instead")
    args = ap.parse_args()

    data = scan(REPO)
    if args.json:
        json.dump(data, sys.stdout, indent=2)
        print()
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "skills.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    page = OUT / "index.html"
    page.write_text(render_page(data), encoding="utf-8")
    copy_textures(OUT / "bg")

    print(f"{data['count']} skills -> {page}")
    if args.open:
        webbrowser.open(page.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
