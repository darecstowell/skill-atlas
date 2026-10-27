<p align="center">
  <img src="assets/banner.png" alt="Skill Atlas" width="100%">
</p>

<p align="center">
  <a href="https://github.com/darecstowell/skill-atlas/actions/workflows/ci.yml"><img src="https://github.com/darecstowell/skill-atlas/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/dependencies-none-6CB2E8" alt="No dependencies">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-8B97A3" alt="MIT license"></a>
</p>

Skill Atlas shows every agent skill on your machine on one local page, for every harness that
loads them: Claude Code, Codex, Cursor, Gemini CLI, Copilot CLI, OpenCode, and more. You can turn
skills on and off per harness, update them from GitHub, install new skills from the repos you
follow, and move old skills to the Trash.

<p align="center">
  <img src="assets/screenshot.png" alt="Skill Atlas, grouped by source, with updates and available skills" width="900">
</p>

## Quick start

```bash
git clone https://github.com/darecstowell/skill-atlas.git
cd skill-atlas
./atlas
```

`./atlas` starts a server on `127.0.0.1:7381` and opens the page. It needs Python 3.10 or later and
nothing else. For a short command, add an alias:

```bash
alias atlas='~/path/to/skill-atlas/atlas'
```

## What it does

| | |
| --- | --- |
| **See everything** | Personal, plugin, and project skills in one list, grouped by the repo they came from. Search covers names, descriptions, sources, and paths. |
| **Switch skills on and off** | One switch per skill, per source, or per plugin. Changes go to `settings.json`, with a backup made first. |
| **Update from GitHub** | Marks skills whose upstream folder changed. Update one skill, one source, or all. About 40 skills update in 3 seconds. |
| **See changes and roll back** | **See changes** on an update shows each added, changed, and removed file, with line diffs. Before each update, the atlas saves the old folder (the last 5 per skill, in `~/.cache/skill-atlas/history`). **History** in the skill panel restores one. |
| **Find new skills** | Lists the skills a source repo has that you have not installed, and tags the ones added since you last looked. |
| **Read a skill** | Press `v` to open the whole SKILL.md in a large reader, formatted or as raw Markdown, with a section outline. |
| **See where it comes from** | Each source shows its owner's GitHub avatar. A source's panel shows the repo's banner, and a skill's panel shows a picture from its own folder when it has one. |
| **Make it yours** | Switch between dense rows and a card grid. Pick light, dark, or the system theme, one of five palettes, and a quiet background texture. |
| **Act on many at once** | Tick skills one by one, shift-click a range, or tick a whole source. Then turn them on or off, update, link, copy them as a prompt, or delete them. |
| **See context cost** | Shows about how many tokens each harness spends in every session to list the skills that are on, and the top five. It marks costly skills that you did not use in 90 days. Sort by **Cost** to put the largest first. |
| **Find problems** | The **Issues** view lists skills with bad frontmatter, a wrong name, a long description, or links to files that are not there. The inventory panel shows lock entries with no folder and folders with no SKILL.md. The atlas does not fix them. |
| **Profiles** | Save which skills are on and off as a named profile, from the **Profiles** menu or from a selection. Apply shows what changes in each harness first, and you can undo it. Profiles go in `~/.config/skill-atlas/profiles.json`. |
| **Move your set** | **Export** in the Inventory panel saves your skills, sources, watched repos, and off switches to a JSON file. **Import** shows what it will install and change, then does it. **Restore** installs again the skills in the lock file that have no folder. |
| **Tidy up** | Delete moves a skill to the Trash, with Undo. A **same as** tag marks skills with the same description. |

## How it works

**Sources.** A skill is tracked when it has a GitHub source in `~/.agents/.skill-lock.json`
(written by `npx skills`) or in `~/.agents/.atlas-lock.json` (written by **Link to GitHub…**).
Untracked skills that share a name prefix, such as `acme-*`, get their own group.

**Update checks.** On load, the atlas reads each source repo's file tree from GitHub (through `gh`,
then anonymous HTTPS). A skill is out of date when its folder SHA is different from the SHA in the
lock. Results stay in a cache for 10 minutes; **Check again** refreshes them.

**Updates and installs.** The atlas downloads one tarball per repo, swaps each skill folder through
a staged copy, and writes the new SHA back to the lock. `npx skills` stays in step.

**Local edits are safe.** A skill whose folder no longer matches its lock is tagged **edited**.
Batch updates skip it. Its own Update button asks first, because an update replaces the whole
folder.

**New skills.** The first check of a repo records a baseline. After that, skills added upstream
get a **new** tag. **Dismiss** clears the tag. **Watch a source…** follows a repo that has none of
its skills installed yet.

## Harnesses and switches

The picker at the top selects a harness. Each switch then changes that harness's own config. **All
harnesses** shows one dot per harness that loads a skill. The skill panel's **Loaded by** list has
a switch for each harness.

