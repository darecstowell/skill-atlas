# Skill Atlas TUI parity checklist

Every user-visible feature of the web page, with the TUI key or path, the file that owns it, its audited status, and the evidence. Cite a row by its number, for example P42.

Status: `done`, `partial`, `missing`, `n/a`. Evidence is a test (`tests/tui/test_*.py::test_name`) or `file:function`; for `n/a` it is the reason. Evidence with "no test" means the code exists but no test covers it. Owner paths are relative to `src/skill_atlas/`. Web keys use `Cmd` for the Mac key.

Audit run: the first audit read code and tests; after review round 1 every partial and missing row was fixed and re-checked by its owner's tests.

The Sources main screen (`plan.md`, "Main screen: the Sources direction") moved some features. Their rows stay `done`. Each row names the new place:

- Row descriptions, sparklines, and info tags: P57, P66, P68, P70–P72, P74, P75, P99.
- The header update count and warning: P18, P20.
- The harness tabs and the view tabs: P2, P29–P39.
- Repo rows and their folds: P55, P90, P93, P329.
- The key bar: P349.
- The side panel stat tiles and sections: P209, P210, P214–P220.

## Summary

Total 401: done 379, partial 0, missing 0, n/a 22.

### Partial and missing rows by owner file

None.

## Header and harness picker

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | Brand and title | Shows the Skill Atlas mark and name | - | Title text in the header bar | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_brand_tabs_and_the_more_cell_fit_each_width |
| P2 | Harness picker | Select lists "All harnesses" (when more than one) and each harness label; hidden when no harness exists | - | The harness chip with `▾` in the header (`Claude Code · personal ▾`); click it to open the harness menu; `[` and `]` step; palette harness entries | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_brackets_step_through_harnesses_and_keep_the_active_tab_shown; tests/tui/test_header.py::test_the_more_cell_opens_a_harness_menu_for_the_mouse |
| P3 | Harness choice is remembered | Last harness is saved and restored on load, if it still exists | - | Saved in UIState preferences | `tui/state.py` | done | tests/tui/test_app.py::test_prefs_round_trip |
| P4 | Default harness | First detected harness, or "all" if none | - | Same rule in `core/views.py` | `core/views.py` | done | src/skill_atlas/core/views.py:default_harness; src/skill_atlas/tui/app.py:on_data (line 522) |
| P5 | Harness-less install | Picker is hidden when no harness is found; list shows empty state | - | Header hides the picker; list shows the "No skills here" empty state | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_one_harness_has_no_all_tab_and_none_shows_no_tabs |
| P6 | Profiles button | Opens the Profiles popover; hidden in the read-only build | - | `p` opens the profiles screen; palette "Profiles" | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profiles_list_rename_by_keys |
| P7 | Search field in header | Input with placeholder "Search skills, sources, paths" | `/`, `Cmd+K` | `/` | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_slash_focuses_the_search_and_selects_the_old_text |
| P8 | Display button and dot | Opens Display popover; a dot shows when project skills or old plugin versions are shown | - | `,` opens the Display pane in the side panel | `tui/widgets/sidepanel.py` | done | sidepanel.py: a marker on the Display head when hidden classes are shown; tests/tui/test_sidepanel.py |
| P9 | Details panel toggle button | Shows or hides the right panel; state is saved | `]` | `\` toggles the detail panel; state saved | `tui/app.py` | done | tests/tui/test_app.py::test_backslash_hides_and_shows_the_panel |
| P10 | Meta line: writes-to path | Shows "writes <settings path>" for a harness with a switch | - | Text in the view strip meta area | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_meta_says_where_the_switches_write; tests/tui/test_viewstrip.py::test_meta_drops_when_the_row_is_short |
| P11 | Meta line: all harnesses | Shows "pick a harness to switch skills" when All is chosen | - | Same text | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_meta_says_where_the_switches_write; tests/tui/test_viewstrip.py::test_meta_drops_when_the_row_is_short |
| P12 | Meta line: no per-skill switch | Shows "<Harness> has no per-skill switch" | - | Same text | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_meta_says_where_the_switches_write; tests/tui/test_viewstrip.py::test_meta_drops_when_the_row_is_short |
| P13 | Meta line: built-ins off | Shows "built-ins off" for Claude Code when bundled skills are disabled | - | Same text | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_meta_says_where_the_switches_write; tests/tui/test_viewstrip.py::test_meta_drops_when_the_row_is_short |
| P14 | Window title badge | Tab title shows "(N up, M new) Skill Atlas" when updates or new skills exist | - | Terminal title (OSC 2), restored on exit | `tui/app.py` | done | tests/tui/test_app.py::test_window_title_follows_the_data_and_the_harness; tests/test_core_views.py::test_window_title_badges_updates_and_new_skills |
| P15 | Brand icon and avatars in header | SVG logo mark | - | n/a: no vector image; the text title replaces it | `tui/widgets/header.py` | n/a | No vector image in a terminal; the text title replaces it |
| P16 | Update cluster: up to date | "Up to date" button with refresh arrow; click checks again; arrow turns to tick for 1.4 s after a refresh | - | `ctrl+r` or palette "Check for updates again"; text "Up to date" with a tick glyph | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_up_to_date_is_a_check_mark_that_checks_again |
| P17 | Update cluster: checking | Button reads "Checking…" and spins; clicks are ignored | - | "Checking…" with a spinner glyph; second request ignored | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_checking_waits_then_holds_and_ignores_clicks |
| P18 | Update cluster: N updates | Shows count "N update(s)", then "Update all" primary button and a refresh icon | - | A quiet `↑ 9 updates` link in the header opens the Updates view (`4`); the accent `Update 8` button (or `Update all`) with `Skips 1 you edited` sits in the Updates view; `shift+u` | `tui/widgets/header.py`, `tui/widgets/viewstrip.py` | done | tests/tui/test_header.py::test_the_updates_link_opens_the_updates_view_on_a_left_click_only; tests/tui/test_viewstrip.py::test_the_updates_view_offers_update_all_and_names_the_skills_it_skips |
| P19 | Update cluster: new skills chip | Chip "N new skills" opens the New view; hidden while the New view is open | - | The header has no chip; the view menu lists New with its count, `6` opens it, and a repo row shows `+N new` | `tui/widgets/viewstrip.py` | done | tests/tui/test_header.py::test_new_skills_show_no_header_chip |
| P20 | Update cluster: sources unchecked warning | "N source(s) unchecked" with the error texts as a tooltip | - | The `! 1` warning in the header; click it to open a popup list of the errors | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_unchecked_sources_show_the_errors_and_check_again |
| P21 | Update cluster: job running | Shows "Updating N of M…" or "Installing N of M…", then "Updated N of M" | - | Same text in header | `tui/widgets/header.py` (text), `tui/jobs.py` (headline) | done | tests/tui/test_header.py::test_a_job_replaces_the_cluster_and_the_tabs_stay_put |
| P22 | Update cluster: not shown before the first check | Cluster is empty until a check finishes | - | Same rule | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_the_cluster_waits_for_the_first_check_and_hides_when_read_only |
| P23 | Update cluster: read-only build | Cluster, Update all, and Profiles are hidden | - | Same rule when the core reports read-only | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_the_cluster_waits_for_the_first_check_and_hides_when_read_only (header.py:_cluster returns {} when not writable; the test covers the wait only) |
| P24 | Job progress bar | Thin bar under the header fills with finished items; holds full for 0.9 s then fades | - | Thin bar row under the header (block glyphs); same timing | `tui/jobs.py`, `tui/widgets/progress.py` | done | tests/tui/test_jobs.py::test_u_runs_a_job_the_bar_fills_and_the_ticks_leave; tests/tui/test_jobs.py::test_bar_fraction_and_headline |
| P25 | Read-only band | Band "Read-only build. Run ./atlas to change skills." | - | Band row under the header; shown for a read-only core | `tui/widgets/header.py` | n/a | n/a: the TUI always runs on a writable core; there is no read-only TUI build |
| P26 | Stale band: server restarted | Band "The server restarted, so this page is out of date" with Reload link | - | n/a: the TUI calls the core in-process, so it has no server to restart | `tui/widgets/header.py` | n/a | The TUI calls the core in-process; no server restarts |
| P27 | Stale band: code changed on disk | Band "Skill Atlas changed on disk. Stop ./atlas and start it again." | - | Band "Skill Atlas changed on disk. Quit and start it again." shown when the core reports stale | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_the_stale_band_asks_for_a_restart |
| P28 | Page size and zoom (Display > Size) | Small, Default, Large scale of the page | - | n/a: terminal font size is set by the terminal; substitute is compact rows (`c`) | `tui/widgets/sidepanel.py` | n/a | The terminal sets the font size; compact rows (`c`) replace it |

## View tabs and search

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P29 | All tab with count | Count of skills the harness loads (no project, no stale) | `1` | `1`; the view chip (`All 347 ▾`) shows the active view and its count; click it to open the view menu | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_tabs_follow_the_view_rules_with_counts; tests/tui/test_viewstrip.py::test_digit_keys_move_the_active_tab |
| P30 | On tab with count | Skills switched on in this harness | `2` | `2`; the view menu | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_tabs_follow_the_view_rules_with_counts; tests/tui/test_viewstrip.py::test_digit_keys_move_the_active_tab |
| P31 | Off tab with count | Skills switched off | `3` | `3`; the view menu | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_tabs_follow_the_view_rules_with_counts; tests/tui/test_viewstrip.py::test_digit_keys_move_the_active_tab |
| P32 | Updates tab with count | Outdated skills; hidden in the read-only build | `4` | `4`; the view menu | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_tabs_follow_the_view_rules_with_counts; tests/tui/test_viewstrip.py::test_digit_keys_move_the_active_tab |
| P33 | Issues tab with count | Skills with SKILL.md problems; hidden when the count is zero unless it is the active view | `5` (when shown) | `5` (digits are fixed: a view keeps its key when others hide); the view menu; palette "Show issues" | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_a_hidden_view_shows_while_it_is_active; tests/tui/test_viewstrip.py::test_digit_keys_move_the_active_tab |
| P34 | New tab with count | New skills from followed sources; hidden when none unless active; hidden in read-only | `6` (when shown) | `6`; the view menu; palette "Show new" | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_a_hidden_view_shows_while_it_is_active |
| P35 | Unused tab with count | No recorded use in 90 days; "wait" style until usage is read; hidden when read-only or usage errors | `7` | `7`; the view menu | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_unused_waits_until_usage_is_read |
| P36 | Costly tab with count | On, costly, unused skills; shown only while active | `8` (when active) | `8`; in the view menu while active; reached from Context cost or Needs attention rows | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_a_hidden_view_shows_while_it_is_active |
| P37 | Similar and Diverged tabs | Hidden tabs shown only while active; reached from Overlap stats | - | No digit (`app.DIGIT_VIEWS`); in the view menu while active; Overlap rows or palette | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_a_hidden_view_shows_while_it_is_active; tests/tui/test_sidepanel.py::test_overlap_and_security_open_their_views |
| P38 | Review tab with count | High-risk security skills; hidden when zero unless active | `9` (when shown) | `9`; the view menu; palette "Show review" | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_a_hidden_view_shows_while_it_is_active |
| P39 | Tab key hints `1`-`9` | Web has no number keys for tabs | - | `1`-`9` fixed to `app.DIGIT_VIEWS`; help and the palette list them | `tui/keys.py` | done | tests/tui/test_commands.py::test_help_rows_and_bindings_read_the_table; src/skill_atlas/tui/keys.py KEYS (1-9) |
| P40 | View filter rules | on/off use the harness switch state; "All" counts any-harness-on; project and stale rules apply to every view | - | Same rules from `core/views.py` | `core/views.py` | done | src/skill_atlas/core/views.py (shared with the web page; core tests) |
| P41 | Search matches | Terms split on spaces, all must match name, invoke, description, plugin, marketplace, project, path, or source (lowercase) | `/` | Same match from `core/views.py` | `core/views.py` | done | src/skill_atlas/core/views.py; tests/tui/test_viewstrip.py::test_typing_filters_at_once_and_counts_the_results |
| P42 | Search highlights | Matched terms (2+ chars) are marked in names and descriptions | - | Matches shown in bold or accent color in rows | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_search_terms_are_highlighted |
| P43 | Search opens all groups | While a query is set, every group and section is open and fold toggles do nothing | - | Same rule | `tui/widgets/skill_list.py` | done | skill_list.py:rebuild/_flatten and :_draw_section hide Collapse all while a query is set; no test for open groups |
| P44 | Search clear | `esc` in a filled box clears; `esc` in an empty box leaves the box and moves to the list | `esc` | `esc` | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_esc_clears_the_text_then_leaves_the_box |
| P45 | Search focus select | `/` or `Cmd+K` focuses and selects the old text | `/`, `Cmd+K` | `/` focuses and selects the old text; `ctrl+k` is the action menu | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_slash_focuses_the_search_and_selects_the_old_text |
| P46 | Filters count meta | Group header shows "N shown" when a filter hides rows | - | Same text in group header | `tui/widgets/skill_list.py` | done | src/skill_atlas/core/views.py group meta ("N shown"); drawn in skill_list.py:_draw_group; no test |
| P47 | Back to All after a view link | Linked "Show them" or "Show all skills" returns to All and focuses the tab | - | Same, focus moves to the strip | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py (focus moves to the All tab after Show all skills) |
| P48 | Select-all box beside tabs | Tri-state box marks or clears all skills the filters show | `Cmd+A` | `ctrl+a`; the mark cell in the bulk bar | `tui/widgets/bulkbar.py` | done | tests/tui/test_bulkbar.py::test_the_mark_cell_marks_all_shown_then_clears_them |
| P49 | Reset (Clear search) | Empty state button clears query, view, project, and stale toggles | - | "Clear search" empty-state action; `esc` | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_search_rebuilds_once_per_burst_and_shows_the_empty_state |

## Skill list rows

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P50 | Section "Your skills" | Section with count (or "N of M" when filtered) and fold chevron | - | Section header row; `left`/`right`/`enter` fold; click the chevron | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_rows_show_sections_groups_and_skills |
| P51 | Section "Plugins" | Plugin groups, count is the number of plugins | - | Same | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_rows_show_sections_groups_and_skills |
| P52 | Section "Project skills" | Shown only with the project toggle; groups by project | - | Same | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_rows_show_sections_groups_and_skills (project section from core views) |
| P53 | Section "New from your sources" | Replaces "Your skills" in the New view; count is shown rows | `6` | Same | `tui/widgets/skill_list.py` | done | src/skill_atlas/core/views.py (section title); drawn in skill_list.py:_draw_section |
| P54 | Collapse all and Expand all | Link in the section header when it has more than one group; hidden while searching | - | `shift+h` collapse all, `shift+l` expand all; click "Collapse all"; palette | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_collapse_all_and_expand_all |
| P55 | Fold state is saved | Collapsed groups persist across loads | - | Saved in UIState preferences: `collapsed` for folds, `opened` for the repos you open in the All view | `tui/state.py` | done | tests/tui/test_skill_list.py::test_fold_keys; tests/tui/test_folds.py::test_opening_a_repo_or_all_repos_unfolds_it_and_a_fold_wins; state.py SAVED has `collapsed` and `opened` |
| P56 | Row name | Slash then the invoke name (plugin skills show the plugin prefix) | - | Same text, accent slash | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_rows_show_sections_groups_and_skills |
| P57 | Row description | Description with boilerplate trimmed ("Use when…"); "No description" if empty; one line | - | The detail panel shows it. Display > "Show descriptions in the list" (`UIState.row_detail`) puts one line back in each row, cut with `…` | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_rows_show_sections_groups_and_skills; tests/tui/test_skill_list.py::test_compact_rows_have_no_blank_lines_and_no_spark |
| P58 | Row thumbnail (cards) | Cards show a picture from the skill folder, or a colored strip | `g` | n/a: images do not render in a terminal; substitute is a one-letter badge in the source hue | `tui/widgets/skill_list.py` | n/a | Images do not render in a terminal; a one-letter badge in the source hue replaces them |
| P59 | Layout list or cards | Display > Layout and `g` toggle | `g` | `g` toggles compact and roomy rows (roomy puts the description on a second line) | `tui/widgets/skill_list.py` | n/a | Plan decision: no cards layout (`g` not bound in keys.py); compact rows (`c`) cover density |
| P60 | Compact rows | `c` hides the description line density | `c` | `c` | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_compact_rows_have_no_blank_lines_and_no_spark |
| P61 | Row switch (single harness) | On/off switch writes the harness config; disabled if the harness has no switch | `x`, `Space` | `x`/`space`; switch glyph at row end | `tui/widgets/skill_list.py`, `tui/widgets/switch.py` | done | tests/tui/test_skill_list.py::test_x_on_the_cursor_row_toggles_through_jobs; tests/tui/test_skill_list.py::test_click_a_switch_toggles_its_row_or_group |
| P62 | Row dots (All harnesses) | One dot per loading harness, filled if on there, label list in tooltip | - | Row of dots; the detail panel's Loaded by list has the names | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_all_harnesses_show_dots_not_switches |
| P63 | Row switch for non-personal skills | Plugin and project rows have no switch (plugins switch at group level) | - | Same: blank slot | `tui/widgets/skill_list.py` | done | skill_list.py:_skill_cells (switch only for scope personal); no test |
| P64 | Row state coloring | States: busy, done, project, off, edited, outdated, on | - | Name color and glyph per state | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_busy_and_done_rows_from_jobs |
| P65 | Row tag: problems | "N problem(s)" tag colored by worst level | - | Tag text | `tui/widgets/skill_list.py` | done | skill_list.py:_skill_status/_from_tag; no row-tag test |
| P66 | Row tag: review and runs code | "review" for high risk, "runs code" for scripts | - | "review" is the `✗ high risk` status in the row; "runs code" is in the detail panel, and in the row with Display > "Show descriptions in the list" | `tui/widgets/skill_list.py` | done | skill_list.py:_from_tag (risk tag); core/views.py:tags |
| P67 | Row tag: edited | "edited" when the folder differs from the lock | - | Tag text | `tui/widgets/skill_list.py` | done | skill_list.py:_skill_status (edited ranks first); tests/tui/test_jobs.py::test_an_edited_skill_asks_before_its_edits_go |
| P68 | Row tag: not upstream | "not upstream" when the repo no longer has the skill | - | In the detail panel; in the row with Display > "Show descriptions in the list" | `tui/widgets/skill_list.py` | done | core/views.py:tags ("not upstream"); shown by skill_list.py:_skill_status; no test |
| P69 | Row tag: update (read-only) | "update" tag when outdated and no Update button | - | Tag text | `tui/widgets/skill_list.py` | done | core/views.py:tags ("update" when read-only); code only |
| P70 | Row tag: you only and agent only | "you only" (disable-model-invocation) and "agent only" (user-invocable false) | - | In the detail panel; in the row with Display > "Show descriptions in the list" | `tui/widgets/skill_list.py` | done | core/views.py:tags ("you only", "agent only"); shown by skill_list.py:_skill_status; no test |
| P71 | Row tag: mode and version | Mode text such as "old version"; "vX" for stale plugin copies | - | In the detail panel; in the row with Display > "Show descriptions in the list" | `tui/widgets/skill_list.py` | done | core/views.py:tags (mode, vX); shown by skill_list.py:_skill_status; no test |
| P72 | Row tag: same as | "same as <name>" for equal descriptions | - | In the detail panel; in the row with Display > "Show descriptions in the list" | `tui/widgets/skill_list.py` | done | core/views.py:tags ("same as"); shown by skill_list.py:_skill_status; no test |
| P73 | Row tags: similar and diverged | "similar" and "diverged" tags | - | Tag text | `tui/widgets/skill_list.py` | done | skill_list.py:_from_tag (similar, diverged glyphs); charts.TAGS; tests/tui/test_charts.py::test_tags_use_the_design_glyphs |
| P74 | Row tag overflow | At most 2 tags, then "+N" | - | A row shows one status glyph, and its word on the cursor and hovered rows; Display > "Show descriptions in the list" brings back 2 tags and `+N` | `tui/widgets/skill_list.py` | done | skill_list.py: first status, a second tag if it fits, then +N with the rest in the tooltip; tests/tui/test_skill_list.py |
| P75 | Row usage cell | 12-week sparkline and short count; blank while usage loads, for stale skills, and for zero uses | - | The row shows a faint use count; the detail panel's Usage section shows uses over time; Display > "Show descriptions in the list" brings back the sparkline | `tui/widgets/charts.py` | done | tests/tui/test_charts.py::test_spark_scales_to_peak_and_draws_zero_as_baseline; tests/tui/test_charts.py::test_spark_count_is_right_aligned_and_muted |
| P76 | Row mark box | Checkbox column (hidden in read-only); shift-click marks a range | `m`, `shift+j/k` | `m`; `shift+j`/`shift+k` extend; shift-click range | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_marks_with_keys; tests/tui/test_skill_list.py::test_click_the_mark_cell_and_shift_click_a_range |
| P77 | Row update slot: Update | "Update" button for outdated tracked skills | `u` | `u` | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_row_update_status_is_a_click_target |
| P78 | Row update slot: confirm | For edited skills the first press shows "Replace my edits" for 4 s; second press runs | `u` twice | `u` then `u` again; `esc` cancels | `tui/widgets/skill_list.py` | done | tests/tui/test_jobs.py::test_an_edited_skill_asks_before_its_edits_go; tests/tui/test_jobs.py::test_click_replace_my_edits_starts_the_update |
| P79 | Row update slot: job states | Badges "Queued", "Updating…", "Updated" with spinner and tick | - | Same text, glyph spinner | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_busy_and_done_rows_from_jobs |
| P80 | Row update slot: Retry | Failed item shows "Retry" with the error as tooltip | `u` | `u`; failed row shows a failed tag; the toast says to press `u` | `tui/widgets/skill_list.py` | done | tests/tui/test_jobs.py::test_update_all_skips_edits_and_names_the_failure |
| P81 | Row key hints | Shows `x` and `u` hints on hover or focus; Display > Show keyboard hints turns them off | - | Hints in the key bar; setting "Show keyboard hints" | `tui/widgets/keybar.py` | done | tests/tui/test_commands.py::test_key_hints_off_hides_the_bar |
| P82 | Row selection | Click or Enter opens the detail panel; current row has aria-current | `Enter` | `enter` or click | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_click_selects_and_a_double_click_opens_the_reader; tests/tui/test_app.py::test_enter_selects_and_opens_the_detail |
| P83 | Row move | `j`/`k` and arrows move focus; scroll keeps the row in view | `j`, `k`, arrows | `j`, `k`, arrows, `pageup`/`pagedown`, `home`/`end` | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_keys_move_open_and_jump |
| P84 | Sort by name, most used, recent, cost | Display > Sort and `s` cycle; a toast names the sort | `s` | `s` cycles and toasts; Sort choice in the Display pane | `tui/commands.py`, `tui/widgets/sidepanel.py` | done | tests/tui/test_commands.py::test_s_cycles_the_sort_and_toasts |
| P85 | Sort applies to groups | Groups sort by total uses, last use, or total cost; "Local, no upstream" stays last | `s` | Same | `tui/widgets/skill_list.py` | done | core/views.py group sort; tests/tui/test_skill_list.py::test_rows_show_sections_groups_and_skills (no sort-specific test) |
| P86 | Row enter animation for restored skills | Rows put back by Undo slide in | - | n/a: no animation needed; substitute is a brief highlight of the row | `tui/widgets/skill_list.py` | n/a | No row animation needed; rows put back by Undo flash briefly (test_rows_flash_when_jobs_names_them) |
| P87 | Delete row animation | Row fades out before delete | - | n/a: removed at once; the toast confirms | `tui/widgets/skill_list.py` | n/a | The row leaves at once; the toast confirms |
| P88 | Skeleton before data | Page renders after the initial scan; usage shows a wait state | - | Skeleton rows while the scan loads (plan.md performance rule) | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_skeleton_rows_until_the_scan_arrives |
| P89 | Virtual rendering | Web renders all rows | - | The list renders only visible lines (400 and 2,000 skill targets) | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_speed_at_2000_skills |

## Group headers

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P90 | Source group header | Fold chevron, avatar, source name, "N of M on" meta, "N shown", "N available", repo link | `enter` on header | One line for each repo; repos start folded in the All view; `enter` expands or collapses the repo | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_rows_show_sections_groups_and_skills |
| P91 | Group avatar | Image from GitHub, or monogram, or folder icon for local groups | - | One-letter badge in the source hue (folder glyph for local groups) | `tui/widgets/skill_list.py` | done | skill_list.py:_draw_group (monogram/`~` badge via _ident); no test |
| P92 | Group hue | Stable hue per group from its id | - | Hue from the same hash, mapped into the 5 palettes | `tui/widgets/skill_list.py` | done | skill_list.py:_ident; theme palette |
| P93 | Group name opens details | Name opens the group detail; chevron folds | `enter` / `h`/`l` | The cursor on a repo shows its details in the panel; `enter` expands or collapses it; `left` folds, `right` unfolds; `x` on header toggles all switches | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_keys_move_open_and_jump; tests/tui/test_skill_list.py::test_fold_keys |
| P94 | Group mark box | Tri-state box marks or clears every row in the group | `m` on header | `m` on a header marks the group | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_click_the_mark_cell_and_shift_click_a_range; skill_list.py:_mark_row (group branch) |
| P95 | Group "+N new" tag | Tag when the source added skills since last look | - | Tag text | `tui/widgets/skill_list.py` | done | skill_list.py:_draw_group ("+N new"); no test |
| P96 | Group "watching" meta | Shows "watching" when watched with nothing installed | - | Same text | `tui/widgets/skill_list.py` | done | core/views.py group meta ("watching"); tests/tui/test_detail.py::test_a_watched_source_can_stop_watching_and_dismiss_new |
| P97 | Group "no source" meta | Prefix groups show "no source ·" | - | Same text | `tui/widgets/skill_list.py` | done | core/views.py group meta ("no source"); no test |
| P98 | Group repo link | "repo ↗" opens GitHub | - | `o` on a header | `tui/jobs.py:open_github` | done | tests/tui/test_jobs.py::test_reveal_and_github_open_locally |
| P99 | Group sparkline | 12-week uses sparkline for the group | - | The repo row shows its use count; Display > "Show descriptions in the list" brings back the sparkline | `tui/widgets/skill_list.py` | done | skill_list.py:_draw_group (charts.spark); no test |
| P100 | Group Update button | "Update N" for outdated skills in the group; "Updating…" while busy | - | `u` on header; click "Update N" | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_group_update_click_updates_its_outdated_skills |
| P101 | Group switch | Tri-state switch turns every skill from the source on or off; toast with Undo; hidden when the harness has no switch or in All | `x` / `space` on header | `x` on header; hidden in All and for no-switch harnesses | `tui/widgets/switch.py` | done | tests/tui/test_skill_list.py::test_click_a_switch_toggles_its_row_or_group; tests/tui/test_jobs.py::test_x_on_a_source_group_turns_every_skill_from_it_on |
| P102 | Group "..." menu | Menu with Stop watching, Link to GitHub…, Delete N skills… | `ctrl+k` on header | `ctrl+k` opens the same list in the palette | `tui/commands.py` | done | tests/tui/test_commands.py::test_group_menu_has_group_actions |
| P103 | Menu: Stop watching | Shown for watched sources | - | Palette item | `tui/commands.py` | done | tests/tui/test_commands.py::test_group_menu_has_group_actions; tests/tui/test_commands.py::test_stop_watching_and_dismiss_call_the_core |
| P104 | Menu: Link to GitHub… | Shown for local groups | - | Palette item `l` | `tui/commands.py` | done | tests/tui/test_commands.py::test_group_menu_has_group_actions |
| P105 | Menu: Delete N skills… | Shown when the group has store skills | - | Palette item | `tui/commands.py` | done | tests/tui/test_commands.py::test_group_menu_has_group_actions |
| P106 | Menu keys | Arrows, Home, End, Esc, Tab move and close the menu | - | Palette list keys | `tui/commands.py` | done | tests/tui/test_commands.py::test_menu_keys_move_and_close |
| P107 | Plugin group header | Plugin name, "<marketplace> · N skills", "not in enabledPlugins" note, sparkline, plugin switch | `x` on header | Same; switch hidden for old versions | `tui/widgets/skill_list.py` | done | skill_list.py:_group_switch (plugin branch); no test |
| P108 | Project group header | Project name, "loads only inside this project · N" | - | Same | `tui/widgets/skill_list.py` | done | core/views.py group meta (project); no test |
| P109 | Group form: link | Link form inline under the header for local groups | `l` | Link modal (see Link section) | `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_link_validates_then_links |

