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
