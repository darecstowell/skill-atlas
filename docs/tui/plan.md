# Plan: Skill Atlas TUI ("Ledger")

## Goal

Add a terminal client with full parity with the web page. `atlas` still opens the web page.
`atlas tui` opens the TUI. Both clients call one shared Python core.

The design is concept A, "Ledger": a grouped skill list on the left, a detail panel on the right,
view tabs with counts on top, and a key bar at the bottom. The Finder action menu from concept D
is added through the command palette.

## Decisions

- **Library: Textual `>=8.2,<9`.** Pure Python. It has tables, tabs, a Markdown viewer with an
  outline, sparklines, modal screens, a command palette, themes, workers, and mouse support.
- **The web path stays standard library only.** Nothing that `serve.py` imports may import
  Textual. `skill_atlas.tui.__init__` and `tui/bootstrap.py` are standard library only.
- **First-run install.** When Textual is missing, `atlas tui` asks before it installs it. It
  installs pinned, hashed packages with `pip install --target` into a private folder, then adds
  that folder to `sys.path`. This works on Homebrew and Debian Python (PEP 668), in a clone, in
  uvx, and in the `.pyz`.
- **No `CSS_PATH`.** It fails inside a zipapp. Each widget keeps its styles in `DEFAULT_CSS`.
- **The TUI calls the core in-process.** No HTTP between the TUI and the core.
- **No git commits.** All changes stay uncommitted in the `tui` worktree.

## Layout

```
src/skill_atlas/
├── core/
│   ├── api.py         # AtlasAPI protocol: one method per /api route (done)
│   ├── atlas.py       # Atlas: the real implementation, moved out of serve.py
│   ├── views.py       # view rules ported from web/index.html
│   └── demo.py        # DemoAtlas: deterministic fake data, used by tests and screenshots
├── serve.py           # thin HTTP layer over core.Atlas
├── __main__.py        # routes `tui` to skill_atlas.tui, everything else to serve.main
└── tui/
    ├── __init__.py    # stdlib only: launch(argv) -> bootstrap, then app
    ├── bootstrap.py   # stdlib only: first-run install of Textual
    ├── requirements.txt  # pinned with hashes
    ├── app.py         # AtlasApp: layout, state, data loading, workers
    ├── state.py       # UIState and saved display preferences
    ├── messages.py    # messages the widgets send
    ├── theme.py       # 5 palettes x light and dark, as Textual themes
    ├── keys.py        # one table of every key binding; the key bar and help read it
    ├── commands.py    # command palette providers (the Finder action menu)
    ├── jobs.py        # update and install jobs, progress, toasts, undo
    ├── widgets/       # header, viewstrip, skill_list, bulkbar, detail, sidepanel,
    │                  # keybar, charts, switch, toast
    └── screens/       # reader, diff, history, confirm, profiles, transfer, link, help
scripts/tui_shot.py    # render a screen to SVG and PNG for review
docs/tui/              # plan.md, design.md, parity.md, review notes
tests/tui/             # Pilot tests and snapshot checks
```

## Shared core

`core/api.py` defines `AtlasAPI`. `Atlas` (real) and `DemoAtlas` (fake) both satisfy it.

- `core/atlas.py` takes its roots and repo path in its constructor. It holds the glue that is in
  `serve.py` today: `roots()`, `toggle()`, `profile_call()`, `scanned_record()`, the import
  plan and apply steps, and the last-scan cache. `serve.py` routes call it and keep the same
  JSON. `tests/test_serve.py` must pass without changes.
- `core/views.py` ports the derived rules from `web/index.html` into pure functions:
  switch state per harness (`state`), `loads`, `inView`, `visible` for each view, view counts,
  groups (by source or scope, prefix groups, "Local, no upstream"), search, outdated, new,
  unused, costly, risky, similar and diverged, "Needs attention" items, and context cost.
  Inputs are plain dicts: the scan, the update check, the usage snapshot, and a `UIState`.
  The web page keeps its JavaScript for now. A later change can make it read these results
  from `/api/data`, so the rules exist once.
- `core/demo.py` builds about 400 skills across real-looking sources and all harness kinds, with
  updates, new skills, problems, security findings, similar and diverged copies, usage, history,
  diffs, and profiles. Its shapes match the real module output exactly. Writes change its
  in-memory state, so the TUI reacts as it does for real. `atlas tui --demo` uses it.

## TUI architecture

- `AtlasApp` owns `atlas: AtlasAPI`, `state: UIState`, and `data` (the scan plus updates, usage,
  and available skills). It loads data in thread workers and sends `DataChanged`.
- Widgets read `app.state` and `app.data`, and call `app.atlas` in workers. They never block the
  event loop.
- Writes are optimistic: the switch changes at once, then reverts with a toast if the write
  fails.
