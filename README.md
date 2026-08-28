# Skill Atlas

A browsable inventory of every Claude Code skill installed on this machine. Run it whenever you
want to see what you have, what is switched on, and where it came from.

```bash
./atlas            # rescan, rebuild, open in the browser
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

Search matches name, description, plugin, marketplace, project, path, and allowed tools. Terms are
ANDed. Sort by name, modified date, length, scope, status, or plugin.

Two chips start switched off because they bury the live set: `scope: project` (git worktrees repeat
the same skills many times over) and `status: stale`. Turn them on to see everything.

Keys: `/` focuses search, `Esc` clears it.

## Layout

- `scan.py` — reads the config roots and returns one record per skill.
- `build.py` — writes `out/skills.json` and inlines it into `out/index.html`.
- `template/index.html` — the viewer, with a `__SKILL_ATLAS_DATA__` placeholder.
- `out/` — generated, not tracked.