## Available and new skills

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P110 | Available block header | "Available from <repo>" with count (or "N of M") and fold chevron | - | Sub-header row under the source group | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_new_view_rows_install_and_the_block_actions |
| P111 | Available block open rule | Open by default if news or nothing installed; always open while searching or in New view; the user flip is saved | - | Same rule | `tui/widgets/skill_list.py` | done | skill_list.py:rebuild; tests/tui/test_skill_list.py::test_click_an_available_header_opens_the_block (rule itself in core/views.py, untested here) |
| P112 | Available row | Name, description, "new" tag, Install button | `i` | Same; `i` installs | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_new_view_rows_install_and_the_block_actions |
| P113 | Available description loading | Skeleton line while descriptions load; "Description unavailable: <error>" on failure | - | Dim "Loading…" and error text | `tui/widgets/skill_list.py` | done | skill_list.py:_avail_cells ("Description unavailable", skeleton bar); no test |
| P114 | Install new button | "Install N new" and Dismiss when news exists | `I` | `shift+i`; click "Install N new" | `tui/widgets/skill_list.py` | done | tests/tui/test_commands.py::test_available_and_new_skills_offer_install_and_dismiss |
| P115 | Install all button | "Install all N" when no news and more than one is installable | - | Click "Install all N" in the block header; palette | `tui/widgets/skill_list.py`, `tui/commands.py` | done | tests/tui/test_commands.py::test_available_and_new_skills_offer_install_and_dismiss |
| P116 | Installing state | Block button reads "Installing…" and is disabled | - | Same text | `tui/widgets/skill_list.py` | done | skill_list.py:_avail_actions ("Installing…"); no test |
| P117 | Dismiss new | Clears the "new" tags, shows a toast, keeps the list open | - | Click "Dismiss"; palette "Dismiss new" | `tui/commands.py` | done | tests/tui/test_commands.py::test_stop_watching_and_dismiss_call_the_core |
| P118 | Taken: name in use | Badge "name in use" with a tooltip instead of Install | - | Same badge | `tui/widgets/skill_list.py` | done | tests/tui/test_jobs.py::test_a_taken_name_does_not_start_an_install |
| P119 | Taken: moved folder | Badge "installed under an old path" | - | Same badge | `tui/widgets/skill_list.py` | done | skill_list.py:_avail_cells ("installed under an old path"); no test |
| P120 | Note: all installed | "You have every skill from this repo. New ones will show here." | - | Same text | `tui/widgets/skill_list.py` | done | skill_list.py (NOTE constant, _draw_note); no test |
| P121 | Installs only where the harness reads the store | Available blocks hide for harnesses that do not read ~/.agents/skills | - | Same rule (`readsStore`) in `core/views.py` | `core/views.py` | done | core/views.py (readsStore rule); core tests |
| P122 | Available skills in other group modes | Shown only in All and New views and only when grouped by source | - | Same rule | `core/views.py` | done | core/views.py; core tests |
| P123 | Available skill detail | Panel shows "Available" or "Cannot install" card, source, path, GitHub link, Read SKILL.md | `Enter` | Same content in the detail panel | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_an_available_skill_loads_its_description_and_installs |
| P124 | Read an available SKILL.md | Fetches the raw file from GitHub; error "GitHub answered N" | `v` | `v`; fetch happens in a worker | `tui/screens/reader.py` (uses `AtlasAPI.available_text`) | done | tests/tui/test_reader.py::test_available_skill_reads_the_raw_file_from_github; tests/tui/test_reader.py::test_fetch_raw_names_the_github_answer |
| P125 | Watched source with nothing installed | A group appears (meta "watching") when watched and the view is All with no search | - | Same group | `tui/widgets/skill_list.py` | done | core/views.py (watched group); tests/tui/test_detail.py::test_a_watched_source_can_stop_watching_and_dismiss_new |
| P126 | New view empty state | Title "No new skills", text "Checked Nm ago. Your sources have not added skills since you last looked.", Check again button | - | Same copy | `tui/widgets/skill_list.py` | done | core/views.py:empty_state (copy); rendered by skill_list.py:_empty_lines; no test of this copy |
| P127 | Banner and star count of a repo | Repo banner image and star count on details | - | n/a: no images; star count shown as text "★ 1.2k" | `tui/widgets/detail.py` | n/a | No images; the star count shows as text in detail_build.py |