- Undo (`z`) covers toggles, bulk toggles, and delete. Delete moves to the Trash and shows a toast
  with the undo key.
- Jobs (update, install) poll `atlas.job()` and drive a thin progress bar under the header.
- Over SSH (`SSH_TTY` set): hide "Reveal in Finder". Copy uses OSC 52 through
  `app.copy_to_clipboard`, plus `pbcopy` on a local macOS session, because Terminal.app ignores
  OSC 52.
- Avatars become a one-letter badge in the source's hue. Background textures do not apply.
- **Full mouse use is required.** Every feature works with the mouse alone (typing aside):
  click, double-click, right-click menus, shift-click ranges, wheel, draggable scrollbars and panel
  divider, tooltips on glyph-only targets, clickable key hints and dialog buttons. The rules are in
  `design.md` §13. Each screen's tests include a mouse-only path (`pilot.click`).

### Contracts between agents

- `skill_atlas.tui.app.run(demo: bool = False) -> int` starts the app. `tui/__init__.py` calls it
  after bootstrap.
- `skill_atlas.core.atlas.default() -> Atlas` builds the real Atlas from the same config as
  `serve.py`. `DemoAtlas(n: int = 400, seed: int = 7)` builds the fake one.
- Theme variables. Widgets use only these names in `DEFAULT_CSS`, plus Textual's own
  `$background`, `$surface`, `$panel`, `$foreground`, `$primary`, `$accent`, `$success`,
  `$warning`, `$error`, `$boost`:
  `$atlas-surface-1`, `$atlas-surface-2`, `$atlas-surface-3`, `$atlas-text`, `$atlas-muted`,
  `$atlas-faint`, `$atlas-accent`, `$atlas-accent-tint`, `$atlas-on-accent`, `$atlas-border`,
  `$atlas-border-strong`, `$atlas-selection`, `$atlas-mark`, `$atlas-on`, `$atlas-off`,
  `$atlas-spark`, `$atlas-heat-0` to `$atlas-heat-4`, `$atlas-add`, `$atlas-add-bg`,
  `$atlas-del`, `$atlas-del-bg`, `$atlas-warn`, `$atlas-warn-tint`, `$atlas-danger`,
  `$atlas-danger-tint`. Pure renderers (rows in the list) get the same names from
  `theme.colors(app)` as a dict of hex strings.

### Keys

Keep the web keys where a terminal can send them.

| Key | Action |
| --- | --- |
| `/` | Search |
| `j` / `k`, arrows | Move |
| `enter` | Open the detail panel |
| `x` or `space` | Turn the skill on or off |
| `u` / `i` | Update / install |
| `v` / `r` | Reader / formatted or Markdown in the reader |
| `c` | Compact rows |
| `m`, `shift+j/k` | Mark / extend marks |
| `ctrl+a` | Mark all shown (list focus only) |
| `z` | Undo |
| `ctrl+k` | Actions for the selected skill (Finder menu) |
| `ctrl+p` | All commands |
| `1`–`9` | Views; `[` / `]` previous and next harness |
| `\` | Show or hide the detail panel |
| `?` | Help |
| `q` | Quit |

Do not bind `ctrl+c`, `ctrl+z`, `ctrl+s`, or `ctrl+q`. Terminals use them.

## Design rules

`docs/tui/design.md` translates the emil skills to the terminal and is the rulebook for every
screen. Builders load the skills that apply to their slice:

- `emil-design-foundations`: hierarchy by subtraction, one primary action per view, every state
  designed, specific copy, empty states that say what to do next.
- `emil-color`: palettes derived in OKLCH from the web tokens; contrast checked in code.
- `emil-surfaces`: depth from background steps first, borders only where they carry meaning.
- `emil-animations`: short ease-out entrances, faster exits, `TEXTUAL_ANIMATIONS=none` and a
  display setting for reduced motion.
- `emil-performance`: the list renders only visible lines; no widget per row; scans in workers;
  skeleton rows while loading.
- `emil-ui-polish`: right-aligned numbers, `…` for truncation, stable layout while data loads,
  focus that is always visible.
- `emil-ui-review`: used by the review rounds.

## Verification

- Cheapest first: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`,
  `uv run pytest -q`.
- Pilot tests drive keys headless with `DemoAtlas`. Tests never touch the real `~/.claude`,
  `~/.agents`, or other harness homes.
- `scripts/tui_shot.py` renders a screen after a key sequence to SVG and PNG (`rsvg-convert`) at
  80x24, 120x36, and 180x50, in dark and light. Reviewers read the PNGs.
- `docs/tui/parity.md` lists every web feature. Each row gets a TUI key path and a test or a
  screenshot before the work is done.

## Build order

