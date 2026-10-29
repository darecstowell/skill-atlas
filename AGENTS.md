# Skill Atlas — agent notes

A local tool that inventories installed Claude Code skills. Read `README.md` first.

## Layout

- The code is the package `src/skill_atlas/`. Modules import each other with relative imports
  (`from . import scan`). Tests patch module attributes, so import modules, not only names.
- The page is `src/skill_atlas/web/index.html`, and its textures are in `web/bg/`. They are
  package data. Find them through `skill_atlas.WEB`, not through a path from the repo root.
  `WEB` is an `importlib.resources` Traversable, so the `.pyz` build can read it from a zip. Use
  `/`, `read_text`, `read_bytes`, and `iterdir` on it, not `Path` or `shutil` calls.
- `skill_atlas.REPO` is the clone root when the code runs from a clone. `out/` and the fallback
  `config.json` go there. Outside a clone, `REPO` is `$XDG_DATA_HOME/skill-atlas`.
- `./atlas`, `uv run skill-atlas`, and `python -m skill_atlas` start the same server.
  `python -m skill_atlas.build` writes the static page.
- README images are in `docs/images/`.

## Rules

- The web path is standard library only, and `./atlas` needs no install. The TUI installs its
  pinned dependencies on first use, after the user agrees. Dev tools (ruff, mypy, pytest) run
  through `uv run`; see `CONTRIBUTING.md`. Run all four checks before you commit.
- `scan.py` reads the host config; it never writes to `~/.claude` or `~/.claude-work`.
- `serve.py` is the only writer. It changes `skillOverrides` and `enabledPlugins` in a root's
  `settings.json` and nothing else, keeps a one-time `settings.json.atlas-bak`, and binds to 127.0.0.1.
- `updates.py` and `remove.py` are the only code that changes skill folders. Updates swap a folder
  through a staged copy; deletes move it to the Trash (`remove.TRASH`), never `rm`. Both keep the
  npx lock and `.atlas-lock.json` in step, and touch no other key in them. Installs from a source
  go through the same staged copy and never replace an existing folder.
- `.atlas-lock.json` also holds `sources` (watched repos) and `seen` (paths per repo). Only
  `updates.py` writes them.
- `usage.py` only reads `.claude.json` and `projects/**/*.jsonl`; its one write is the index cache at
  `out/usage-index.json`.
- `out/` is generated. Never hand-edit it, and never track it.
- The frontmatter parser in `scan.py` covers the YAML subset that real skills use. Widen it when a
  skill fails to parse, rather than adding a YAML dependency.
- New metadata belongs in the record built by `build_record`, then in `renderDetail` in
  `web/index.html`. Keep the two in step.

## TUI rules

Read `docs/tui/design.md` before you change the UI. `docs/tui/plan.md` has the layout and the
contracts.

- `tui/__init__.py` and `tui/bootstrap.py` use only the standard library. Nothing that `serve.py`
  imports may import Textual.
- The shared core is `AtlasAPI` in `core/api.py`, with one method for each `/api` route. Both
  clients call it. View rules come from `core/views.py`; never derive them again in the TUI.
- Styles go in each widget's `DEFAULT_CSS`. Never use `CSS_PATH`, because it fails in a zipapp.
- Widgets use only the `$atlas-*` theme tokens, plus the Textual tokens that `plan.md` lists.
- `tui/keys.py` is the one table of keys. The key bar, the help, and the palette read it.
- Check visuals with `uv run python scripts/tui_shot.py`. It renders the demo data to SVG and PNG
  in `out/shots/`.