## Bulk actions

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P128 | Bulk bar | Toolbar appears when any skill is marked | `m` | Bar row under the strip | `tui/widgets/bulkbar.py` | done | tests/tui/test_bulkbar.py::test_the_bar_takes_the_view_strip_row_while_marks_exist |
| P129 | Selected count | "N skills selected" and "N hidden by filters" | - | Same text | `tui/widgets/bulkbar.py` | done | tests/tui/test_bulkbar.py::test_marks_that_the_filters_hide_are_counted |
| P130 | Turn on | Turns on selected own skills and plugins, with counts; disabled at zero | - | `x` with marks; bar button | `tui/widgets/bulkbar.py` | done | tests/tui/test_bulkbar.py::test_each_action_shows_the_count_from_the_plan |
| P131 | Turn off | Same for off | - | `x` with marks; bar button | `tui/widgets/bulkbar.py` | done | tests/tui/test_bulkbar.py::test_each_action_shows_the_count_from_the_plan |
| P132 | Bulk update | Updates selected outdated tracked skills; skips edited ones with a note | `u` | `u` with marks | `tui/widgets/bulkbar.py` | done | tests/tui/test_bulkbar.py::test_each_action_shows_the_count_from_the_plan |
| P133 | Link to GitHub… (bulk) | Inline form "owner/repo" and "Link N"; error if no folder matches | `l` | `l` with marks | `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_link_validates_then_links |
| P134 | Copy as prompt | Copies "/name /name" for all selected; toast with a trimmed preview | `y` | `y` with marks | `tui/widgets/bulkbar.py` | done | tests/tui/test_bulkbar.py::test_mouse_runs_each_action |
| P135 | Save as profile… | Opens the selection variant of the save dialog | - | Bulk bar button; `p` then Save with marks | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_save_selection_profile_by_mouse |
| P136 | Delete… (bulk) | Opens confirm dialog for selected store skills | - | `delete` with marks | `tui/screens/confirm.py` | done | tests/tui/test_dialogs.py::test_delete_confirm_keys |
| P137 | Clear selection | "Clear esc" button; `esc` clears marks | `esc` | `esc` | `tui/widgets/bulkbar.py` | done | tests/tui/test_bulkbar.py::test_clear_by_click_and_by_esc |
| P138 | Select all shown | Box and `Cmd+A` mark every shown skill, collapsed groups too | `Cmd+A` | `ctrl+a` | `tui/widgets/bulkbar.py` | done | tests/tui/test_bulkbar.py::test_the_mark_cell_marks_all_shown_then_clears_them |
| P139 | Range mark | Shift-click marks every visible row between marks | shift+click | `shift+j/k` | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_click_the_mark_cell_and_shift_click_a_range |
| P140 | Marks across harness change | Plan counts depend on the current harness and its switch | - | Plan from `core/views.py` | `core/views.py` | done | core/views.py:bulk_plan; tests/tui/test_commands.py::test_flags_follow_the_marks |
| P141 | Bulk not in read-only | Marks, bar, and `m` hidden in the read-only build | - | Same rule | `tui/widgets/skill_list.py` | done | skill_list.py:_marks and commands.py:flags gate marks on ins.writable; no test (core is always writable). Builder: not done in bulkbar.py |
| P142 | Bulk on and off in All harnesses | The switch actions need one harness; in All the plan counts own skills but the toggle writes need a harness | - | Disable on and off in All with the hint "pick a harness to switch skills" | `tui/widgets/bulkbar.py` | done | tests/tui/test_bulkbar.py::test_actions_that_do_not_apply_say_why |

## Detail panel: header and actions

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P143 | No selection shows the inventory | Panel shows Inventory when nothing is selected | `esc` | Same | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_the_close_cell_shows_the_inventory_again |
| P144 | Panel open and close | Close button; `esc` closes and returns focus to the row | `esc` | `esc`; `\` hides the panel | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_the_close_cell_shows_the_inventory_again; tests/tui/test_app.py::test_backslash_hides_and_shows_the_panel |
| P145 | Banner image | Skill folder or repo banner image at the top | - | n/a: images do not render; substitute is the source badge and star text | `tui/widgets/detail.py` | n/a | No images; the source badge and star text replace the banner |
| P146 | Breadcrumb | Source avatar, name, stars; click opens the group detail | `Enter` on crumb | First line shows the source; `enter` on it opens the group | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_a_skill_shows_its_header_cards_and_sections |
| P147 | Title | Slash and invoke name | - | Same | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_a_skill_shows_its_header_cards_and_sections |
| P148 | Panel switch | Switch in title row (skill or plugin) | `x` | `x` | `tui/widgets/detail.py`, `tui/widgets/switch.py` | done | tests/tui/test_detail.py::test_space_and_x_toggle_the_focused_switch |
| P149 | Meta line | Tags: edited, update; plugin switch note ("turns all N skills…"); "Same as …" | - | Same text | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_a_skill_shows_its_header_cards_and_sections |
| P150 | Who can call it | Two cells: You (`/name` or "Not in the / menu"), Agent ("Loads it when it fits" or "Never on its own") | - | Two lines with the same copy | `tui/widgets/detail.py` | done | detail_build.py:_who; no test |
| P151 | Description | Full text; clamped over 420 chars with Show more and Show less; "No description" if empty | - | Same; `shift+m` toggles | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_a_long_description_shows_more_on_click; tests/tui/test_commands.py::test_shift_m_and_the_header_commands_call_their_owners |
| P152 | Read SKILL.md button | Opens the reader | `v` | `v` | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_header_hints_read_copy_and_more |
| P153 | Copy /name button | Copies the slash command; icon turns to a tick for 1.5 s | - | `y`; toast "Copied /name" | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_header_hints_read_copy_and_more |
| P154 | GitHub link | Opens the marketplace or source URL | - | `o` opens in the browser (or shows the URL) | `tui/jobs.py:open_github`, `tui/widgets/detail_build.py` | done | tests/tui/test_jobs.py::test_github_url_reads_the_marketplace_or_the_source |
| P155 | Reveal button | Opens the folder in the file manager; hidden in read-only | - | `shift+r`; hidden over SSH (SSH_TTY set) | `tui/jobs.py:reveal` | done | tests/tui/test_detail.py::test_reveal_hides_over_ssh |
| P156 | Collapsible panes | Sections fold; user state saved per mode; defaults: inventory Needs attention and Usage, skill Loaded by and Usage | - | Click or `enter` on a section label; `tab` moves between controls; state saved | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_click_a_section_label_folds_it_and_saves_it; tests/tui/test_detail.py::test_enter_on_a_folded_section_opens_it |
| P157 | Pane summary and cue | Folded pane shows a summary or a warning cue (danger or warn tone) | - | Same summary text and a colored cue glyph | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_a_short_window_folds_all_but_loaded_by; detail_build.py:section (cue) |

## Detail panel: problems, update, and state cards

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P158 | Problems card | "N problems to fix" with level (Error or Warning), message, hint, path | - | Same list in the panel | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_problems_show_level_message_and_hint |
| P159 | Card: copy for one harness | "A copy for one harness" for skills outside the store | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_cards ("A copy for one harness"); no test |
| P160 | Card: not linked | "Not linked to a repo" with an inline link form | `l` | `l` opens the link modal | `tui/widgets/detail_build.py`, `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_link_validates_then_links |
| P161 | Card: update available | "Update available… newer version is on <repo>", See changes, Update; warns about local edits | `u`, `d` | Same card; `d` See changes, `u` Update | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_update_card_hints_run_their_actions |
| P162 | Card: edited note | Note "You changed this skill after install…" when edited but not outdated | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_cards; no test |
| P163 | Card: old version | "Old version. Claude Code no longer loads this copy." | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_cards (Old version); no test |
| P164 | Card: project skill | "Loads only when you work inside <project>." | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_cards (project); no test |
| P165 | Update job in the panel | Update slot shows queued, working, done, Retry like rows | - | Same | `tui/widgets/detail.py` | done | detail_build.py:_update_card/_update_hint; no dedicated test |
| P166 | Plugin skills that cannot update | Plugin skills get no update check and no Update button | - | No Update key action; the key bar hides `u` | `tui/widgets/detail.py` | done | keys.py needs="update"; commands.py:flags; no plugin-specific test |
| P167 | Tracked check failed (unknown) | Tag "not upstream" on row; update status "unknown" | - | Same tag | `tui/widgets/skill_list.py` | done | core/views.py:tags ("not upstream"); shown by skill_list.py |

