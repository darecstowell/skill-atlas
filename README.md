# Skill Atlas

A browsable inventory of every Claude Code skill installed on this machine. Run it whenever you
want to see what you have, what is switched on, and where it came from.

```bash
./atlas            # serve on 127.0.0.1:7381 with working switches, open in the browser
python3 build.py   # rebuild only
python3 build.py --json > skills.json   # raw records to stdout
```

No dependencies. Python 3.9 or later, standard library only.

## What it scans

`config.json` names the roots. Defaults:

| Source | Where | Notes |
| --- | --- | --- |
| Personal skills | `<config root>/skills` | Symlinks are resolved, so one skill shared by two roots is listed once. |
| Plugin skills | `<config root>/plugins/cache/<marketplace>/<plugin>/<version>/skills` | Every cached version, live or superseded. |
| Project skills | `<project root>/**/.claude/skills` and `.agents/skills` | Depth is capped by `project_scan_depth`. |

Bundled skills that ship inside the Claude Code binary are not on disk, so they cannot be scanned.
The header says whether `disableBundledSkills` is set.

## What "status" means

- **enabled** — a personal skill, or a plugin skill whose plugin is `true` in `enabledPlugins`.
- **disabled** — the plugin is installed but set to `false` in `enabledPlugins`.
- **installed** — the plugin is installed and has no entry in `enabledPlugins`.
- **stale** — a cached plugin version that is not the one recorded in `installed_plugins.json`.
- **project-only** — a skill that loads only while you work inside that project.

Personal skills have no per-skill off switch, so they always read as enabled. The separate
**invocation** field is the real gate on their behaviour: `disable-model-invocation: true` in the
frontmatter means only you can call the skill by name, and the model will never reach for it.

## Reading the page

Skills are grouped as your skills, plugins, and project skills. Use the switch at the top to pick
which settings file (`personal` or `work`) the page reads. By source splits your skills by the repo they were
installed from; each source has a switch that turns all of its skills on or off together. Search matches name, description, plugin,
project, and path. Terms are ANDed. All / On / Off filters by the current state.

Project skills and old plugin versions are hidden at first. Check the boxes to show them.

`./atlas` serves the page with working switches. Each change writes the chosen root's
`settings.json` and keeps a one-time backup at `settings.json.atlas-bak`. Restart Claude Code
sessions to pick up a change. The page built by `build.py` is read-only. The switches show the state of `skillOverrides` (one
personal skill) and `enabledPlugins` (a whole plugin). Plugin skills cannot be turned off one by one.

## Updates

A skill is tracked when it has a GitHub source in `~/.agents/.skill-lock.json` (written by
`npx skills`) or in `~/.agents/.atlas-lock.json` (written here, by **Link to GitHub…**). Linking
finds the folder in the repo with the same name as the skill.

On load, `./atlas` reads each source repo's tree from GitHub (through `gh`, then anonymous HTTPS)
and marks a skill out of date when its folder SHA differs from the lock. Results are cached for 10
minutes; "Check again" refreshes them.

Updates download one tarball per repo from codeload.github.com, swap each skill folder in place,
and write the new SHA back to the lock the skill came from, so `npx skills` stays in step. A skill
whose folder no longer matches its lock is tagged **edited**: batch updates skip it, and its own
Update button asks you to confirm, because an update replaces the whole folder.

Plugin skills are not checked.

## Groups and deleting

By source groups skills by repo. Untracked skills that share a name prefix (three or more, such as
`emil-*`) get their own group. A **same as** tag marks skills whose description matches another one.

Delete moves a skill folder to the macOS Trash and removes its lock entries and `skillOverrides`
setting. The toast offers Undo for the last delete.

Keys: `/` focuses search, `Esc` clears it or closes the detail panel, arrow keys move through the list.

## Layout

- `scan.py` — reads the config roots and returns one record per skill.
- `build.py` — writes `out/skills.json` and inlines it into `out/index.html`.
- `template/index.html` — the viewer, with a `__SKILL_ATLAS_DATA__` placeholder.
- `out/` — generated, not tracked.
