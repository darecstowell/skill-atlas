# TUI design rules

The rulebook for every TUI screen. Builders follow it; reviewers cite its section numbers. It
translates the `emil-*` skills to Textual 8 on a monospace grid. The web page
(`src/skill_atlas/web/index.html`) is the reference for words, tokens, and behavior. Where this file
and a skill disagree, this file wins in the terminal.

## 1. Principles

1. **The list is the product.** The skill name is the brightest thing on its line. All else recedes:
   muted, faint, or gone. Make hierarchy by subtraction, not with more color.
2. **Keys first, and instant.** A key changes the screen in the next frame. The hot path (move, views,
   toggle, mark, search) never animates and never waits for IO.
3. **One accent, one focus.** The accent means "you can act here" or "this changed upstream". Exactly
   one focus mark shows on screen.
4. **Never color alone.** Each state has a glyph or a word as well as a color. The screen must read
   with `NO_COLOR=1`.
5. **Depth from background steps.** A border shows only where a surface floats or a line divides.
6. **A stable grid.** Nothing moves when data loads, a mark appears, or a number grows.
7. **Every state is designed.** Each element has a look for each state in §7.
8. **Specific words.** Sentence case. Labels name the result. Empty states say what to do next.
   Errors say how to fix the problem.
9. **Optimistic and honest.** Writes show at once and revert with a toast if they fail. Waits over
   400 ms show progress.
10. **Same character as the web.** Same tokens, same strings, same view rules (`core/views.py`).

## 2. Grid and spacing

The unit is one cell. Horizontal spacing uses 1, 2, or 3 cells. Vertical spacing uses 0 or 1 row.
Put space in `padding` on the parent. In grid layouts use `grid-gutter`. In a vertical stack, use
`margin-bottom: 1` and remove it from the last item with `&:last-child { margin-bottom: 0; }`.

App frame, top to bottom:

| Row | Region | Surface | Contents |
| --- | --- | --- | --- |
| 0 | Header | `$atlas-surface-1`, `padding: 0 1` | brand, harness tabs, status at the right |
| 1 | View strip | `$background`, `padding: 0 1` | view tabs with counts, search at the right |
| 2 | Rule | `─` in `$atlas-border` | becomes the progress bar during a job (§8) |
| 3…n-2 | List, panel | `$background`, `$atlas-surface-1` | the panel docks at the right (§11) |
| n-1 | Key bar | `$atlas-surface-1`, `padding: 0 1` | keys at the left, totals at the right |

The bulk bar replaces the view strip on row 1 while marks exist. It never adds a row.

**Skill row.** One line. Columns, left to right:

| Cols | Column | Width | Align | Notes |
| --- | --- | --- | --- | --- |
| 0 | Focus bar | 1 | — | `▌` on the cursor row only |
| 1 | Mark | 1 | — | blank until a mark exists (§6) |
| 2 | gap | 1 | | |
| 3–5 | Switch | 3 | — | blank when the harness has no switch |
| 6–9 | gap | 4 | | cols 8–9 hold the chevron on group headers |
| 10… | Name | see below | left | `/` in `$atlas-faint`, name in `$atlas-text` |
| | gap, Description | 2, flex (min 16) | left | `$atlas-muted`, cut with `…` |
| | gap, Spark | 2, 12 | left | 12 weeks, one cell per week |
| | gap, Count | 1, widest count in view (min 2) | right | `$atlas-muted`; blank for zero uses |
| | gap, Status | 2, 12 (24 when the description keeps 36) | left | first status (§6), a second tag if it fits, then `+N` in `$atlas-faint`, as the web |

- **Name width** is the 80th-percentile `/name` in the current view, clamped to 14–32 cells and to
  40% of the list width. Longer names cut with `…`. Compute it per view, never per screen, so the
  column holds still while you scroll.
- **Column drop order** when the list is narrow: spark, then count, then the status word (its glyph
  stays), then description. When the description drops, the status word comes back if it fits. The
  gutter, switch, and name never drop. All-harnesses dots show at most 5; the tooltip names each.