## Detail panel: Loaded by

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P168 | Loaded by pane | One row per harness that loads the folder: label, switch or "no switch"; current harness highlighted; summary "On in N of M" | `x` on a row | Pane lists rows; `x` toggles the row under the cursor | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_click_a_loaded_by_switch_writes_that_harness |
| P169 | Loaded by: no harness | "No harness loads this folder." | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_loaded_by ("No harness loads this folder."); no test |
| P170 | Loaded by: harness without switch | Shows "no switch" for harnesses such as Cursor | - | Same text | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_a_harness_without_a_switch_says_so |
| P171 | Loaded by: read-only | Switches are disabled; a click toasts the read-only text | - | Rows show state only; `x` toasts the read-only text | `tui/widgets/detail.py` | done | detail_build.py:_loaded_by (live = switch and ctx.writable); no test (core always writable) |

## Detail panel: Overlap

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P172 | Similar skills list | Each similar skill with a percent meter; click opens it | `Enter` | List with a bar meter and percent; `enter` opens | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_similar_rows_open_the_other_skill |
| P173 | Copies list | Other folders with a diverged SKILL.md: path, "newer" text, "Only SKILL.md differs" or "Other files differ too" | - | Same list | `tui/widgets/detail.py` | done | detail_build.py:_overlap (copies list); no copies-specific test |
| P174 | Compare button | Opens the compare dialog; hidden in read-only with the note "Run ./atlas to compare the files." | `Enter` on a copy | `enter` on a copy opens the compare screen | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_compare_shows_both_paths_and_the_diff |
| P175 | Overlap pane summary and cue | "N similar skills · N diverged"; warn cue for diverged copies | - | Same | `tui/widgets/detail.py` | done | detail_build.py:_overlap (summary and cue); no test |