| Harness | Reads skills from | A switch writes |
| --- | --- | --- |
| Claude Code | `~/.claude/skills`, plugins | `skillOverrides` or `enabledPlugins` in `settings.json` |
| Codex | `~/.agents/skills`, `~/.codex/skills` | `[[skills.config]]` with `enabled = false` in `config.toml` |
| Gemini CLI | `~/.gemini/skills`, `~/.agents/skills` | `skills.disabled` in `settings.json` |
| Copilot CLI | `~/.copilot/skills`, `~/.agents/skills` | `disabledSkills` in `settings.json` |
| OpenCode | `~/.config/opencode/skills`, `~/.claude/skills`, `~/.agents/skills` | `permission.skill` in `opencode.json` |
| Cursor, Amp, Goose, Windsurf, Cline, Kiro, Roo Code, Antigravity | their own folders | no per-skill switch, so the atlas only lists them |

The atlas shows a harness when its home folder exists. A skill folder that several harnesses read
shows once. Installs, updates, and deletes act on `~/.agents/skills`, the folder `npx skills` uses.
Restart the harness's sessions to load a change.

## Keyboard

| Key | Action |
| --- | --- |
| `/` or `⌘K` | Search |
| `j` / `k` | Move between skills |
| `Enter` | Open the detail panel |
| `x` or `Space` | Turn the skill on or off |
| `u` | Update the skill |
| `i` | Install an available skill |
| `v` | Read the whole SKILL.md |
| `r` | Formatted or Markdown, in the reader |
| `g` | List or cards |
| `c` | Compact rows |
| `m` | Select the skill for bulk actions |
| `⌘A` | Select all skills shown |
| `⌘Z` | Undo the last change |
| `?` | All shortcuts |

## Configuration

No setup is needed. The atlas finds each harness in its usual folder, and also reads
`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, and `COPILOT_HOME` when they are set.

To add project folders, or a second Claude Code config folder, run:

```bash
./atlas init
```

This writes `~/.config/skill-atlas/config.json` with the config folders it finds, and prints it.
Edit it to add `project_roots` or to rename a tab:

```json
{
  "config_roots": { "main": "~/.claude", "work": "~/.claude-work" },
  "harnesses": ["claude-code", "codex", "cursor"],
  "project_roots": ["~/code"],
  "project_scan_depth": 3
}
```

`config_roots` lists Claude Code config folders. `harnesses` is optional: it limits the picker to
these harnesses.

The atlas reads `$SKILL_ATLAS_CONFIG` first, then `~/.config/skill-atlas/config.json`, then a
`config.json` next to the code.

| Source | Where |
| --- | --- |
| Personal skills | Each harness's skill folders (see above). Symlinks are resolved, so a shared folder shows once. |
| Plugin skills | Claude Code: `<config root>/plugins/cache/<marketplace>/<plugin>/<version>/skills` |
| Project skills | `<project root>/**/.claude/skills` and `.agents/skills`, down to `project_scan_depth` |

Skills that ship inside a harness binary are not on disk, so the atlas cannot list them.

## Safety

- The server binds to `127.0.0.1` only. Each API call must send a token that changes every time
  the server starts, so other web pages cannot call it.
- In each harness config, the atlas changes only the skill keys in the table above and keeps the
  rest of the file. It makes a one-time backup (`settings.json.atlas-bak`, `config.toml.atlas-bak`)
  before the first write.
- Deletes go to the Trash (`~/.Trash` on macOS, the freedesktop Trash on Linux), never `rm`.
  Where there is no Trash, delete is not available.
- Plugin skills are not checked for updates.
- The page loads avatars, banners, and the SKILL.md of skills you have not installed straight
  from GitHub, so GitHub sees those requests.

## Without the server

```bash
python3 build.py                        # write a read-only page to out/index.html
python3 build.py --json > skills.json   # print the raw records
```

## Development

The tool uses only the Python standard library. Dev tools run through
[uv](https://docs.astral.sh/uv/):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

| File | Job |
| --- | --- |
| `scan.py` | Reads the config roots and makes one record per skill |
| `serve.py` | Local server and the only writer of `settings.json` |
| `updates.py` | Update checks, updates, installs, and watched sources |
| `assets.py` | Avatars, banners, and image paths for source repos |
| `harnesses.py` | Where each harness looks for skills, and how its switch reads and writes |
| `usage.py` | Counts skill use from session logs of Claude Code, Codex, Gemini CLI, Copilot CLI, and OpenCode |
| `remove.py` | Moves skills to the Trash, and puts them back |
| `build.py` | Puts the records into `template/index.html` |
| `template/index.html` | The page: one file of HTML, CSS, and JavaScript |

Read [CONTRIBUTING.md](CONTRIBUTING.md) before you open a pull request.

## License

[MIT](LICENSE)