- **Group header** uses the same columns. The group switch sits in the switch column. The chevron
  sits at col 8, and the group name starts at col 10, in line with the skill names. The meta text
  (`20 of 22 on · 30 available`) follows the name in `$atlas-muted`. The group spark, count, and
  status use the row columns.
- **Section label** (`YOUR SKILLS 42`, `AVAILABLE`) starts at col 3.
- **Pin the group header** of the top visible row on the list's first line while its rows scroll.
- **Regular rows:** one blank row before each group header. **Compact (`c`):** no blank rows, no
  spark, description in `$atlas-faint`. This matches the web's compact mode.

**Numbers.** Monospace digits are already the same width. Alignment is not automatic:

- Right-align every number in a column. Pad to the widest value in the view: `f"{n:>{w}}"`.
- Short forms come from one shared formatter, the same as the web: `1.2k`, `5.4k tokens`, `82%`,
  `2m ago`. Do not write a second formatter in a widget.
- A count that is not known yet shows `–` in `$atlas-faint`, at the width the number will need.

**Panel.** `padding: 1 2`. One blank row between sections. Key-value rows use a 12-cell label column
in `$atlas-muted` and a value column in `$atlas-text`. In **Loaded by**, the harness name is at the
left; the switch, one space, and the word `on` or `off` sit at the right padding edge.

**Measure.** Text in the panel wraps at 64 cells at most. Markdown in the reader is centered and wraps
at 76 cells, the same as the web reader. Key bar pairs are 3 cells apart.

## 3. Type hierarchy

One font, four levels:

| Level | Style | Use for |
| --- | --- | --- |
| Strong | `text-style: bold`, `$atlas-text` | panel title, group names, dialog titles, names in toasts |
| Normal | `$atlas-text` | skill names, values, body text |
| Muted | `$atlas-muted` | descriptions, counts, meta lines, section labels, key bar labels |
| Faint | `$atlas-faint` | `·` separators, `/` of names, disabled text, placeholders, line numbers |

- Bold shows hierarchy, never state. Show the active tab, hover, and focus with background and color.
- A line has at most one bold run.
- Section labels are UPPERCASE, `$atlas-muted`, not bold, 1–3 words: `LOADED BY`, `USAGE · 26 WEEKS`.
  Keep the source string in sentence case and call `.upper()` in the renderer.
- **Italic:** never in the interface. Only inside rendered SKILL.md Markdown in the reader.
- **Underline:** only for real links (OSC 8 URLs). Never for emphasis or actions.
- **Reverse video:** never. It ignores the theme. Override Textual defaults that use it, such as
  `Input > .input--cursor`, with token colors and `text-style: none`.
- **Strike, blink, dim:** never. Use `$atlas-faint`, not `dim`; terminals draw `dim` differently.

| Wrong | Right |
| --- | --- |
| `[b]/copywriting[/b]  [b]When the user…[/b]` | `/copywriting` normal, description muted |
| active tab in bold | active tab on `$atlas-surface-3` |
| `[i]No uses yet[/i]` | `No uses yet` in `$atlas-muted` |

## 4. Color

Use only the theme tokens from `plan.md` ("Contracts between agents"). Never write a hex value in
`DEFAULT_CSS`. Pure renderers get the same names from `theme.colors(app)`. Read that dict once per
theme change, not once per line.

| Token | Use for | Never for |
| --- | --- | --- |
| `$atlas-surface-1/2/3` | background steps (§5) | text |
| `$atlas-text`, `-muted`, `-faint` | the levels in §3 | backgrounds |
| `$atlas-accent` | key letters, `↑ update`, progress, links, the primary hint | focus, decoration |
| `$atlas-accent-tint` | update card, row flash after undo or update | text |
| `$atlas-on-accent` | text on an accent background | anything else |
| `$atlas-border`, `-strong` | separators; floating surface edges; scrollbar thumb | text |
| `$atlas-selection` | the focused cursor row and any focused item | marks |
| `$atlas-mark` | rows marked for bulk actions | focus |
| `$atlas-on`, `$atlas-off` | switch track and knob; `✓ updated` | the accent |
| `$atlas-spark`, `$atlas-heat-0…4` | sparkline bars, heatmap cells | text |
| `$atlas-add/-del`, `-add-bg/-del-bg` | diff lines, `+42 −11` | status |
| `$atlas-warn`, `-warn-tint` | needs a look: edited, similar, issues | errors |
| `$atlas-danger`, `-danger-tint` | broken, failed, high risk, removed | warnings |