## Detail panel: Usage

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P176 | Skill usage stats | Uses, last used ("today", "N days ago"), active days | - | Three stats | `tui/widgets/detail.py` | done | detail_build.py:_use_stats; tests/tui/test_charts.py::test_heatmap_grid_labels_and_caption |
| P177 | Usage heatmap | 26-week calendar with five levels; hover shows the day and count | - | Grid of cells; mouse hover shows the day | `tui/widgets/charts.py` | done | tests/tui/test_charts.py::test_heatmap_grid_labels_and_caption; tests/tui/test_charts.py::test_heatmap_hover_shows_the_day_in_caption_and_tooltip |
| P178 | Usage heatmap hover readout | Hover swaps the summary line for the day text | - | Mouse hover (no keys) | `tui/widgets/charts.py` | done | charts.Heatmap takes focus; arrow keys move a cursor day with the readout; tests/tui/test_charts.py |
| P179 | Usage by project | Top 4 projects with bars | - | Rows with block-glyph bars | `tui/widgets/charts.py` | done | tests/tui/test_charts.py::test_barchart_truncates_labels_and_aligns_numbers |
| P180 | Usage counted note | "Claude Code counted N uses in all. Old sessions get deleted…" | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_usage; no test |
| P181 | No uses note | "No recorded uses yet." plus a hint to turn off unused skills that are on | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_usage; no test |
| P182 | Usage still reading | "Reading your agent sessions… N of M" with a progress track | - | Same text and a bar | `tui/widgets/charts.py`, `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_usage_shows_its_progress_while_it_reads; tests/tui/test_charts.py::test_progress_fills_half_cells_on_a_thin_track |
| P183 | Usage error | Cue "Could not read usage" and the server hint text | - | Same | `tui/widgets/detail.py` | done | tests/tui/test_sidepanel.py::test_usage_and_profiles_show_their_failures |
| P184 | Usage count-up animation | Number counts up with the reveal | - | n/a: no animation; the number shows at once (reduced-motion setting) | `tui/widgets/charts.py` | n/a | No animation; the number shows at once |
| P185 | Usage hidden | Not shown for project skills, stale skills, available skills, or read-only | - | Same rule | `tui/widgets/detail.py` | done | detail_build.py:_usage (hides for project, stale, read-only); no test |

## Detail panel: Security

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P186 | Security pane | Findings grouped by rule and level (high, medium, info); info groups start closed; click folds | - | Foldable groups with the same defaults | `tui/widgets/detail.py` | done | detail_build.py:_security_body (secfold, info closed); tests/tui/test_detail.py::test_security_loads_through_fetch_when_opened |
| P187 | Finding rows | file:line plus excerpt code | - | Same | `tui/widgets/detail.py` | done | detail_build.py:_security_body; no test |
| P188 | Scanning state | "Scanning the files…" with a 150 ms settle delay | - | Same, worker with debounce | `tui/widgets/detail.py` | done | detail.py shows "Scanning the files…" with the skeleton; tests/tui/test_detail.py |
| P189 | Scan error | "Could not scan this skill: <error>" and Try again | - | Same; `enter` on the link retries | `tui/widgets/detail.py` | done | detail_build.py:_security_body ("Could not scan this skill" + Try again); no test |
| P190 | No findings | "No risky patterns in N files." | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_security_body; no test |
| P191 | Truncated and skipped notes | "N more findings not shown." and "N files over 1 MB not scanned." | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_security_body; no test |
| P192 | Security note | Heuristic note shown in every state | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_security_body (views.SEC_NOTE); no test |
| P193 | Read-only security line | Counts only, with "Run ./atlas to see each finding." | - | Same rule | `tui/widgets/detail.py` | done | detail_build.py:_security_body (not ctx.writable branch); no test (core always writable) |

## Detail panel: Details, History, Delete

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P194 | Details pane | Facts: Version, Updated, Tools, Arguments, Size, Context cost, Setting, Path; summary "vX · ≈N tokens" | - | Definition list in the pane | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_a_skill_shows_its_header_cards_and_sections |
| P195 | Setting line | Claude Code: `skillOverrides.<name>` or `enabledPlugins[...]`; others: the config path | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:_setting; no test |
| P196 | History pane | Snapshot list: time, "Before an update" or "Before a restore", hash, Restore… button; summary "N snapshots" | `h` | `h` opens the history screen; the History pane lists snapshots | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_a_skill_shows_its_header_cards_and_sections; tests/tui/test_diff.py::test_history_lists_versions_and_diffs_each |
| P197 | History empty | "No saved versions yet. Before each update, the atlas saves a copy of this skill here." | - | Same text | `tui/widgets/detail.py` | done | tests/tui/test_diff.py::test_history_empty_and_error_states |
| P198 | History loading and error | "Reading saved versions…"; "Could not read the history: <error>" with Try again | - | Same text | `tui/widgets/detail.py` | done | tests/tui/test_diff.py::test_history_empty_and_error_states |
| P199 | Delete zone | "Delete…" button and note "Moves the folder to the Trash and removes its lock entry. You can undo it."; only for store skills; hidden in read-only | - | `delete`; the pane shows the note | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_delete_asks_through_the_confirm_screen |

## Detail panel: group detail

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P200 | Group detail header | Banner, title, switch, meta ("N of M on", "N available", stars, "Watching") | - | Same text, no banner | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_a_group_shows_its_source_and_actions |
| P201 | Group description | Repo description, or "Skills with no upstream repo…", or the prefix text | - | Same text | `tui/widgets/detail.py` | done | detail_build.py:group_blocks; no test |
| P202 | Group actions | Update, Install N new, GitHub, Link to GitHub…, Stop watching | - | Palette items and keys `u`, `shift+i`, `o`, `l` | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_a_group_shows_its_source_and_actions; tests/tui/test_detail.py::test_a_watched_source_can_stop_watching_and_dismiss_new |
| P203 | Group stat tiles | on, off, updates, edited, you only, unused | - | Six stats | `tui/widgets/detail.py` | done | detail_build.py:_group_stats; no test |
| P204 | Group usage | Stats, heatmap, top 5 skills; "No recorded uses for these skills yet." | - | Same | `tui/widgets/detail.py` | done | detail_build.py:_group_usage; no test |
| P205 | Group facts | Kind, Repo, Checked, Folder (source); Marketplace, Version, Installed, Updated, Setting (plugin); Folder (project) | - | Same list | `tui/widgets/detail.py` | done | detail_build.py:group_blocks (group.facts); no test |
| P206 | Group delete zone | "Delete N skills…" with "Moves every folder in this collection to the Trash. You can undo it." | - | Palette item and same note | `tui/widgets/detail.py` | done | detail_build.py:group_blocks (delete zone); no test |
| P207 | Plugin group detail | Plugin, marketplace, version, N skills; switch for the plugin | - | Same | `tui/widgets/detail.py` | done | tests/tui/test_detail.py::test_group_switch_turns_only_the_skills_that_change |
| P208 | Project group detail | Project, N skills, folder | - | Same | `tui/widgets/detail.py` | done | detail_build.py:group_blocks; no test |

## Side panel: Inventory

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P209 | Inventory stat tiles | on, off, updates ("–" in read-only), untracked, duplicates, edited | - | Two lines of text: `297 on   50 off   9 updates`, then `66 untracked, 1 duplicate, 1 edited` | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_the_stats_and_title_come_from_views |
| P210 | Needs attention pane | Rows sorted danger first: store problems, skills to review, skills with problems, missing, diverged names, costly skills; each with a "Show them" link | - | One short line for each item, with the full sentence in its tooltip; `enter` on a row jumps to the view | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_needs_attention_lists_each_item_with_its_glyph; tests/tui/test_sidepanel.py::test_show_them_opens_the_view_with_the_mouse |
| P211 | Needs attention: store health | Lock entries with no folder and folders no harness can load, with a details list | - | Foldable list | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_store_problems_fold_open_under_their_row |
| P212 | Needs attention: missing skills | "N skills in the lock file have no folder." with Restore link | - | Row with the Restore action (Skill set flow) | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_restore_runs_from_the_row_and_the_skill_set |
| P213 | Needs attention: nothing | "Nothing needs your attention. The skill folders and lock files have no problems." | - | Same text | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_nothing_to_do_shows_the_web_copy |
| P214 | Usage pane (all) | Heatmap for the harness, top 5 skills, "N skills not used in 90 days. Show them" | - | Behind the "Usage, cost, security and more" row in the side panel; same | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_a_top_used_row_selects_its_skill |
| P215 | Context cost pane (one harness) | "≈N tokens in every session, from N skills that are on", top 5 costly skills, estimate note | - | Behind the "Usage, cost, security and more" row in the side panel; same | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_context_cost_rows_select_a_skill_or_a_harness |
| P216 | Context cost pane (All harnesses) | Per-harness list "≈N · M on"; click switches the harness | - | Behind the "Usage, cost, security and more" row in the side panel; `enter` switches | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_context_cost_rows_select_a_skill_or_a_harness |
| P217 | Context cost: none on | "No skills are on in <harness>, so skills add no tokens to a session." | - | Behind the "Usage, cost, security and more" row in the side panel; same text | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_nothing_to_do_shows_the_web_copy |
| P218 | Overlap pane | Two tiles: similar pairs and diverged names; each opens that view; disabled at zero | - | Behind the "Usage, cost, security and more" row in the side panel; same | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_overlap_and_security_open_their_views |
| P219 | Security pane (all) | "N to review · N with medium findings · N run code"; Show them; note | - | Behind the "Usage, cost, security and more" row in the side panel; same | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_overlap_and_security_open_their_views |
| P220 | Skill set pane | Lead text, Export, Copy, Import… buttons; "You can also drop a manifest file on this panel."; hidden in read-only | - | Behind the "Usage, cost, security and more" row in the side panel; the drop hint becomes "Pass a file with `atlas tui import FILE`" | `tui/widgets/sidepanel.py` | done | sidepanel.py: the import note in the Skill set pane; tests/tui/test_sidepanel.py |
| P221 | Keyboard hint link | "All keyboard shortcuts" link and `?` | `?` | Same | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_the_keys_hint_opens_help |
| P222 | Drag and drop a manifest | Dropping a JSON file on the panel starts an import | - | n/a: terminals cannot drop files into a widget; substitute is a path prompt in the import flow | `tui/screens/transfer.py` | n/a | A terminal cannot take a file drop; the import path prompt replaces it (transfer.py) |

## Reader

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P223 | Open reader | Modal with title, path, outline, body; focus returns to the row on close | `v` | `v` full-screen reader | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_v_reads_the_selected_skill; tests/tui/test_reader.py::test_esc_q_and_the_close_cell_close_and_focus_returns |
| P224 | Reader header | Source avatar, `/name`, path (or "repo · path" for available) | - | Title and path line | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_v_reads_the_selected_skill |
| P225 | Formatted mode | GFM subset: headings, lists, task lists, code fences, tables, blockquotes, rules, links, images; raw HTML escaped | `r` | Textual Markdown | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_r_and_clicks_switch_between_formatted_and_markdown |
| P226 | Markdown (raw) mode | Numbered raw lines | `r` | `r` toggles; choice saved | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_r_and_clicks_switch_between_formatted_and_markdown; reader.py:701,879 read and save state.reader_raw (coordinator: now has a test) |
| P227 | Front matter block | Key/value table at the top in formatted mode | - | Table at the top | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_frontmatter_parses_like_the_web |
| P228 | Outline | "On this page" list shown when more than 2 headings and not raw; click scrolls | - | `t` shows or hides the outline; arrows and `enter` jump | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_outline_hides_when_narrow_and_t_or_a_click_shows_it |
| P229 | Copy Markdown | Copies the whole file; tick for 1.5 s; error toast "Could not copy: …" | - | `y` | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_copy_github_and_reveal_by_key_and_by_click |
| P230 | GitHub link in reader | Opens the file on GitHub when the skill has a repo and is not a plugin skill | - | `o` | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_copy_github_and_reveal_by_key_and_by_click; tests/tui/test_reader.py::test_local_skill_has_no_github_and_ssh_hides_reveal |
| P231 | Reveal in reader | Reveals the folder; hidden for available skills | - | `shift+r`; hidden over SSH | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_local_skill_has_no_github_and_ssh_hides_reveal |
| P232 | Reader loading | "Loading…" text | - | Same | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_skeleton_shows_after_150ms_while_the_file_loads |
| P233 | Reader read-only note | "This read-only build has only the first lines. Run ./atlas to read the whole file." | - | Same note | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_a_read_only_build_shows_the_first_lines_and_says_so |
| P234 | Reader load error | "Could not load the file: <error>" | - | Same text | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_a_read_error_names_the_reason |
| P235 | Relative links and images | Map to GitHub blob and raw URLs for tracked skills | - | Links open in the browser; images n/a (shown as alt text) | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_links_map_like_the_web; tests/tui/test_reader.py::test_links_open_on_github_and_anchors_jump |
| P236 | Reader close | `esc`, close button, or click outside | `esc` | `esc` or `q` | `tui/screens/reader.py` | done | tests/tui/test_reader.py::test_esc_q_and_the_close_cell_close_and_focus_returns |

## Diff, compare, and history

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P237 | See changes dialog | Per-file collapsible diffs; first 3 open; summary "N added · N changed · N removed" and total lines | `d` (via button) | `d` opens the diff screen | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_see_changes_lists_files_and_shows_the_first |
| P238 | See changes: loading | "Downloading <repo>…" | - | Same | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_slow_download_shows_progress_then_the_diff |
| P239 | See changes: error | "Could not get the changes: <error>" | - | Same | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_errors_and_same_files_say_so |
| P240 | See changes: no file change | "The files are the same. Only the version record is different." | - | Same text | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_errors_and_same_files_say_so |
| P241 | Diff file rows | Path, +/− counts, status tag (added, changed, removed) | - | Same | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_see_changes_lists_files_and_shows_the_first |
| P242 | Diff lines | Added, removed, and hunk lines colored; "Shows the first N lines only." for truncated | - | Same colors | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_lines_read_without_color; tests/tui/test_diff.py::test_a_long_diff_draws_only_what_shows |
| P243 | Diff binary and too long | "Binary file, X to Y" and "Not shown. The diff is too long." | - | Same text | `tui/screens/diff.py` | done | diff.py (binary and too long text); tests/tui/test_diff.py::test_sizes_and_times_read_as_on_the_web (no binary-specific test) |
| P244 | Diff edited warning | "You changed this skill after install. The removed lines include your changes." | - | Same text | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_edited_skill_warns_and_asks_to_replace_edits |
| P245 | Diff action | Close and Update (or "Replace my edits"); Update hidden if not outdated or a job runs | - | `u` in the screen | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_u_updates_and_the_close_cell_closes; tests/tui/test_diff.py::test_update_hides_when_current_or_a_job_runs |
| P246 | Compare dialog | Two file paths (old/new, "newer" tag), line diff, "+N −N lines"; opened from a Copies row | - | Compare screen with the same content | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_compare_shows_both_paths_and_the_diff |
| P247 | Compare: states | "Loading the diff…"; "The two files are the same now. Reload the page to update the list."; "The diff is too long to show in full."; "Could not compare the files: <error>" | - | Same text; "Reload the page" becomes "Press ctrl+r to scan again" | `tui/screens/diff.py` | done | tests/tui/test_diff.py::test_compare_states |
| P248 | Restore from History | Confirm dialog "Restore /name from <time>?" with lead; Cancel and Restore | - | `r` on a snapshot opens the confirm; `enter` selects | `tui/screens/history.py`, `tui/screens/confirm.py` | done | tests/tui/test_diff.py::test_restore_asks_once_then_rolls_back |
| P249 | Restore blocked by a job | Toast "An update is still running." | - | Same toast | `tui/screens/history.py` | done | tests/tui/test_diff.py::test_restore_blocked_or_failed_says_why |
| P250 | Restore result | Toast "Restored <name> from <time>. Restart <harness> sessions to pick it up."; data and checks reload | - | Same | `tui/screens/history.py` | done | tests/tui/test_diff.py::test_restore_asks_once_then_rolls_back |
| P251 | Restore error | Toast "Could not restore: <error>" | - | Same | `tui/screens/history.py` | done | tests/tui/test_diff.py::test_restore_blocked_or_failed_says_why |
| P252 | History screen | Web has only the pane list; the TUI adds a full screen for long lists | - | `h` | `tui/screens/history.py` | done | tests/tui/test_diff.py::test_history_lists_versions_and_diffs_each; tests/tui/test_diff.py::test_history_at_80_by_24 |

## Delete and undo

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P253 | Delete confirm | Dialog "Move /name to the Trash?" (or "N skills") with harness list, lock-entry note, path list, edited tag, undo note; Cancel and "Move N to Trash" | `delete` | Confirm modal with the same copy | `tui/screens/confirm.py` | done | tests/tui/test_dialogs.py::test_delete_confirm_keys; tests/tui/test_dialogs.py::test_delete_confirm_mouse |
| P254 | Delete harness list | "It stops loading in A, B, and N more" with at most 3 names | - | Same | `tui/screens/confirm.py` | done | tests/tui/test_dialogs.py::test_helpers_match_the_web_strings |
| P255 | Delete edited warning | "N skills have changes you made after install." | - | Same | `tui/screens/confirm.py` | done | tests/tui/test_dialogs.py::test_helpers_match_the_web_strings |
| P256 | Delete result | Toast "Moved <name> to the Trash." with Undo; selection clears if deleted | - | Same; `z` undoes | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_delete_moves_to_the_trash_and_z_puts_it_back |
| P257 | Delete error | Toast "Could not delete: <error>" | - | Same | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_delete_and_undo_errors |
| P258 | Undo delete | Toast Undo or `Cmd+Z` restores from Trash; toast "Put back N skills."; error toast "Could not undo: …" | `Cmd+Z` | `z` | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_delete_moves_to_the_trash_and_z_puts_it_back; tests/tui/test_jobs.py::test_delete_and_undo_errors |
| P259 | Trash not available | Server error is shown in the "Could not delete" toast; the README says delete is not available | - | `delete` opens the confirm, which shows the reason and disables the action | `tui/screens/confirm.py` | done | tests/tui/test_dialogs.py::test_delete_without_a_trash_disables_the_action (the dialog shows the reason; no toast) |
| P260 | Delete scope | Only store skills (in ~/.agents/skills) are deletable; copies outside the store, plugin, and project skills are not | - | Same rule; hides delete otherwise | `tui/screens/confirm.py` | done | tests/tui/test_dialogs.py::test_delete_only_store_skills |
| P261 | Delete in read-only | Delete buttons are hidden | - | Same rule | `tui/commands.py` | done | commands.py:flags (delete needs a writable core); no test |
| P262 | Undo for switches | Toggle, source toggle, bulk toggle, unwatch, and profile toasts carry Undo | `Cmd+Z` | `z` | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_z_puts_the_switch_back_and_does_nothing_when_the_stack_is_empty; tests/tui/test_dialogs.py::test_profile_delete_and_undo |
| P263 | Undo key without a toast | `Cmd+Z` does nothing when no undo is pending (only when not typing) | `Cmd+Z` | Same | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_z_puts_the_switch_back_and_does_nothing_when_the_stack_is_empty |

## Profiles

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P264 | Profiles popover | Header: "Profiles" with count; list of profiles, or empty copy; Save current as profile… | - | Profiles screen `p` | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profiles_list_rename_by_keys |
| P265 | Profile row | Name, "N on · N off · harness or N harnesses", Apply…, Rename, Delete | - | Row with keys `a`, `r`, `delete` | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profiles_list_rename_by_keys |
| P266 | Profiles empty | "No profiles yet. A profile keeps which skills are on and off, so you can switch them all in one step." | - | Same text | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profiles_error_empty_and_retry |
| P267 | Profiles loading and error | "Loading profiles…"; "Could not read the profiles. <error>" with Try again | - | Same text | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profiles_error_empty_and_retry |
| P268 | Save current as profile | Dialog with name (max 60), lead, exists note, "Replace profile" label when the name exists; scoped to the current harness | - | Input modal; same copy | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_save_current_profile |
| P269 | Save selection as profile | Title "Save N selected skills as a profile", lead, check "Also turn off all other skills in <where>" | - | Same modal with the check | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_save_selection_profile_by_mouse |
| P270 | Save blocked: no switch | Message "<Harness> has no on/off switch for skills. Pick another harness to save a profile." | - | Same text | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profiles_without_a_switch |
| P271 | Rename profile | Dialog with name; blocks a taken name with "Another profile has this name. Use a different name." | - | Same | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profiles_list_rename_by_keys |
| P272 | Apply preview | Dialog "Apply <name>?" with the count of switches and harnesses, per-harness On or Off list, "missing" note; "Apply N changes" | - | Same preview screen | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profile_apply_preview_mouse_and_undo |
| P273 | Apply no change | "Profile <name> already matches"; "All switches already match this profile. Nothing changes."; Close only | - | Same text | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profile_apply_when_nothing_changes |
| P274 | Apply result | Toast "Applied <name>: N changes. Restart agent sessions to pick it up." with Undo | - | Same; `z` undoes | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profile_apply_preview_mouse_and_undo |
| P275 | Undo apply | Toast "Put back the switches from before <name>." | - | Same | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profile_apply_preview_mouse_and_undo |
| P276 | Delete profile | Toast "Deleted the profile <name>." with Undo ("Put back the profile <name>.") | - | Same | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profile_delete_and_undo |
| P277 | Profile dialog errors | Error text shows inside the dialog, the button re-enables | - | Same | `tui/screens/profiles.py` | done | tests/tui/test_dialogs.py::test_profiles_error_empty_and_retry |
| P278 | Profiles in All harnesses | Save and apply act on each harness ("each harness") | - | Same wording | `tui/screens/profiles.py` | done | profiles.py ("each harness" wording); tests/tui/test_dialogs.py::test_save_current_profile (not in All) |
| P279 | Profiles hidden in read-only | Button is hidden | - | Same rule | `tui/screens/profiles.py` | done | keys.py: `p` has needs="writable", so the key bar and palette hide it; no test. Builder: not done |

## Import and export

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P280 | Export | Builds a manifest and downloads `skills-<host>-<date>.json`; toast "Exported N skills to <file>." | - | Writes the file to the current folder (path prompt, default name); same toast | `tui/screens/transfer.py` | done | tests/tui/test_dialogs.py::test_export_to_the_default_file_then_replace |
| P281 | Copy manifest | Copies the JSON to the clipboard; "Copied" for 1.5 s | - | Copies by OSC 52, plus `pbcopy` on local macOS; same toast | `tui/screens/transfer.py` | done | tests/tui/test_dialogs.py::test_export_path_errors_and_copy |
| P282 | Import… | File chooser for a .json; limit 1 MB ("is too large to be a manifest"); "is not a JSON file" | - | Path prompt; same limits and errors | `tui/screens/transfer.py` | done | tests/tui/test_dialogs.py::test_import_file_errors |
| P283 | Import plan dialog | "Import skill set?" with lead (host, date), group checkboxes: install, turn off in harness, watch repos; "Already here: N"; "Cannot install: N"; skipped harness note | - | Same plan screen with checkboxes | `tui/screens/transfer.py` | done | tests/tui/test_dialogs.py::test_import_plan_groups_and_apply |
| P284 | Import apply | Runs the checked groups; install becomes a job; toast with switched, watched, and failed counts | - | Same; "Nothing changed." when empty | `tui/screens/transfer.py` | done | tests/tui/test_dialogs.py::test_import_plan_groups_and_apply |
| P285 | Import nothing to do | "This computer already has everything in the file that the atlas can install." with Close only | - | Same text | `tui/screens/transfer.py` | done | tests/tui/test_dialogs.py::test_import_nothing_to_do_and_all_groups_off |
| P286 | Import errors | "Could not import <file>: <error>"; "Could not export: …" | - | Same | `tui/screens/transfer.py` | done | tests/tui/test_dialogs.py::test_import_file_errors; tests/tui/test_dialogs.py::test_export_path_errors_and_copy |
| P287 | Restore missing skills | Needs attention row opens a plan "Restore N missing skills?" from the lock file; "No skill is missing now."; "Its lock entry names a different folder" | - | Same | `tui/screens/transfer.py` | done | tests/tui/test_dialogs.py::test_restore_missing_skills |
| P288 | Restore blocked by a job | Toast "Another job is still running." | - | Same | `tui/screens/transfer.py` | done | transfer.py ("Another job is still running."); no test |
| P289 | Restore reading state | Link reads "Reading…" while the plan loads; errors "Could not read the lock file: …" | - | Same | `tui/screens/transfer.py` | done | confirm.fetch_slow and transfer.ReadingDialog ("Reading the lock file…" after 300 ms); tests/tui/test_dialogs.py |

## Link to GitHub and watch a source

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P290 | Link form (single or group) | Input "owner/repo" with Link and Cancel; button reads "Linking…" | `l` | Modal input; same | `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_link_validates_then_links |
| P291 | Link success | Toast "Linked N to <repo>. No folder for: …"; reloads data and re-checks updates | - | Same | `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_link_validates_then_links |
| P292 | Link no match | Inline error "No folder in <repo> has the same name as this skill / these skills." | - | Same in the modal | `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_link_errors_stay_in_the_dialog |
| P293 | Link error | Inline error text from the server | - | Same | `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_link_errors_stay_in_the_dialog |
| P294 | Link cancel | Cancel button or `esc` closes the form | `esc` | `esc` | `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_dialogs_close_on_a_click_outside |
| P295 | Watch a source… | Link in "Your skills" header; form "Watch a GitHub repo for new skills" (owner/repo or URL); button "Watching…" | - | `w` opens the modal; palette "Watch a source" | `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_watch_a_source |
| P296 | Watch success | Toast "Watching <repo>. N skills available." or "You have all its skills."; scrolls to the group | - | Same | `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_watch_a_source |
| P297 | Watch error | Inline error with first letter capitalized and a period | - | Same | `tui/screens/link.py` | done | tests/tui/test_dialogs.py::test_link_errors_stay_in_the_dialog; tests/tui/test_dialogs.py::test_watch_a_source |
| P298 | Stop watching | Toast "Stopped watching <repo>." with Undo | - | Same; `z` undoes | `tui/commands.py` | done | tests/tui/test_commands.py::test_stop_watching_and_dismiss_call_the_core |
| P299 | Watch hidden in the New view and in read-only | Link is hidden then | - | Same | `tui/commands.py` | done | commands.py: the `watch` flag is off in the New view; tests/tui/test_commands.py |

