# Contributing

The atlas itself uses only the Python standard library. The dev tools run through
[uv](https://docs.astral.sh/uv/):

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy                  # type check
uv run pytest                # tests (the template test needs Node for `node --check`)
```

CI runs the same commands on Ubuntu and macOS with Python 3.9 and 3.13.

Read `AGENTS.md` for the rules about which module writes what. Tests must never touch your real
`~/.claude` or `~/.agents`. Use `tmp_path` for every file they write.