- **One accent.** If two accent items compete in one region, demote one to `$atlas-text`.
- **Status colors come with a glyph and a word.** Right: `± edited` in warn. Wrong: `edited` in warn,
  or a warn-colored name.
- **Green means on, added, or done.** It is never the accent.
- **Contrast floors** (a test checks 5 palettes × light and dark):
  `$atlas-text` ≥ 7:1 on every surface, selection, and mark.
  `$atlas-muted` ≥ 4.5:1 on background, surface-1, surface-2, selection, and mark.
  Accent, on, warn, and danger text ≥ 4.5:1 on background, surface-1, and their own tint.
  `$atlas-on-accent` ≥ 4.5:1 on accent. `$atlas-faint` ≥ 3:1 on background and never carries
  needed information alone.
- **256 colors.** Many terminals and tmux setups show only 256 colors. Background, the three surfaces,
  selection, and mark must map to distinct xterm-256 indices (`Color.downgrade(ColorSystem.EIGHT_BIT)`).
- **No color transitions in CSS.** A `transition` on `color` or `background` also fires on a theme
  change. A theme change is instant.

## 5. Surfaces and borders

Separate regions with background steps first:

| Surface | Where |
| --- | --- |
| `$background` | list, view strip |
| `$atlas-surface-1` | header, key bar, panel, a hovered list row, dialogs |
| `$atlas-surface-2` | neutral cards in the panel, a hovered panel row, input fields, skeleton bars |
| `$atlas-surface-3` | toasts, the active view tab, a focused input, a pressed hint |
| tints | update card (`accent-tint`), problem cards (`warn-tint`, `danger-tint`) |

A border earns its place in two cases only:

1. **A surface floats and holds focus:** modal dialogs and the command palette. Use
   `border: round $atlas-border-strong`. A `ModalScreen` keeps its `$background 60%` scrim.
2. **A line divides regions on one surface:** the rule on row 2, and the reader's outline column
   (`border-right: solid $atlas-border`).

- Border styles: `round` for floating surfaces, `solid` for dividers, `none` for everything else.
  Never `heavy`, `double`, `thick`, `tall`, `wide`, `outer`, `hkey`, or `vkey`.
- No border titles. A dialog title is the first line inside, in bold.
- Cards: tint background, `padding: 0 1`, no border, `margin-bottom: 1`.
- Toasts: `$atlas-surface-3`, `padding: 1 2`, no border.
- **Focus is not a border.** Textual widgets draw a focus border by default. Remove it and use §7.
- Scrollbars: `scrollbar-size-vertical: 1`, `scrollbar-size-horizontal: 0`. Thumb
  `$atlas-border-strong`, hover `$atlas-muted`, active `$atlas-text`. The track uses the region's own
  surface, so it disappears.

```css
/* Right: a background step makes the split. */
DetailPanel { background: $atlas-surface-1; padding: 1 2; }
/* Wrong: a frame costs 2 columns and 2 rows and says nothing new. */
DetailPanel { border: round $atlas-border; }
```

## 6. Glyph vocabulary

One set. Each glyph has one meaning. Each glyph must be one cell wide (`rich.cells.cell_len(g) == 1`
in a test). No emoji. No Nerd Font icons: many users do not have them.