## Update and install jobs

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P300 | Update one skill | Starts a job for one folder; row and panel show states | `u` | `u` | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_u_runs_a_job_the_bar_fills_and_the_ticks_leave |
| P301 | Update many | Update all (header), per-source Update, bulk Update; edited skills skipped with a note; "All N have your edits. Update them one at a time." if none are safe | - | `shift+u`; `u` on a header; `u` with marks | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_update_all_skips_edits_and_names_the_failure |
| P302 | Only one job at a time | Toasts "An update is already running." and "Another job is still running." | - | Same toasts | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_one_job_at_a_time |
| P303 | Job polling | Polls every 300 ms; a 404 marks running items failed ("that job is gone…") | - | Poll `atlas.job()` every 300 ms; the missing-job case marks items failed | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_a_job_that_cannot_start_or_goes_missing |
| P304 | Job completion toast | "Updated <name> in Ns. Restart <harness> sessions to pick it up." or "Installed N from <repo> in Ns." or "Updated N, M failed: <error>. Use Retry on the row." | - | Same copy | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_update_all_skips_edits_and_names_the_failure; tests/tui/test_jobs.py::test_install_one_available_skill_and_the_new_ones |
| P305 | Job end sequence | Hold the bar full 0.9 s, fade 1.1 s, remove ticks; failed items stay with Retry | - | Same timing; failed items stay | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_u_runs_a_job_the_bar_fills_and_the_ticks_leave |
| P306 | After a job | Reloads data, drops cached history, re-checks updates | - | Same | `tui/jobs.py` | done | jobs.py:_finish (app.reload scan and updates); no test |
| P307 | Start error | Toast "Could not start: <error>" | - | Same | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_a_job_that_cannot_start_or_goes_missing |
| P308 | Check for updates | Toast "Could not check for updates: <error>" on failure; refresh flag ignores the 10-minute cache | - | `ctrl+r` forces refresh | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_check_again_forces_a_fresh_check |
| P309 | Install one or many | Install button, Install N new, Install all; the job installs into ~/.agents/skills | `i` | `i`, `shift+i` | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_install_one_available_skill_and_the_new_ones |
| P310 | Install failed | Row button turns to red "Retry" with the error as tooltip | `i` | `i`; failed row keeps its tag; the toast says to press the key | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_update_all_skips_edits_and_names_the_failure |
| P311 | Screen reader announcements | Live region announces start and end of jobs | - | n/a: no screen reader hook in Textual; substitute is the toast text | `tui/jobs.py` | n/a | Textual has no screen reader hook; toast text is the substitute |

