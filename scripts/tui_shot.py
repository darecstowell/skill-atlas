"""Render the TUI over the demo data to SVG and PNG, after a key sequence, for review.

    uv run python scripts/tui_shot.py --size 120x36 --keys "j j enter" --out out/shots/open
    uv run python scripts/tui_shot.py --sizes 80x24,120x36,180x50 --themes atlas-dark,atlas-light

Keys are Textual key names split by spaces. `type:text` types text; `wait:0.5` waits.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PNG_WIDTH = 1600
LEADING = re.compile(
    r'(<text [^>]*?x=")([\d.]+)("[^>]*?textLength=")([\d.]+)("[^>]*>)((?:&#160;)+)([^<]*)</text>'
)


def parse_size(text: str) -> tuple[int, int]:
    w, _, h = text.lower().partition("x")
    return int(w), int(h)


def prefs_for(theme_name: str) -> dict:
    from skill_atlas.tui import theme

    for palette, mode in itertools.product(theme.PALETTES, theme.SHADES):
        if theme.name(palette, mode) == theme_name:
            return {"palette": palette, "mode": mode}
    return {}


DEMO_NOW = datetime(2026, 10, 28, 9, 30).astimezone()


async def press(pilot, keys: str) -> None:
    from skill_atlas.tui.app import settle

    for token in keys.split():
        kind, _, rest = token.partition(":")
        if kind == "type" and rest:
            await pilot.press(*rest)
        elif kind == "wait" and rest:
            await asyncio.sleep(float(rest))
        else:
            await pilot.press(token)
        await settle(pilot)


async def shoot(
    size: tuple[int, int], theme_name: str, keys: str, svg: Path, extra: dict | None = None
) -> None:
    from skill_atlas.core.demo import DemoAtlas
    from skill_atlas.tui.app import AtlasApp, settle

    with tempfile.TemporaryDirectory() as tmp:
        prefs = Path(tmp) / "tui.json"
        want = prefs_for(theme_name)
        prefs.write_text(json.dumps({**want, **(extra or {})}), encoding="utf-8")
        app = AtlasApp(DemoAtlas(now=DEMO_NOW), prefs=prefs)
        async with app.run_test(size=size, notifications=True) as pilot:
            await settle(pilot)
            if not want:
                app.theme = theme_name
            await press(pilot, keys)
            svg.write_text(app.export_screenshot(), encoding="utf-8")


def for_rsvg(svg: str) -> str:
    """rsvg drops the leading spaces of a text run, so move the run right instead."""

    def shift(m: re.Match[str]) -> str:
        lead = m[6].count("&#160;")
        cell = float(m[4]) / (lead + len(html.unescape(m[7])))
        x, length = float(m[2]) + lead * cell, float(m[4]) - lead * cell
        return f"{m[1]}{x:.1f}{m[3]}{length:.1f}{m[5]}{m[7]}</text>"

    return LEADING.sub(shift, svg).replace(
        "font-family: Fira Code,", "font-family: Fira Code, Menlo,"
    )


def to_png(svg: Path, png: Path) -> bool:
    if shutil.which("rsvg-convert"):
        fixed = svg.with_suffix(".rsvg.svg")
        fixed.write_text(for_rsvg(svg.read_text(encoding="utf-8")), encoding="utf-8")
        cmd = ["rsvg-convert", "-w", str(PNG_WIDTH), "-o", str(png), str(fixed)]
        ok = subprocess.run(cmd, check=False).returncode == 0
        fixed.unlink()
        if ok:
            return True
    if not Path(CHROME).exists():
        return False
    box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg.read_text(encoding="utf-8"))
    height = round(PNG_WIDTH * float(box[2]) / float(box[1])) if box else 1000
    cmd = [
        CHROME,
        "--headless=new",
        "--hide-scrollbars",
        f"--window-size={PNG_WIDTH},{height}",
        f"--screenshot={png.resolve()}",
        svg.resolve().as_uri(),
    ]
    return subprocess.run(cmd, check=False, capture_output=True).returncode == 0


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("COLORTERM", "truecolor")  # else Rich may pick 256 colors
    ap = argparse.ArgumentParser(description="Render the TUI to SVG and PNG.")
    ap.add_argument("--size", default="120x36", help="WIDTHxHEIGHT in cells")
    ap.add_argument("--sizes", help="a comma list of sizes; renders each one")
    ap.add_argument("--theme", default="atlas-dark", help="a theme name, such as sage-light")
    ap.add_argument("--themes", help="a comma list of themes; renders each one")
    ap.add_argument("--keys", default="", help='keys to press first, such as "j j enter"')
    ap.add_argument("--out", default="out/shots/shot", help="the output path without a suffix")
    ap.add_argument("--no-png", action="store_true", help="write the SVG only")
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="FIELD=JSON",
        help='a saved preference to start with, such as group_size="large" or compact=true',
    )
    args = ap.parse_args(argv)

    os.environ.setdefault("TEXTUAL_ANIMATIONS", "none")
    sizes = [parse_size(s) for s in (args.sizes or args.size).split(",")]
    themes = (args.themes or args.theme).split(",")
    base = Path(args.out)
    base.parent.mkdir(parents=True, exist_ok=True)
    matrix = len(sizes) * len(themes) > 1
    extra = {}
    for item in args.set:
        field, _, raw = item.partition("=")
        try:
            extra[field] = json.loads(raw)
        except ValueError:
            extra[field] = raw
    failed = 0
    for (w, h), theme_name in itertools.product(sizes, themes):
        stem = f"{base.name}-{w}x{h}-{theme_name}" if matrix else base.name
        svg = base.with_name(stem + ".svg")
        asyncio.run(shoot((w, h), theme_name, args.keys, svg, extra))
        png = svg.with_suffix(".png")
        if args.no_png:
            print(svg)
        elif to_png(svg, png):
            print(png)
        else:
            print(f"{svg} (no PNG: install rsvg-convert or Google Chrome)", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