| Glyph | Meaning | Color |
| --- | --- | --- |
| `━━●` `○━━` `━◐━` | switch: on, off, mixed. The knob position says the state | on: `$atlas-on`; off: `$atlas-off`, knob `$atlas-muted` |
| `●` `○` | on or off in one harness (All harnesses) | `$atlas-on` / `$atlas-off` |
| `▾` `▸` | open, folded (group headers, panel sections) | `$atlas-muted` |
| `▌` | focus bar on the focused row (col 0) | `$atlas-text` |
| `◆` `◇` `◈` | marked, not marked (shown only while marks exist), some marked (group) | `$atlas-accent`, `$atlas-faint`, `$atlas-accent` |
| `↑ update` | an update is available | accent |
| `± edited` | local edits; batch updates skip it | warn |
| `≈ similar` `≠ diverged` | overlapping description; a copy that differs | warn |
| `! 2 issues` | SKILL.md problems or medium risk | warn |
| `✗ failed` `✗ error` `✗ high risk` | broken, failed, or high risk | danger |
| `✓ updated` `✓ No risky patterns` | done or clean | `$atlas-on` |
| `+ new` | added upstream since the last look | accent |
| `+` `−` | added and removed lines in a diff (U+2212 for minus) | add, del |
| `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` | work in progress (one frame each 80 ms) | accent |
| `▁▂▃▄▅▆▇█` | sparkline levels; a week with no use is `▁` | `$atlas-spark`; zero `$atlas-faint` |
| `■` | one heatmap day | `$atlas-heat-0…4` |
| `━` on `─` | progress: done share on the track | `$atlas-accent` on `$atlas-border` |
| `·` | separator, one space on each side | `$atlas-faint` |
| `…` | text continues: cut text, `Delete…` (asks first), `Checking…` (running) | inherits |
| `–` | value not known yet | `$atlas-faint` |
| `→` | from and to: `a3f9c1e → 7d20b4a`, `on → off` | `$atlas-muted` |
| `↗` | opens in the browser | `$atlas-muted` |
| `‹` `›` | more tabs past this edge | `$atlas-faint` |

- The first status on a row, by priority: busy, done, failed, update, edited, error, risk, issues,
  diverged, similar, new. Then one more tag if it fits, then `+N` (its tooltip names the rest), as
  the web shows 2 tags and `+N`. Plain tags (`runs code`, `you only`) are `$atlas-faint`.
- The brand is ` ╱ ` in `$atlas-on-accent` on `$atlas-accent`, then **Skill Atlas**, like the web logo.
- Write keys as their names, lowercase: `enter`, `esc`, `space`, `tab`, `ctrl+k`, `shift+j`. Not `⏎`.
- Never type `...`. Use `…`.

## 7. States

Focus has one look everywhere: `$atlas-selection` background. Row-shaped items (list rows, group
headers, panel rows, panel section headers) also show `▌` in col 0. When the list loses focus, its
cursor row keeps a `$atlas-surface-2` background and drops the bar.

| Element | Default | Mouse hover | Focus / cursor | Selected / active | Marked | Disabled |
| --- | --- | --- | --- | --- | --- | --- |
| Skill row | §2 columns | `$atlas-surface-1` | selection + `▌` | — | `$atlas-mark` + `◆`; cursor wins the background | off: name muted, description faint, spark faint |
| Group header | bold name, muted meta | `$atlas-surface-1` | selection + `▌` | — | `◆` or `◈` | — |
| View tab | label muted, count faint | label `$atlas-text` | not focusable; keys `1`–`9` | `$atlas-surface-3`, label text, count muted | — | count `–`, no hover |
| Switch | §6 | via its row | via its row | — | — | all cells `$atlas-faint`, knob left |
| Key hint | key accent; label text (content) or muted (key bar) | `$atlas-surface-2` under the hint and 1 cell each side | selection (dialogs only) | primary: ` u Update ` on accent | — | key and label faint, no hover |
| Input | `$atlas-surface-2`, `/` and placeholder faint | — | `$atlas-surface-3`, cursor block in `$atlas-text` | — | — | text faint, no cursor |
| Panel section | `▾ LABEL` muted | `$atlas-surface-2` | selection + `▌` | folded: `▸` + summary at the right | — | — |