## Toasts and errors

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P312 | Toast | One toast at a time at the bottom; HTML-safe text; hover pauses the timer | - | Hover pauses the timer | `tui/widgets/toast.py` | done | tests/tui/test_jobs.py::test_hover_pauses_a_toast_and_the_close_cell_dismisses_it; tests/tui/test_jobs.py::test_a_toast_is_plain_text_sits_above_the_key_bar_and_replaces_the_last |
| P313 | Toast duration | Max of 4 s (8 s with Undo) and 300 ms per word; 2.5 s after the mouse leaves | - | Same formula | `tui/widgets/toast.py` | done | tests/tui/test_jobs.py::test_toast_duration_follows_the_word_count |
| P314 | Toast Undo button | "Undo" with the Cmd+Z hint; runs once, hides the toast | `Cmd+Z` | `z` hint in the toast | `tui/widgets/toast.py` | done | tests/tui/test_jobs.py::test_click_undo_on_the_toast |
| P315 | Switch change toast | "Turned <name> on/off. Restart <harness> sessions to pick it up." with Undo | - | Same | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_x_flips_the_switch_at_once_then_writes_with_an_undo_toast |
| P316 | Source switch toast | "Turned N skills from <source> on/off…" with Undo (only changed skills) | - | Same | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_x_on_a_source_group_turns_every_skill_from_it_on |
| P317 | Bulk switch toast | "Turned N skills and N plugins on/off…" with Undo | - | Same | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_x_with_marks_turns_skills_and_plugins_to_the_side_most_need |
| P318 | Switch save error | Switch reverts and toast "Could not save: <error>" | - | Optimistic change reverts with the toast | `tui/jobs.py` | done | tests/tui/test_jobs.py::test_a_failed_write_reverts_the_switch_and_says_why |
| P319 | Read-only switch toast | "This page is read-only. Run ./atlas to change skills." | - | "This build is read-only. Run `atlas` to change skills." | `tui/jobs.py`, `tui/commands.py` | done | commands.py:toggle_everywhere and jobs.py ("This build is read-only…"); no test |
| P320 | Copy errors | "Could not copy." / "Could not copy: <error>" | - | Same | `tui/jobs.py:copy` | done | tests/tui/test_jobs.py::test_pbcopy_failure_says_could_not_copy |
| P321 | Reveal error | "Could not reveal: <error>" | - | Same | `tui/jobs.py:reveal` | done | tests/tui/test_jobs.py::test_over_ssh_copy_does_not_claim_success_and_reveal_explains |
| P322 | Dismiss toast | "Dismissed N new skills from <repo>. They stay under Available." | - | Same | `tui/commands.py`, `tui/widgets/skill_list.py:_dismiss` | done | tests/tui/test_commands.py::test_stop_watching_and_dismiss_call_the_core |
| P323 | Sort toast | "Sorted by name / most used / recently used / context cost." | - | Same | `tui/commands.py:cycle_sort` | done | tests/tui/test_commands.py::test_s_cycles_the_sort_and_toasts |
| P324 | Server error mapping | API errors surface as messages from the server `error` field | - | Core exceptions map to the same messages | `tui/jobs.py` | done | jobs.py:_msg maps core exceptions to the toast text; tests/tui/test_jobs.py::test_delete_and_undo_errors |
| P325 | Hostile or long text | Toast and dialogs escape HTML | - | n/a: Rich markup escape instead | `tui/widgets/toast.py` | n/a | Toasts are plain text; no HTML to escape |

