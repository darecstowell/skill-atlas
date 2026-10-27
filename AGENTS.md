# Skill Atlas — agent notes

A local tool that inventories installed Claude Code skills. Read `README.md` first.

## Rules

- Standard library only at run time. No dependencies, no build step. Dev tools (ruff, mypy,
  pytest) run through `uv run`; see `CONTRIBUTING.md`. Run all four checks before you commit.
- `scan.py` reads the host config; it never writes to `~/.claude` or `~/.claude-work`.
- `serve.py` is the only writer. It changes `skillOverrides` and `enabledPlugins` in a root's
  `settings.json` and nothing else, keeps a one-time `settings.json.atlas-bak`, and binds to 127.0.0.1.
- `updates.py` and `remove.py` are the only code that changes skill folders. Updates swap a folder
  through a staged copy; deletes move it to `~/.Trash`, never `rm`. Both keep the npx lock and
  `.atlas-lock.json` in step, and touch no other key in them. Installs from a source go through
  the same staged copy and never replace an existing folder.
- `.atlas-lock.json` also holds `sources` (watched repos) and `seen` (paths per repo). Only
  `updates.py` writes them.
- `usage.py` only reads `.claude.json` and `projects/**/*.jsonl`; its one write is the index cache at
  `out/usage-index.json`.
- `out/` is generated. Never hand-edit it, and never track it.
- The frontmatter parser in `scan.py` covers the YAML subset that real skills use. Widen it when a
  skill fails to parse, rather than adding a YAML dependency.
- New metadata belongs in the record built by `build_record`, then in `renderDetail` in the
  template. Keep the two in step.