| Element | Busy | Error | Empty | Loading |
| --- | --- | --- | --- | --- |
| Skill row | status `⠋ updating`; `queued` in muted | status `✗ failed` | — | skeleton (below) |
| Group header | `⠋ 3 of 8` in status | `✗ 2 failed` | the group hides | skeleton name bar |
| View tab | — | — | count `0`; Issues, New, Costly, Review hide at `0`, as on the web | count `–` |
| Switch | none: writes are optimistic | reverts, then a toast | — | `━━━` skeleton in `$atlas-surface-3` |
| Key hint | label `Updating…`, spinner in place of the key | — | — | — |
| Input | — | `✗` line below in danger, with the fix | placeholder | — |
| Panel section | summary `Reading sessions…` | summary `✗ Could not read sessions` | summary from the web: `Nothing to do` | same as busy |

- **Skeleton rows** keep the real row grid: gutter, a `━━━` switch, a name bar of 10–20 cells (at
  most the name column less 2; group bars at most the name column plus 4) and a description bar of
  40–70% of its column. Each bar is `━` glyphs in `$atlas-surface-3` on `$background`, never cell
  backgrounds. Widths come from the row index, so they do not change between frames. No shimmer.
- **Hover** never changes text, weight, or width. Reserve every cell that hover uses (the `◇` mark,
  the hint padding).
- **Pressed** (mouse down on a hint): `$atlas-surface-3` until mouse up. Act on mouse up.

## 8. Motion

Motion is feedback, not decoration. When in doubt, do not animate.

**Never animate:** `j`/`k`, arrows, page keys, `1`–`9`, `[`/`]`, typing, `x`, `m`, `c`, `\` in the
docked layout, opening the help, palette, reader, or a dialog. Cursor-follow scrolling passes
`animate=False` (`scroll_to_region` and `scroll_visible` animate by default).

**May animate:**

| Motion | Enter | Exit | Easing (Textual) | Level |
| --- | --- | --- | --- | --- |
| Drawer panel (< 100 cols), `offset-x` | 0.20 s | 0.15 s | `out_quart` / `in_cubic` | `full` |
| Toast, `opacity` | 0.15 s | 0.10 s | `out_cubic` / `in_cubic` | `full` |
| Switch knob, mouse click only | one in-between frame (`━●━`) for 0.06 s | — | — | `full` |
| Bulk cascade: switches flip top to bottom | 18 ms per row, 0.14 s in total at most | — | linear steps | `full` |
| Row flash after undo or update | 0.7 s fade from `$atlas-accent-tint` | — | `out_cubic` | `basic` |
| Progress fill on the row-2 rule | 0.28 s per step | fades 0.18 s after done | `out_quart` / `in_cubic` | `full`, else instant |
| Spinner | 80 ms per frame | — | linear | `full`, else hidden |

- Exits are faster than entrances, by 25–35%.
- Always pass `easing=`. The Textual default is `in_out_cubic`, which is wrong for an entrance.
- Never use `in_*` for an entrance. Never use `*_back`, `*_elastic`, or `*_bounce`.
- CSS `transition` is allowed only on `offset` and `opacity`, for the drawer and the toast.
- Web tokens to Textual: `--ease-out` → `out_quint`, `--ease-out-quart` and `--ease-drawer` →
  `out_quart`, `--ease-in-cubic` → `in_cubic`, `--ease-swap` → `out_cubic`.
- Animate only what is on screen. Stop each interval timer (spinner, flash) when no visible line needs it.

**Reduced motion.** Textual has three levels. CSS transitions and `animate()` default to `full`.

| Level | How to get it | What runs |
| --- | --- | --- |
| `full` | default | everything in the table |
| `basic` | Display → Motion → Reduced; the default over SSH (`SSH_TTY` set) | color fades only; no movement, no spinner |
| `none` | `TEXTUAL_ANIMATIONS=none`; Display → Motion → Off | nothing; final values at once |

When `TEXTUAL_ANIMATIONS` is set, it is the ceiling: the display setting can lower motion, never raise
it. Without a spinner, the label (`Checking…`) carries the state.

## 9. Feedback

- **Optimistic writes.** A toggle shows in the same frame as the key. The write runs in a worker. If it
  fails, the switch reverts and a toast says why: `Could not save: settings.json is read-only. Check its
  permissions.` No spinner on a toggle.
- **One toast at a time.** A new toast replaces the old one at once, with no exit motion.
- **Toast duration** comes from word count: `max(4 s, 0.3 s × words)`. Toasts with undo and error
  toasts use `max(8 s, 0.3 s × words)`. Mouse over a toast pauses it; mouse out gives 2.5 s more.
- **Undo toasts** end with the hint `z Undo`. Use the web strings: `Turned ads off. Restart Claude
  Code sessions to pick it up.` `Moved 3 skills to the Trash.` After undo: `Put back 3 skills.` and a
  row flash on each restored row.
- **Copy confirmation** names what went to the clipboard, cut to 48 cells: `Copied 3 skills:
  /ads /aso /seo`. With OSC 52 alone (SSH, no `pbcopy`), do not claim success: `Sent the path to your
  terminal's clipboard.`
