"""`tui` opens the terminal client. Any other arguments go to the web server."""

from __future__ import annotations

import sys

TUI_HELP = "Add 'tui' to open Skill Atlas in the terminal. 'tui --help' shows its options."


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["tui"]:
        from .tui import launch

        return launch(args[1:])
    from . import serve

    if "-h" in args or "--help" in args:
        try:
            return serve.main()
        finally:
            print(f"\n{TUI_HELP}")
    return serve.main()


if __name__ == "__main__":
    raise SystemExit(main())
