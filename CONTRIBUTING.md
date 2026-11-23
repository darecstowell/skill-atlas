# Contributing

The web page uses only the Python standard library. The terminal client installs Textual on first
use, after the user agrees. The dev tools run through [uv](https://docs.astral.sh/uv/):

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy                  # type check
uv run pytest                # tests (the template test needs Node for `node --check`)
```

The code is in `src/skill_atlas/`, and the page is `src/skill_atlas/web/index.html`. To run it:

```bash
./atlas                              # the web page: no install, standard library only
uv run skill-atlas                   # the same server, from the uv environment
uv run python -m skill_atlas.build   # write a read-only page to out/index.html
```

CI runs the same commands on Ubuntu and macOS with Python 3.10 and 3.13.

Read `AGENTS.md` for the rules about which module writes what. Tests must never touch your real
`~/.claude` or `~/.agents`. Use `tmp_path` for every file they write.

## Terminal client

The client is in `src/skill_atlas/tui/`. The uv environment has Textual, so `uv run` starts the
client with no question.

```bash
uv run python -m skill_atlas tui --demo   # run the client on sample data
uv run pytest tests/tui                   # run the TUI tests
```

The sample data is `DemoAtlas` in `src/skill_atlas/core/demo.py`. It keeps all its data in memory,
so the TUI tests and the screenshots never touch `~/.claude` or `~/.agents`.

To check the visuals, render the client on the sample data:

```bash
uv run python scripts/tui_shot.py --sizes 80x24,120x36 --themes atlas-dark,atlas-light
uv run python scripts/tui_shot.py --keys "j j enter" --out out/shots/open
```

`--sizes` and `--themes` take comma lists, and the script renders each pair. `--keys` gives the
Textual key names to press first. `--out` is the output path without a suffix. Each shot is an SVG
and a PNG. The PNG needs `rsvg-convert` or Google Chrome. `--no-png` writes the SVG only.

## Packages

```bash
uv build                         # wheel and sdist in dist/
python3 scripts/build_pyz.py     # dist/skill-atlas.pyz, a single file that runs with python3
```

The page and textures are package data. Read them through `skill_atlas.WEB` (an
`importlib.resources` path), so they also load from inside the `.pyz`. Never write inside the
package; write to `skill_atlas.REPO` or the user's config and cache folders.

The repo is also a Claude Code plugin marketplace. `.claude-plugin/` holds the manifests, and
`skills/skills-atlas/SKILL.md` gives the `/skills-atlas` command, which runs
`scripts/start-atlas.sh`. Check them with `claude plugin validate .`.

## Releases

1. Set `__version__` in `src/skill_atlas/__init__.py` and `version` in
   `.claude-plugin/plugin.json` to the new version. A test checks that the two are the same.
2. Merge to `main`, then push a tag: `git tag v0.2.0 && git push origin v0.2.0`.
3. `.github/workflows/release.yml` runs the checks, makes sure that the tag is `v` plus the
   version, builds the wheel, the sdist, and the `.pyz`, and attaches them to a GitHub Release.