- **Long waits.** If work still runs at 300 ms, show an indicator. Once shown, keep it for 500 ms or
  more, so it does not flash. Where it shows:
  first scan → skeleton rows; rescan → old data stays, header says `Scanning…`;
  one update → status column; a job → progress on the row-2 rule and `Updating 3 of 8` in the header;
  usage index → `Reading sessions…` in the panel section.
- **Done.** A row shows `✓ updated` for 2 s, then the row flash. A job ends with one toast:
  `Updated 8 skills. Restart Claude Code sessions to pick them up.`
- **Input never blocks.** Keys work during jobs. A second job gets the web toast
  `Another job is still running.`
- **Destructive confirms.** `enter` never runs a destructive action. The dialog names a letter key for
  it, and `esc` cancels. Delete always says where things go: `Move 3 skills to the Trash?`

## 10. Copy

- Sentence case for every label, title, and message. Section labels are uppercased in code (§3).
- Key bar labels are one or two lowercase words: `move`, `open`, `toggle`, `help`.
- Labels name the result: `See changes`, `Update`, `History (5)`, `Check again`, `Move to Trash`.
  Never `OK`, `Submit`, `Yes`, or `Done` alone.
- Front-load the important word. No "please". No exclamation marks.
- Errors: `Could not <verb>: <reason>. <how to fix>.` Right: `Could not reach GitHub: the request timed
  out. Check your network, then press r to check again.` Wrong: `Error: request failed.`
- A too-small window says what it needs: `The window is 52 × 14. Skill Atlas needs at least 60 × 16.`
- Use the web strings where they exist, word for word. Empty states (title, then body, then action):

| View | Title | Body | Action |
| --- | --- | --- | --- |
| Search | `No skills match “<q>”` | `Try fewer or shorter words.` or `The <view> filter is on.` (+ `<n> hidden skills match.`) | `esc Clear search` |
| Updates | `Everything is up to date` | `Checked 2m ago.` / `Checked just now.` / `No check has run yet.` | `Check again` |
| New | `No new skills` | `Checked …` + `Your sources have not added skills since you last looked.` | `Check again` |
| Issues | `No problems found` | `Each SKILL.md in this view has valid frontmatter, and each file it names is there.` | `Show all skills` |
| Similar | `No similar skills` | `No two skills in this harness have descriptions that overlap a lot.` | `Show all skills` |
| Diverged | `No diverged copies` | `Each copy of a skill has the same SKILL.md as the others.` | `Show all skills` |
| Review | `Nothing to review` | `No skill in this view has high-risk patterns. A heuristic scan of the files. It can miss real risks and flag safe code.` | `Show all skills` |
| Unused | `Every skill is in use` | `Each one ran in the last 90 days.` | — |
| Costly | `No costly skills sit unused` | `Each costly skill that is on ran in the last 90 days.` | `Show all skills` |
| Off | `Nothing is off` | `Every skill in this view loads.` | — |
| Other | `No skills here` | `Turn on Project skills or Old plugin versions to see more.` | — |

The empty state fills the list area: title bold, one blank row, body muted (wrap at 60 cells), one
blank row, then the action as a key hint. Center it, one third down from the top.

## 11. Responsive layout

Check every screen at 80×24, 120×36, and 180×50 (`scripts/tui_shot.py`).