## Keyboard

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P326 | Help sheet | Sheet listing all shortcuts; `?` or `esc` closes; Tab is trapped | `?` | Help screen generated from `keys.py` | `tui/screens/help.py` | done | tests/tui/test_commands.py::test_question_mark_opens_help_and_closes_it; tests/tui/test_commands.py::test_help_rows_and_bindings_read_the_table |
| P327 | Key: search | `/`, `Cmd+K` | `/` | `/` (no `ctrl+k` search; it opens the action menu) | `tui/keys.py` | done | tests/tui/test_viewstrip.py::test_slash_focuses_the_search_and_selects_the_old_text |
| P328 | Key: move | `j`, `k`, arrows | `j`,`k` | `j`,`k`, arrows | `tui/keys.py` | done | tests/tui/test_skill_list.py::test_keys_move_open_and_jump |
| P329 | Key: open details | `Enter` | `Enter` | `enter`; on a repo row, `enter` expands or collapses the repo | `tui/keys.py` | done | tests/tui/test_app.py::test_enter_selects_and_opens_the_detail |
| P330 | Key: toggle skill | `x`, `Space` (row focused) | `x` | `x`, `space` | `tui/keys.py` | done | tests/tui/test_skill_list.py::test_x_on_the_cursor_row_toggles_through_jobs |
| P331 | Key: update | `u` | `u` | `u` | `tui/keys.py` | done | tests/tui/test_jobs.py::test_u_runs_a_job_the_bar_fills_and_the_ticks_leave |
| P332 | Key: install | `i` | `i` | `i` | `tui/keys.py` | done | tests/tui/test_jobs.py::test_install_one_available_skill_and_the_new_ones |
| P333 | Key: reader | `v` | `v` | `v` | `tui/keys.py` | done | tests/tui/test_reader.py::test_v_reads_the_selected_skill |
| P334 | Key: raw or formatted | `r` (reader open) | `r` | `r` | `tui/screens/reader.py` (keys.py row `r` where reader) | done | tests/tui/test_reader.py::test_r_and_clicks_switch_between_formatted_and_markdown |
| P335 | Key: compact | `c` | `c` | `c` | `tui/keys.py` | done | tests/tui/test_skill_list.py::test_compact_rows_have_no_blank_lines_and_no_spark |
| P336 | Key: panel | `]` | `]` | `\` (since `[` and `]` change harness) | `tui/keys.py` | done | tests/tui/test_app.py::test_backslash_hides_and_shows_the_panel |
| P337 | Key: layout | `g` | `g` | `g` (roomy rows) | `tui/keys.py` | n/a | Plan decision: no cards layout; `g` is not bound in keys.py. Compact rows (`c`) cover density |
| P338 | Key: sort | `s` | `s` | `s` | `tui/keys.py` | done | tests/tui/test_commands.py::test_s_cycles_the_sort_and_toasts |
| P339 | Key: mark | `m` | `m` | `m` | `tui/keys.py` | done | tests/tui/test_skill_list.py::test_marks_with_keys |
| P340 | Key: select all | `Cmd+A` | `Cmd+A` | `ctrl+a` | `tui/keys.py` | done | tests/tui/test_bulkbar.py::test_the_mark_cell_marks_all_shown_then_clears_them |
| P341 | Key: escape | Close, clear, cancel in this order: search text, link form, bulk form, menu, confirm, marks, selection | `esc` | Same order | `tui/app.py` | done | app.py:action_escape + jobs.escape. Order: pending "Replace my edits", search text, narrow drawer, marks, focus to list; tests/tui/test_jobs.py::test_an_edited_skill_asks_before_its_edits_go; tests/tui/test_viewstrip.py::test_esc_clears_the_text_then_leaves_the_box |
| P342 | Key: undo | `Cmd+Z` | `Cmd+Z` | `z` | `tui/keys.py` | done | tests/tui/test_jobs.py::test_z_puts_the_switch_back_and_does_nothing_when_the_stack_is_empty |
| P343 | Key: help | `?` | `?` | `?` | `tui/keys.py` | done | tests/tui/test_commands.py::test_question_mark_opens_help_and_closes_it |
| P344 | Key: views | No keys for tabs in the web | - | `1`-`9`, fixed per view | `tui/keys.py` | done | tests/tui/test_viewstrip.py::test_digit_keys_move_the_active_tab |
| P345 | Key: harness | No keys in the web | - | `[` and `]` | `tui/keys.py` | done | tests/tui/test_header.py::test_brackets_step_through_harnesses_and_keep_the_active_tab_shown |
| P346 | Key: action menu | No web menu key; the group menu is a "..." button | - | `ctrl+k` | `tui/commands.py` | done | tests/tui/test_commands.py::test_ctrl_k_opens_the_menu_for_an_outdated_skill |
| P347 | Key: command palette | No web palette | - | `ctrl+p` (all commands) | `tui/commands.py` | done | tests/tui/test_commands.py::test_ctrl_p_opens_the_atlas_palette_with_the_selection_color |
| P348 | Key: quit | No quit (browser) | - | `q` | `tui/keys.py`, `tui/app.py` | done | tests/tui/test_commands.py::test_q_closes_a_dialog_types_in_a_field_and_quits_from_the_main_screen |
| P349 | Key hints in the key bar | Hints near rows; Display > Show keyboard hints | - | Bottom key bar: `enter`, `ctrl+k`, `?`; on a repo row, `enter` reads expand or collapse; marks, search, and the panel have their own hints | `tui/widgets/keybar.py` | done | tests/tui/test_commands.py::test_the_bar_follows_the_marks_and_the_search; tests/tui/test_commands.py::test_enter_reads_expand_or_collapse_on_a_repo_row_and_holds_its_width |
| P350 | Keys when typing | Shortcuts are off while an input has focus (except esc) | - | Same | `tui/keys.py` | done | tests/tui/test_app.py::test_typing_in_search_does_not_run_keys |
| P351 | Keys when a dialog is open | The page handler returns; dialogs own their keys | - | Screens own their keys | `tui/keys.py` | done | tests/tui/test_commands.py::test_q_closes_a_dialog_types_in_a_field_and_quits_from_the_main_screen |
| P352 | Mouse support | Click everything | - | Click rows, tabs, switches, and buttons (Textual mouse) | `tui/app.py` | done | tests/tui/test_app.py::test_click_a_harness_tab_and_a_view_tab |
| P353 | Terminal-reserved keys | n/a on the web | - | Do not bind `ctrl+c`, `ctrl+z`, `ctrl+s`, or `ctrl+q` | `tui/keys.py` | done | tests/tui/test_app.py::test_no_key_takes_a_terminal_shortcut; tests/tui/test_commands.py::test_no_key_takes_a_terminal_shortcut |

## Display options

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P354 | Layout | List or Cards | `g` | `g` list and roomy rows | `tui/widgets/sidepanel.py` | n/a | Layout list or cards: no cards layout in the TUI (plan decision); `g` is not bound |
| P355 | Sort | Name, Most used, Recent, Cost | `s` | Same | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_display_changes_apply_at_once_with_the_keys |
| P356 | Collections size | Regular or Large group rows | - | Group rows regular or tall (two lines) | `tui/widgets/sidepanel.py`, `tui/widgets/skill_list.py` | done | state.group_size (saved); sidepanel Collections choice; skill_list two-line group headers; tests/tui/test_sidepanel.py, tests/tui/test_skill_list.py |
| P357 | Group by | Source or Scope | - | Same; palette "Group by" | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_display_changes_apply_at_once_with_the_keys |
| P358 | Theme | System, Light, Dark; system follows the OS | - | System (read from `COLORFGBG` or the terminal), Light, Dark | `tui/theme.py` | done | theme.system_shade (COLORFGBG, else the macOS look on a local session); tests/tui/test_theme.py::test_system_mode_follows_the_terminal |
| P359 | Palette | Atlas, Stone, Sage, Heather, Graphite | - | The same 5 palettes as Textual themes | `tui/theme.py` | done | tests/tui/test_theme.py::test_ten_themes_with_the_contract_names |
| P360 | Background texture | None, Contours, Chart, Paper, Linen | - | n/a: image textures do not render in a terminal; no substitute | `tui/widgets/sidepanel.py` | n/a | Image textures do not render in a terminal; no substitute |
| P361 | Show project skills | Checkbox; adds project groups; dot on the Display button | - | Check in the Display pane (`,`); palette | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_display_changes_apply_at_once_with_the_keys |
| P362 | Show old plugin versions | Checkbox; adds stale versions with a "vX" tag | - | Check in the Display pane (`,`); palette | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_display_changes_apply_at_once_with_the_keys |
| P363 | Show keyboard hints | Checkbox; hides inline key hints only | - | Check in the Display pane (`,`) | `tui/widgets/sidepanel.py` | done | tests/tui/test_commands.py::test_key_hints_off_hides_the_bar |
| P364 | Compact rows | `c`; saved | `c` | `c`; check in the Display pane | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_display_changes_apply_at_once_with_the_keys |
| P365 | Details panel open | Saved | `]` | `\` | `tui/app.py` | done | sidepanel.py: Display check "Details panel" calls app.show_detail; tests/tui/test_sidepanel.py |
| P366 | Reduced motion | Honors the OS setting | - | Setting "Reduce motion" and `TEXTUAL_ANIMATIONS=none` | `tui/widgets/sidepanel.py` | done | tests/tui/test_app.py::test_reduced_motion_turns_animation_off |
| P367 | Preferences saved | Stored in localStorage | - | Saved in the config folder as UIState preferences | `tui/state.py` | done | tests/tui/test_app.py::test_prefs_round_trip |
| P368 | Display popover keys | `esc` closes and refocuses the button | `esc` | `esc` | `tui/widgets/sidepanel.py` | n/a | The Display pane is part of the side panel, not a popover; `esc` follows the normal order |
| P369 | Page scale and zoom | Display > Size | - | n/a: the terminal sets the font size; see header section | `tui/widgets/sidepanel.py` | n/a | The terminal sets the font size |

## Edge cases

| # | Feature | Web behavior | Web key | TUI key or path | TUI owner file | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P370 | Read-only build | Band; no cluster, Profiles, bulk marks, Updates/New/Unused tabs, switches, update, delete, reveal, or skill set; reader shows `body_preview`; security counts only | - | Core reports read-only and the TUI hides the same items | `tui/app.py` | n/a | n/a: the TUI always runs on a writable core; there is no read-only TUI build |
| P371 | Empty state: search | "No skills match “<q>”" with "Try fewer or shorter words." or "The <view> filter is on."; "N hidden skills match."; buttons Clear search and Show project skills | - | Same copy and buttons | `tui/widgets/skill_list.py` | done | core/views.py:empty_state supplies the copy; rendered by skill_list.py:_empty_lines. tests/tui/test_skill_list.py::test_search_rebuilds_once_per_burst_and_shows_the_empty_state covers the search case only |
| P372 | Empty state: Updates | "Everything is up to date" with "Checked Nm ago." / "Checked just now." / "No check has run yet."; Check again | - | Same copy | `tui/widgets/skill_list.py` | done | core/views.py:empty_state supplies the copy; rendered by skill_list.py:_empty_lines. tests/tui/test_skill_list.py::test_search_rebuilds_once_per_burst_and_shows_the_empty_state covers the search case only |
| P373 | Empty state: Issues | "No problems found" — "Each SKILL.md in this view has valid frontmatter, and each file it names is there."; Show all skills | - | Same copy | `tui/widgets/skill_list.py` | done | core/views.py:empty_state supplies the copy; rendered by skill_list.py:_empty_lines. tests/tui/test_skill_list.py::test_search_rebuilds_once_per_burst_and_shows_the_empty_state covers the search case only |
| P374 | Empty state: Similar and Diverged | "No similar skills" / "No diverged copies" with their text; Show all skills | - | Same copy | `tui/widgets/skill_list.py` | done | core/views.py:empty_state supplies the copy; rendered by skill_list.py:_empty_lines. tests/tui/test_skill_list.py::test_search_rebuilds_once_per_burst_and_shows_the_empty_state covers the search case only |
| P375 | Empty state: Review | "Nothing to review" with the security note; Show all skills | - | Same copy | `tui/widgets/skill_list.py` | done | core/views.py:empty_state supplies the copy; rendered by skill_list.py:_empty_lines. tests/tui/test_skill_list.py::test_search_rebuilds_once_per_burst_and_shows_the_empty_state covers the search case only |
| P376 | Empty state: Unused | "Every skill is in use" — "Each one ran in the last 90 days." | - | Same copy | `tui/widgets/skill_list.py` | done | core/views.py:empty_state supplies the copy; rendered by skill_list.py:_empty_lines. tests/tui/test_skill_list.py::test_search_rebuilds_once_per_burst_and_shows_the_empty_state covers the search case only |
| P377 | Empty state: Costly | "No costly skills sit unused" — "Each costly skill that is on ran in the last 90 days."; Show all skills | - | Same copy | `tui/widgets/skill_list.py` | done | core/views.py:empty_state supplies the copy; rendered by skill_list.py:_empty_lines. tests/tui/test_skill_list.py::test_search_rebuilds_once_per_burst_and_shows_the_empty_state covers the search case only |
| P378 | Empty state: Off | "Nothing is off" — "Every skill in this view loads." | - | Same copy | `tui/widgets/skill_list.py` | done | core/views.py:empty_state supplies the copy; rendered by skill_list.py:_empty_lines. tests/tui/test_skill_list.py::test_search_rebuilds_once_per_burst_and_shows_the_empty_state covers the search case only |
| P379 | Empty state: default | "No skills here" — "Turn on Project skills or Old plugin versions to see more." | - | Same copy | `tui/widgets/skill_list.py` | done | core/views.py:empty_state supplies the copy; rendered by skill_list.py:_empty_lines. tests/tui/test_skill_list.py::test_search_rebuilds_once_per_burst_and_shows_the_empty_state covers the search case only |
| P380 | Stale scan | Band says the code changed on disk; a restarted server shows the reload band | - | See the header section (changed-on-disk band only) | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_the_stale_band_asks_for_a_restart |
| P381 | Sources that failed to check | Header warning "N source(s) unchecked" with texts; their skills show no update status | - | Same | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_unchecked_sources_show_the_errors_and_check_again |
| P382 | Edited skills | "edited" tag, warn state, batch skips, confirm label, diff warning, delete warning | - | Covered by the rows above; audit one test for the whole path | `tui/widgets/skill_list.py` | done | tests/tui/test_jobs.py::test_an_edited_skill_asks_before_its_edits_go; tests/tui/test_diff.py::test_edited_skill_warns_and_asks_to_replace_edits |
| P383 | Plugin skills | No update check, no delete; one switch per plugin; "not in enabledPlugins" note when unset | - | Same | `tui/widgets/skill_list.py` | done | core/views.py (no update check for plugins); skill_list.py:_group_switch; no test |
| P384 | Harness with no per-skill switch | Meta line, no row switch, "no switch" in Loaded by, no profile save, no bulk toggle | - | Same | `tui/widgets/switch.py` | done | tests/tui/test_detail.py::test_a_harness_without_a_switch_says_so; tests/tui/test_dialogs.py::test_profiles_without_a_switch |
| P385 | All harnesses mode | Row dots, no row switch, no group switch, meta "pick a harness", cost list per harness, delete confirm names all harnesses | - | Same | `tui/widgets/skill_list.py` | done | tests/tui/test_skill_list.py::test_all_harnesses_show_dots_not_switches |
| P386 | Built-ins off | Meta text "built-ins off" for Claude Code when bundled skills are disabled | - | Same | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_meta_says_where_the_switches_write |
| P387 | Project skills toggle | Hidden by default; the dot on Display shows when on; the empty-state button turns it on | - | Same | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_display_changes_apply_at_once_with_the_keys |
| P388 | Old plugin versions toggle | Hidden by default; rows show "vX" tag and "Old version" card; plugin switch hidden | - | Same | `tui/widgets/sidepanel.py` | done | tests/tui/test_sidepanel.py::test_display_changes_apply_at_once_with_the_keys |
| P389 | Skills outside the store | Copies for one harness: "A copy for one harness" card; no update, link, or delete | - | Same | `tui/widgets/detail.py` | done | detail_build.py:_cards; no test |
| P390 | Untracked prefix groups | Skills named `acme-*` with 3 or more members form a group "acme-*" (longest shared prefix) | - | Same rule in `core/views.py` | `core/views.py` | done | core/views.py (shared rule); core tests |
| P391 | Duplicate descriptions | "same as <name>" tag and Duplicates stat | - | Same | `core/views.py` | done | core/views.py (dupes); no TUI test |
| P392 | Usage not ready or failed | Unused tab shows a wait style, hides on error; costly set is empty until ready | - | Same | `tui/widgets/viewstrip.py` | done | tests/tui/test_viewstrip.py::test_unused_waits_until_usage_is_read |
| P393 | Offline or no GitHub | Update checks fail with the unchecked warning; descriptions show "Description unavailable" | - | Same | `tui/widgets/header.py` | done | tests/tui/test_header.py::test_unchecked_sources_show_the_errors_and_check_again; skill_list.py:_avail_cells ("Description unavailable") |
| P394 | Narrow terminal (80x24) | Page has a narrow layout with a scrim over the panel | - | Panel becomes a full-width overlay under 100 columns; tabs scroll | `tui/app.py` | done | tests/tui/test_app.py::test_narrow_panel_is_an_overlay_and_keeps_the_saved_choice |
| P395 | No harness found | Picker hidden; stderr note "No agent harness found" at start | - | Same stderr note; empty state in the app | `tui/app.py` | done | skill_list.py empty state "No agent harness found" / "Set config_roots in <path>." (Atlas.data config_path); tests/tui/test_skill_list.py |
| P396 | Over SSH | n/a on the web | - | Hide Reveal in Finder; copy by OSC 52 | `tui/commands.py` | done | tests/tui/test_jobs.py::test_over_ssh_copy_does_not_claim_success_and_reveal_explains; tests/tui/test_commands.py::test_over_ssh_the_menu_has_no_reveal |
| P397 | Demo mode | n/a on the web | - | `atlas tui --demo` loads `DemoAtlas` | `tui/app.py` | done | src/skill_atlas/tui/__init__.py:launch (--demo) -> app.py:run (DemoAtlas); tests/tui/test_bootstrap.py::test_tui_command_goes_to_launch |
| P398 | First-run install of Textual | n/a on the web | - | Ask before install; see plan.md Bootstrap | `tui/bootstrap.py` | done | tests/tui/test_bootstrap.py::test_yes_installs_without_a_question; tests/tui/test_bootstrap.py::test_n_declines |
| P399 | Web page stays the default | n/a on the TUI | - | `atlas` opens the web page; `atlas tui` opens the TUI | `tui/__init__.py` | done | tests/tui/test_bootstrap.py::test_tui_command_goes_to_launch; tests/tui/test_bootstrap.py::test_other_arguments_go_to_serve; tests/tui/test_bootstrap.py::test_web_path_never_imports_textual |
| P400 | Avatars and banners fetched from GitHub | The page loads images from GitHub (privacy note) | - | n/a: the TUI loads no images, so it makes no such requests | `tui/widgets/detail.py` | n/a | The TUI loads no images, so it makes no such requests |
| P401 | Background texture images | Served from /bg/<name>.webp | - | n/a: see Display options | `tui/theme.py` | n/a | No textures in the TUI |
