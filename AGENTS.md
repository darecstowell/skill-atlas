# Skill Atlas — agent notes

A local tool that inventories installed Claude Code skills. Read `README.md` first.

## Rules

- Standard library only. No dependencies, no build step, no package manager.
- `scan.py` reads the host config; it never writes to `~/.claude` or `~/.claude-work`.
- `serve.py` is the only writer. It changes `skillOverrides` and `enabledPlugins` in a root's
  `settings.json` and nothing else, keeps a one-time `settings.json.atlas-bak`, and binds to 127.0.0.1.
- `updates.py` and `remove.py` are the only code that changes skill folders. Updates swap a folder
  through a staged copy; deletes move it to `~/.Trash`, never `rm`. Both keep the npx lock and
  `.atlas-lock.json` in step, and touch no other key in them.
- `out/` is generated. Never hand-edit it, and never track it.
- The frontmatter parser in `scan.py` covers the YAML subset that real skills use. Widen it when a
  skill fails to parse, rather than adding a YAML dependency.
- New metadata belongs in the record built by `build_record`, then in `renderDetail` in the
  template. Keep the two in step.