| Width | Layout |
| --- | --- |
| < 60, or < 16 rows | only the too-small message (§10) |
| 60–99 | list only. `enter` opens the panel as a drawer from the right, width `min(cols − 8, 64)`, over the list. `esc` closes it. The brand shows only its logo. Harness tabs show the active harness and `2 of 9 ›` in faint. Search hides until `/`, then takes the view strip row. |
| 100–119 | panel docked at the right, width 40. The spark drops first (§2). |
| 120–159 | panel width `round(0.34 × cols)`. All harness tabs show if they fit, else as at 60–99. Search shows at the right of the view strip, 28 cells wide. The reader shows its outline column (28 cells). |
| ≥ 160 | panel width `min(round(0.34 × cols), 64)`. The key bar shows its right-side totals. |

| Height | Change |
| --- | --- |
| < 30 rows | Usage shows a 26-cell sparkline and its summary line, not the 7-row heatmap. Panel sections that have no saved state start folded, except Loaded by and the update card. |
| ≥ 30 rows | full heatmap. |
| any | Dialogs: `max-height` = rows − 2, with an inner scroll. Toasts: 3 rows at most, right-aligned above the key bar, `max-width: 60`. |

- When tabs do not fit, the strip scrolls to keep the active tab in view, with `‹`/`›` at the edges.
- The key bar never wraps. It drops keys from the right by priority. `? help` and `q quit` stay.

## 12. Performance

- **The list is one line-API widget.** One `ScrollView` subclass with `render_line(y) -> Strip`.
  No widget per row and no widget per group header. Cost follows visible lines, not skill count.
- **Cache rendered lines** in a `textual.cache.LRUCache` keyed by row id, width, data version, and row
  flags (cursor, focus, marked, hover). Clear it on theme change, resize, and `DataChanged`.
- **Refresh only what changed.** A cursor move refreshes two lines (`refresh_line`). A hover refreshes
  two lines. A toggle refreshes one line.
- **Precompute.** Build row text, widths, and `Style` objects once per `DataChanged`. No markup parsing
  and no `views.py` calls inside `render_line`.
- **Workers for all IO**: scan, update check, usage index, writes, `gh`, `pbcopy`. Use
  `@work(thread=True, exclusive=True)` so stale results never land. Never block a handler.
- **Debounce.** Search filters 100 ms after the last key; the input echoes at once. Saved display
  settings write 500 ms after the last change.
- **The panel never slows the list.** While `j`/`k` repeats, the panel renders at most once per 50 ms.
- **Budgets** at 2,000 skills (a Pilot test checks): a key to paint in one frame (16 ms); the shell and
  skeleton paint before the first scan ends.

## 13. Accessibility

- **Never color alone.** Review one screenshot per screen with `NO_COLOR=1`. Switch, mark, focus,
  status, and diff lines must still read. Charts always have a text summary line.
- **Focus is always visible.** Exactly one focus mark on screen. Focus moves only when the user moves
  it, or when its item goes away.
- **Every action has a key and a palette command.** The key bar, help (`?`), and palette read one table
  in `keys.py`. Each click target also has a key.
- **The mouse alone does every task.** A user who never touches the keyboard (except to type a search
  or a name) can reach every feature in `parity.md`. Required:
  - Click a harness tab, a view tab, a key bar hint, a panel action, or a dialog button to run it.
  - Click a row to select it; double-click to open the reader. Click its switch to toggle it. Click its
    mark cell to mark it; shift-click marks a range.
  - Click a group chevron to fold the group; click the group switch and the group `Update N`.
  - Right-click a row or a group (or click its `⋯` cell) to open its action menu, the same menu as
    `ctrl+k`.
  - The wheel scrolls the region under the pointer. Scrollbars can be dragged.
  - Every modal has a clickable close cell (`✕`) and a clickable primary and secondary action.
    A click on the dimmed area outside a modal closes it, except for confirm-delete.
  - Hover shows a tooltip for every glyph-only target (switch, tags, `⋯`, `✕`, spark, heat cell).
  - Drag the divider between the list and the panel to resize the panel.
- **A key never changes its meaning because the data changed.** View numbers stay fixed when a view
  hides.
