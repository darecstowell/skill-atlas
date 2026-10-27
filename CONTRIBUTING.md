# Contributing

The atlas itself uses only the Python standard library. The dev tools run through
[uv](https://docs.astral.sh/uv/):

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy                  # type check
uv run pytest                # tests (the template test needs Node for `node --check`)
```

The code is in `src/skill_atlas/`, and the page is `src/skill_atlas/web/index.html`. To run it:

```bash
./atlas                              # no install, standard library only
uv run skill-atlas                   # the same server, from the uv environment
uv run python -m skill_atlas.build   # write a read-only page to out/index.html
```

CI runs the same commands on Ubuntu and macOS with Python 3.10 and 3.13.

Read `AGENTS.md` for the rules about which module writes what. Tests must never touch your real
`~/.claude` or `~/.agents`. Use `tmp_path` for every file they write.

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