1. **Foundations, in parallel:** `core/atlas.py` and the `serve.py` refactor; `core/views.py`;
   `core/demo.py`; bootstrap and `__main__` routing; `theme.py`; app shell, `state.py`,
   `messages.py`, placeholder widgets, and `tui_shot.py`; `charts.py` and `switch.py`;
   `design.md`; `parity.md`.
2. **Screens, in parallel:** header; view strip and search; skill list; bulk bar; detail panel;
   side panel; reader; diff, compare, and history; delete, profiles, import and export, link,
   and watch; keys, help, and command palette; jobs, toasts, and undo.
3. **Review rounds:** `emil-ui-review` on screenshots and code, by area. Builders fix their own
   areas. A parity audit against `parity.md`. A performance pass at 400 and 2,000 skills.
4. **Docs:** README TUI section and keys, AGENTS.md rules, CONTRIBUTING.

## File ownership

One agent owns each file. To change a file you do not own, report the change you need.
Run `ruff format` and `ruff check` on your own files only. Never run git commands that change the
tree or the index (`checkout`, `reset`, `stash`, `add`, `commit`).

## AGENTS.md change

Replace "Standard library only at run time" with: the web path is standard library only. The TUI
installs its pinned dependencies on first use, after the user agrees.

## Deviations

Record changes to this plan here.

- Bootstrap: the private folder is `<hash12>-py3.X`. The pins differ by Python version
  (platformdirs), so one folder per Python minor version. pip also gets `--no-compile`
  (11 MB instead of 23 MB). Old folders from earlier pins are not removed yet.
- Parity: `parity.md` has 401 rows (P1 to P401), one per behavior. 16 rows are `n/a`.
- Core: `AtlasAPI` gained `repos()` (source description and stars). `Atlas` also keeps
  `server_info()`, which the TUI does not need. `source_hash` now covers `core/*.py`.
- Views: the API is larger than planned (tags, row state, bulk plan, empty states, heatmap,
  group detail). Folded group ids go to `sections()` as an argument, with the web's keys.
  Checked against the page's own JavaScript in Node: 352 filter combinations x 6 data variants
  x 3 time zones, 0 differences. Three web oddities stay for parity. One fix: "all" skips harness
  ids that are not in the scan (the JavaScript recursed forever there).
- Design: `design.md` §14 lists 9 changes from the mockup (no frames, neutral focus bar, 3-cell
  switch, no brackets on key hints, web strings). Accepted.
- Mouse: full mouse use became a requirement (`design.md` §13).
- Shell: breakpoints follow `design.md` §11 (drawer below 100 columns, "too small" below 60x16).
  `reduced_motion` sets the `basic` animation level; `SSH_TTY` defaults to `basic`. Digit keys
  follow `views.VIEWS` order. New saved fields: `panel_width`, `collapsed`, `folded`. New state
  `selected_key` and message `ItemSelected` for group headers and available skills.
- Demo: `DemoAtlas(n=400, seed=7, *, now=None)`. Pass a fixed `now` for reproducible screenshots.
- Theme: selection and mark backgrounds changed so hover, focus, pressed, and marked differ.
  256-color terminals (SSH without `COLORTERM`) get snapped variants; `atlas tui --truecolor` and a
  one-line hint cover terminals that support true color.

## Wave 2 contracts

Read this before you build a screen.

**App API** (from `tui/app.py`, `state.py`, `messages.py`):
- `app.atlas` (AtlasAPI), `app.state` (UIState), `app.data` (AtlasData: `scan`, `usage`, `updates`,
  `loading`, `errors`, `skills`, `harnesses`, `available`, `insights`, `skill(path)`).
- `app.set_state(**fields)` sends `StateChanged(fields)`. `app.reload(parts, refresh=False)`.
  `await app.fetch(fn, *args)` runs a blocking call on a thread. `app.show_detail(bool)`.
- Messages: `SkillSelected(path, open)`, `ItemSelected(key, open)` for a group id or
  `a:<repo>:<path>`, `StateChanged`, `DataChanged`. The app delivers the last two to every widget
  that handles them. `JobChanged(view)` comes from `jobs` through `app.broadcast(lambda: JobChanged(v))`;
  `view` is `None` when the job ended. `jobs.state_of(app, name)` gives a row's job state.
- `widgets.app_of(widget)` gives the typed app. `UIState.view_state()` gives `views.ViewState`.
- `screens.AtlasModal[R]`: esc and a click outside close it (`CLOSE_ON_OUTSIDE = False` opts out).
  `screens.CloseCell()` is the 3-cell `✕`.
- Rules come from `core.views`. Never derive a rule again in the TUI.

**Keys:** `keys.py` is the one table. Any key can run `run('module:function')`; the app imports
`skill_atlas.tui.<module>` and calls `function(app)` (sync or async). No `app.py` edit is needed.

