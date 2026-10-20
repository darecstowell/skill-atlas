#!/usr/bin/env python3
"""Scan the skills and write out/skills.json plus a self-contained out/index.html."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scan import scan

REPO = Path(__file__).resolve().parent
OUT = REPO / "out"


def render_page(data: dict, api_token: str = "") -> str:
    """Inline the records into the template. No token means a read-only page."""
    payload = json.dumps({**data, "api_token": api_token}).replace("</", "<\\/")
    template = (REPO / "template" / "index.html").read_text()
    return template.replace("__SKILL_ATLAS_DATA__", payload)


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

    OUT.mkdir(exist_ok=True)
    (OUT / "skills.json").write_text(json.dumps(data, indent=2))

    page = OUT / "index.html"
    page.write_text(render_page(data))

    print(f"{data['count']} skills -> {page}")
    if args.open:
        subprocess.run(["open", str(page)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
