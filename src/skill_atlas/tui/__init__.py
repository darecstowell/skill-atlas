"""The terminal client. This module and bootstrap use only the standard library."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping

from . import bootstrap


def limited_hint() -> str:
    return (
        "Colors are limited to 256. If your terminal supports true color, run "
        f"{bootstrap.rerun()} tui --truecolor, or set COLORTERM=truecolor."
    )


def launch(argv: list[str]) -> int:
    """Run `tui [--demo] [--yes] [--truecolor]`: make Textual importable, then start the app."""
    ap = argparse.ArgumentParser(prog="atlas tui", description="Open Skill Atlas in the terminal.")
    ap.add_argument("--demo", action="store_true", help="show sample data, not your skills")
    ap.add_argument(
        "--yes", action="store_true", help="install Textual without a question if it is missing"
    )
    ap.add_argument(
        "--truecolor",
        action="store_true",
        help="use 24-bit color, for SSH sessions that do not send COLORTERM",
    )
    args = ap.parse_args(argv)
    if args.truecolor:
        os.environ["TEXTUAL_COLOR_SYSTEM"] = "truecolor"
    code = bootstrap.ensure(yes=args.yes)
    if code:
        return code
    if limited_colors(os.environ):
        print(limited_hint(), file=sys.stderr)
    from .app import run

    return run(demo=args.demo)


def limited_colors(env: Mapping[str, str]) -> bool:
    """True over SSH when nothing tells Textual that the terminal has true color."""
    true = env.get("COLORTERM", "").lower() in ("truecolor", "24bit")
    return bool(env.get("SSH_TTY")) and not true and "TEXTUAL_COLOR_SYSTEM" not in env