**Feature functions.** Each owner writes these with exactly these names. Arguments after `app` are
optional; with none, the function acts on the current selection or marks.
- `jobs`: `toggle(app)`, `set_switch(app, harness, names, on, kind="skill")`, `update(app,
  names=None)`, `update_all(app)`, `install(app, repo=None, paths=None)`, `install_new(app)`,
  `check_again(app)`, `undo(app)`, `delete(app, names)` (after the confirm), `copy(app, text,
  what)`, `copy_prompt(app, names=None)`, `reveal(app, path=None)`, `open_github(app, url=None)`,
  `toast(app, text, *, severity="information", action=None)` where action is
  `(key, label, callback)`, `push_undo(app, label, callback)`.
- `screens.reader`: `open_reader(app, path=None)`.
- `screens.diff`: `open_diff(app, name=None)`, `open_compare(app, a=None, b=None)`.
- `screens.history`: `open_history(app, name=None)`.
- `screens.confirm`: `confirm_delete(app, names=None)`.
- `screens.profiles`: `open_profiles(app)`, `save_profile(app, names=None)`,
  `apply_profile(app, name)`.
- `screens.transfer`: `open_export(app)`, `open_import(app)`, `open_restore(app)`.
- `screens.link`: `open_link(app, names=None)`, `open_watch(app)`.
- `screens.help`: `open_help(app)`.
- `commands`: `AtlasCommands` (the `ctrl+p` provider), `open_actions(app, target=None)` where
  target is a skill path or an item key (the right-click and `ctrl+k` menu).
- `widgets.sidepanel`: `open_display(app)` shows and focuses the Display section.

Import other owners' modules inside the function that uses them, not at the top. Their modules
are built at the same time. Until one exists, test your part with a monkeypatched stub.

**Parity:** do not edit `parity.md`. List the P numbers you finished in your final report.
**Shared files** (`app.py`, `state.py`, `messages.py`, `screens/__init__.py`,
`widgets/__init__.py`, `plan.md`, `design.md`, `parity.md`): the integrator owns them. Report the
change you need.

## Integration decisions (wave 2)

- `app.notify` routes to `jobs.toast`, so every toast shares one look and one stack.
- Esc order: a pending "Replace my edits" prompt, then a non-empty search, then the drawer, then
  the marks, then focus to the list.
- Digit `9` is Review. Similar and Diverged have no digit (`app.DIGIT_VIEWS`).
- The web's cards layout (`g`, P59, P337) is `n/a`. Compact rows (`c`) cover density.
- Theme mode "system" (P358): `theme.system_shade()` reads `COLORFGBG`, else the macOS look on a
  local session, else dark. It is read once at start. The default mode stays dark, so tests do
  not depend on the machine.
- `AtlasData.missing` loads after each scan (`restore_plan`), for the side panel's "N missing".
- `views._lv` is public as `views.loaded_skills`.
- Known gaps for the review round: the folded-section keys differ (`key:open` in the side panel,
  `+key` in the detail panel); `AtlasData` should cache available descriptions and per-harness
  counts; headless screenshots of a modal show no screen behind it (Textual export).

## Review round 1 decisions

- `AtlasApp.current()` returns (skill path, item key): the selection, else the list's cursor row.
  Every key that acts on "this skill" reads it, so a key never acts on a row that is not shown.
  The list clears the selection when a view or search hides it.
- One shared `HintButton` in `screens/__init__.py` for every dialog and screen button.
- The terminal title carries the web's tab badge, "(3↑ · 2 new) Skill Atlas" (OSC 2). `atlas tui`
  pushes the terminal's title at start and restores it at exit.
- A failed load shows in one place: the first scan in the list's empty state, later failures in
  the error band. No toast repeats it.
- In 256 colors, the card tints (accent, warn, danger) take a quiet grey when no cube color is
  near the tint; the title and glyphs carry the tone.
- `updates.fetch_raw(repo, path)` is the public raw GitHub read; `AtlasAPI.available_text` uses it.
- `theme.identity(hue, dark)` is the public identity-color helper.
- Ownership changes: the integrator owns `keybar.py` and `theme.py`; the detail builder owns
  `charts.py` and `switch.py`.
- The read-only build rows (P25, P370) are `n/a`: the TUI always runs on a writable core.
- Layout classes sit on the smallest node (`#detail-pane.-narrow`, `#list.-peek`, `#bulkbar.-on`,
  `#viewstrip.-off`); the panels toggle with `.display`. A class on the App restyles every widget.
- A load sends `LoadStarted(part)` at its start and `DataChanged` only at its end. `Insights`
  builds on the worker thread (`AtlasData.basis`, `build`, `put`).
- `state.motion` (full, reduced, off) replaces `reduced_motion`; an old saved `true` loads as
  reduced.
- Deferred: mounting the panels after the first paint (cross row 7) made a timer divide by zero
  at exit, so the panels still compose with the app.