- **Click targets** are 3 cells wide or more. A switch takes clicks on its 3 cells and 1 cell on each
  side. Two targets never overlap.
- Do not bind `ctrl+c`, `ctrl+z`, `ctrl+s`, or `ctrl+q`. Screen readers get little from a terminal, so
  help (`?`) names the web page (`atlas`) as the client for them.

## 14. Changes from the mockup

The Ledger mockup sets the layout. These details change, each for a rule above:

1. No frames around the list and the panel. A background step does the work and saves 4 columns and
   2 rows (§5).
2. The update card uses `$atlas-accent-tint` with no border, as on the web (§5).
3. Key hints have no brackets: `d See changes`, not `[d] See changes` (§7).
4. The switch is 3 cells, so the knob position shows on, off, and mixed without color (§6).
5. The focus bar is `$atlas-text`, not the accent. The accent stays for "act here" (§4).
6. The active view tab and the active harness tab use `$atlas-text` on `$atlas-surface-3`, not a solid
   accent block (§7). The header row keeps the accent for `Update all` only.
7. The brand is the ` ╱ ` logo cell. `◆` is the mark glyph (§6).
8. The spark shows 12 weeks, as on the web. Similar shows `82%`, not `0.82 overlap`.
9. Web strings replace mockup ones: `no switch` (not `lists only`), `checked 2m ago` (not `⟳ 2m ago`),
   `enter` (not `⏎`).

## 15. Rules that do not apply in a terminal

- Font family, pairing, loading, smoothing, kerning, and weights other than bold and normal.
- Type scale, sizes, leading, tracking (so uppercase labels stay short), `text-wrap: balance`.
- Radii, shadows, elevation stacks, gradients, masks, fades, blur, hairlines, image outlines, textures.
  Avatars become a one-letter badge in the source hue.
- GPU compositing, `will-change`, `transform`, scale on press, springs, bounce, 150 ms hover fades.
- Pixel touch targets, `hover: hover`, iOS input zoom, safe areas, `::selection`, a z-index scale
  (use Textual screens and built-in layers; add no new layers).

## 16. Review checklist

Review the PNGs from `scripts/tui_shot.py` (dark and light, three sizes), one `NO_COLOR=1` shot,
and the code. Check:

- [ ] Only `$atlas-*` and the allowed Textual tokens; no hex in `DEFAULT_CSS` (§4).
- [ ] One accent per region; status colors have a glyph and a word (§4, §6).
- [ ] Background steps first; borders only in the two cases in §5; no focus borders.
- [ ] Columns hold still while scrolling, loading, marking, and as counts grow (§2).
- [ ] Numbers right-aligned in their columns; `…` for every cut; no `...` (§2, §6).
- [ ] No bold for state; no italic, underline, reverse, dim, or strike in the interface (§3).
- [ ] Every element has its states from §7, including empty, loading, and error.
- [ ] Nothing on the hot path animates; scroll calls pass `animate=False` (§8).
- [ ] Each animation has an explicit easing, a faster exit, and the right level (§8).
- [ ] Writes are optimistic and revert with a specific toast (§9).
- [ ] Copy uses web strings, sentence case, specific labels, and errors with a fix (§10).
- [ ] The 80×24 shot works: drawer panel, dropped columns, short key bar (§11).
- [ ] No widget per row; IO in workers; line cache in place (§12).
- [ ] Every action has a key and a palette command; focus is always visible (§13).

**Report format.** Start with one verdict line: **Blocked** (breaks an interaction or §13),
**Approve with changes**, or **Ship it**. Then the findings, most harmful first, in one table under
each of the headings Blocking, Should fix, and Nits:

| Before | After | Why |
| --- | --- | --- |
| `skill_list.py:88` cursor row uses `text-style: reverse` | `$atlas-selection` background and `▌` in `$atlas-text` | §3: reverse ignores the theme |
| 80×24 shot: description pushes the status off the line | drop spark, count, then description | §2: column drop order |

One row per finding. Name the file and line, or the screenshot and size. The Why cell cites a section.
If there are no findings, write **Ship it** and stop.
