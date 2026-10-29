"""The command palette (ctrl+p) and the action menu (ctrl+k, or a right-click on a row)."""

from __future__ import annotations

import importlib
import inspect
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar, cast
from weakref import WeakKeyDictionary

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.command import CommandPalette, DiscoveryHit, Hit, Hits, Provider
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.fuzzy import Matcher
from textual.geometry import Offset
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ..core import views
from . import jobs, keys, theme
from .messages import ItemSelected, SkillSelected
from .screens import AtlasModal, CloseCell
from .state import MOTIONS
from .widgets import app_of

if TYPE_CHECKING:
    from textual.app import App

    from .app import AtlasApp

NAME_COL = 10
SORT_WORDS = {
    "name": "name",
    "uses": "most used",
    "recent": "recently used",
    "cost": "context cost",
}
VIEW_TITLES = {
    "all": "Show all skills",
    "on": "Show skills that are on",
    "off": "Show skills that are off",
    "updates": "Show updates",
    "issues": "Show issues",
    "new": "Show new skills",
    "unused": "Show unused skills",
    "costly": "Show costly skills",
    "similar": "Show similar skills",
    "diverged": "Show diverged copies",
    "review": "Show skills to review",
}
# Textual's own commands that this palette replaces or does not need.
SKIP_SYSTEM = {"Quit", "Keys", "Theme", "Minimize", "Maximize", "Check for updates", "Bell"}
# Action id -> the keys.py key that does the same thing from the list.
ACTION_KEYS = {
    "open": "enter",
    "fold": "enter",
    "read": "v",
    "switch": "x",
    "everywhere": "X",
    "update": "u",
    "diff": "d",
    "history": "h",
    "copy": "y",
    "mark": "m",
    "github": "o",
    "reveal": "R",
    "link": "l",
    "delete": "delete",
    "install": "i",
    "new": "I",
}


# Calling the modules that own each feature


def _ssh() -> bool:
    return bool(os.environ.get("SSH_TTY"))


async def call(app: AtlasApp, module: str, func: str, *args: Any, **kwargs: Any) -> None:
    """Call `skill_atlas.tui.<module>.<func>(app, ...)`, awaiting it when it is async."""
    name = f"{__package__}.{module}"
    try:
        fn = getattr(importlib.import_module(name), func, None)
    except ModuleNotFoundError as e:
        if e.name != name:
            raise
        fn = None
    if fn is None:
        app.notify("This command does not work yet.", severity="warning")
        return
    result = fn(app, *args, **kwargs)
    if inspect.isawaitable(result):
        await result


def toast(app: AtlasApp, text: str | Text, **kwargs: Any) -> None:
    jobs.toast(app, text, **kwargs)


def _later(app: AtlasApp, module: str, func: str, *args: Any, **kwargs: Any) -> Callable[[], Any]:
    return partial(call, app, module, func, *args, **kwargs)


def harness_label(app: AtlasApp, harness: str) -> str:
    h = app.data.harnesses.get(harness) or {}
    return h.get("label") or h.get("name") or harness


# Values that change only with the data, the harness, and the hidden-skill toggles


_MEMO: WeakKeyDictionary[Any, tuple[tuple, dict[str, Any]]] = WeakKeyDictionary()


def _memo(app: AtlasApp) -> dict[str, Any]:
    ins = app.data.insights
    st = app.state
    stamp = (id(ins), st.harness, st.show_project, st.show_stale)
    hit = _MEMO.get(app)
    if hit is None or hit[0] != stamp or hit[1].get("ins") is not ins:
        hit = (stamp, {"ins": ins})
        _MEMO[app] = hit
    return hit[1]


def _wide_state(app: AtlasApp) -> views.ViewState:
    st = app.state
    return views.ViewState(
        harness=st.harness or "all",
        show_project=st.show_project,
        show_stale=st.show_stale,
    )


def groups(app: AtlasApp) -> dict[str, views.Group]:
    """Every group in the harness by id, as the All view shows them grouped by source."""
    memo = _memo(app)
    ins = app.data.insights
    if "groups" not in memo and ins is not None:
        memo["groups"] = {g["id"]: g for g in views.groups(ins, _wide_state(app))}
    return memo.get("groups") or {}


def counts(app: AtlasApp) -> dict[str, int]:
    """The view tab counts, for the palette and the key bar."""
    return app.data.counts(_wide_state(app))


def cost(app: AtlasApp) -> dict:
    """views.context_cost for the harness."""
    memo = _memo(app)
    ins = app.data.insights
    if "cost" not in memo and ins is not None:
        memo["cost"] = views.context_cost(ins, app.state.harness or "all")
    return memo.get("cost") or {}


# Targets and their actions


@dataclass
class Target:
    """What a menu acts on. kind is "skill", "group", or "avail"; key is its path or item key."""

    kind: str
    key: str
    title: str
    item: dict
    repo: str = ""


def target_of(app: AtlasApp, key: str | None = None) -> Target | None:
    """The target for a skill path, a group id, or `a:<repo>:<path>`; by default the selection."""
    ins = app.data.insights
    if not key:
        path, item = app.current()
        key = path or item
    if ins is None or not key:
        return None
    if key in ins.by_path:
        s = ins.by_path[key]
        return Target("skill", key, f"/{s.get('invoke') or s['name']}", s)
    if key.startswith("a:"):
        repo, _, path = key[2:].partition(":")
        a = next((x for x in app.data.available.get(repo) or [] if x.get("path") == path), None)
        return Target("avail", key, f"/{a['name']}", a, repo) if a else None
    g = groups(app).get(key)
    if g is None:
        return None
    return Target("group", key, g["label"], dict(g), g.get("repo") or "")


@dataclass
class Action:
    """One row of the action menu. id is also the flag that keys.Key.needs names."""

    id: str
    label: str
    run: Callable[[], Any]
    note: str = ""
    danger: bool = False

    @property
    def key(self) -> str:
        name = ACTION_KEYS.get(self.id)
        return keys.key(name).short if name else ""


def _everywhere(ins: views.Insights, s: dict) -> list[tuple[str, views.Switch]]:
    out = []
    for h in ins.harness_ids:
        if views.loads(h, s):
            sw = views.switch_state(ins, h, s)
            if sw["toggle"]:
                out.append((h, sw))
    return out


def _select(app: AtlasApp, t: Target, open: bool) -> None:
    if t.kind == "skill":
        app.post_message(SkillSelected(t.key, open=open))
    else:
        app.post_message(ItemSelected(t.key, open=open))


def _repo_open(app: AtlasApp, t: Target) -> list[Action]:
    """On a repo that folds, enter folds it, so the menu names that and keeps details keyless."""
    from .widgets.skill_list import SkillList

    details = partial(_select, app, t, True)
    found = app.main.query(SkillList)
    lst = found.first() if found else None
    if lst is None or not lst.can_fold(t.key):
        return [Action("open", "Open details", details)]
    label = "Expand" if t.key in app.state.folds() else "Collapse"
    return [
        Action("fold", label, partial(lst.toggle_fold, t.key)),
        Action("details", "Open details", details),
    ]


def actions_for(app: AtlasApp, t: Target) -> list[Action]:
    """The actions that apply to a target, in menu order. Delete comes last."""
    ins = app.data.insights
    if ins is None:
        return []
    if t.kind == "skill":
        return _skill_actions(app, ins, t)
    if t.kind == "group":
        return _group_actions(app, ins, t)
    return _avail_actions(app, ins, t)


def _mark(app: AtlasApp, path: str) -> None:
    app.set_state(marked=app.state.marked ^ {path})


def _skill_actions(app: AtlasApp, ins: views.Insights, t: Target) -> list[Action]:
    s, h, ok = t.item, app.state.harness, ins.writable
    acts = [
        Action("open", "Open details", partial(_select, app, t, True)),
        Action("read", "Read SKILL.md", _later(app, "screens.reader", "open_reader", s["path"])),
    ]
    sw = views.switch_state(ins, h, s)
    if ok and h != "all" and sw["toggle"]:
        verb = "off" if sw["on"] else "on"
        run = _later(app, "jobs", "set_switch", h, [sw["key"]], not sw["on"], kind=sw["toggle"])
        acts.append(Action("switch", f"Turn {verb} in {harness_label(app, h)}", run))
    every = _everywhere(ins, s)
    if ok and (len(every) > 1 or (h == "all" and every)):
        verb = "off" if any(sw["on"] for _, sw in every) else "on"
        acts.append(
            Action("everywhere", f"Turn {verb} everywhere", partial(toggle_everywhere, app, t.key))
        )
    name = views.lock_name(s)
    if ok and name and views.is_outdated(ins, s):
        acts.append(Action("update", "Update", _later(app, "jobs", "update", [name])))
        acts.append(Action("diff", "See changes", _later(app, "screens.diff", "open_diff", name)))
    if name:
        run = _later(app, "screens.history", "open_history", name)
        acts.append(Action("history", "History", run, " · –"))
    copies = s.get("copies") or []
    if copies:
        run = _later(app, "screens.diff", "open_compare", s["path"], copies[0]["path"])
        acts.append(Action("compare", "Compare with its other copy", run))
    if ok:
        verb = "Unmark" if t.key in app.state.marked else "Mark"
        acts.append(Action("mark", verb, partial(_mark, app, t.key)))
    folder = s.get("dir_name") or s["name"]
    acts.append(Action("copy", "Copy as prompt", _later(app, "jobs", "copy_prompt", [folder])))
    where = s.get("dir") or s["path"]
    acts.append(Action("copy_path", "Copy path", _later(app, "jobs", "copy", where, "the path")))
    url = jobs.github_url(s)
    if url:
        acts.append(
            Action("github", "Open on GitHub", _later(app, "jobs", "open_github", url), " ↗")
        )
    if ok and not _ssh():
        path = s.get("dir") or s["path"]
        acts.append(Action("reveal", keys.REVEAL, _later(app, "jobs", "reveal", path)))
    personal = ok and s.get("store") and s.get("scope") == "personal"
    if personal and not name:
        run = _later(app, "screens.link", "open_link", [folder])
        acts.append(Action("link", "Link to GitHub…", run))
    if personal:
        run = _later(app, "screens.confirm", "confirm_delete", [folder])
        acts.append(Action("delete", "Move to Trash…", run, danger=True))
    return acts


def _group_actions(app: AtlasApp, ins: views.Insights, t: Target) -> list[Action]:
    g, h, ok = t.item, app.state.harness, ins.writable
    members = g["members"]
    acts = _repo_open(app, t)
    if ok and g["switch"] and h != "all":
        on = g["checked"] == "true"
        verb = "off" if on else "on"
        where = harness_label(app, h)
        if g["kind"] == "plg":
            run = _later(app, "jobs", "set_switch", h, [g["key"]], not on, kind="plugin")
            acts.append(Action("switch", f"Turn {verb} {g['label']} in {where}", run))
        else:
            names = [views.switch_state(ins, h, s)["key"] for s in members]
            run = _later(app, "jobs", "set_switch", h, names, not on, kind="skill")
            label = f"Turn {verb} all {len(members)} in {where}"
            acts.append(Action("switch", label, run))
            if g["checked"] == "mixed":
                sws = (views.switch_state(ins, h, s) for s in members)
                lit = [sw["key"] for sw in sws if sw["on"]]
                run = _later(app, "jobs", "set_switch", h, lit, False, kind="skill")
                acts.append(Action("switch_off", f"Turn off all {len(lit)} in {where}", run))
    outdated = [n for s in members if views.is_outdated(ins, s) for n in [views.lock_name(s)] if n]
    if ok and outdated:
        run = _later(app, "jobs", "update", outdated)
        acts.append(Action("update", f"Update {len(outdated)}", run))
    repo = t.repo
    offered = [a for a in app.data.available.get(repo) or [] if not a.get("taken")] if repo else []
    fresh = [a for a in offered if a.get("new")]
    if ok and views.reads_store(ins, h):
        if fresh:
            run = _later(app, "jobs", "install", repo, [a["path"] for a in fresh])
            acts.append(Action("new", f"Install {len(fresh)} new", run))
        elif len(offered) > 1:
            run = _later(app, "jobs", "install", repo, [a["path"] for a in offered])
            acts.append(Action("install_all", f"Install all {len(offered)}", run))
    if ok and fresh:
        run = partial(dismiss_new, app, repo, [a["path"] for a in fresh])
        acts.append(Action("dismiss", "Dismiss new", run))
    if g.get("repo_url"):
        run = _later(app, "jobs", "open_github", g["repo_url"])
        acts.append(Action("github", "Open on GitHub", run, " ↗"))
    if ok and repo in ((app.data.updates or {}).get("watched") or []):
        acts.append(Action("unwatch", "Stop watching", partial(stop_watching, app, repo)))
    stored = [s.get("dir_name") or s["name"] for s in members if s.get("store")]
    if ok and g["kind"] == "src" and g.get("local") and stored:
        acts.append(
            Action("link", "Link to GitHub…", _later(app, "screens.link", "open_link", stored))
        )
    if ok and g["kind"] == "src" and stored:
        run = _later(app, "screens.confirm", "confirm_delete", stored)
        label = f"Move {views.plural(len(stored), 'skill')} to Trash…"
        acts.append(Action("delete", label, run, danger=True))
    return acts


def _avail_actions(app: AtlasApp, ins: views.Insights, t: Target) -> list[Action]:
    a, repo, ok = t.item, t.repo, ins.writable
    acts = [
        Action("open", "Open details", partial(_select, app, t, True)),
        Action("read", "Read SKILL.md", _later(app, "screens.reader", "open_reader", t.key)),
    ]
    if ok and not a.get("taken") and views.reads_store(ins, app.state.harness):
        acts.append(Action("install", "Install", _later(app, "jobs", "install", repo, [a["path"]])))
    if ok and a.get("new"):
        acts.append(Action("dismiss", "Dismiss new", partial(dismiss_new, app, repo, [a["path"]])))
    folder = str(a.get("path", "")).removesuffix("SKILL.md").rstrip("/")
    url = f"https://github.com/{repo}/tree/HEAD/{folder}"
    acts.append(Action("github", "Open on GitHub", _later(app, "jobs", "open_github", url), " ↗"))
    return acts


def flags(app: AtlasApp) -> frozenset[str]:
    """What the selection or the marks allow. keys.Key.needs reads these."""
    ins = app.data.insights
    if ins is None:
        return frozenset()
    out: set[str] = set()
    if ins.writable:
        out.add("writable")
        if app.state.view != "new":
            out.add("watch")
        if counts(app).get("updates"):
            out.add("updates")
    t = target_of(app)
    if t is not None:
        out.add("open")
        out.update(a.id for a in actions_for(app, t))
        if ins.writable and t.kind != "avail":
            out.add("mark")
    marked = [ins.by_path[p] for p in app.state.marked if p in ins.by_path]
    if marked:
        out -= {"switch", "update", "copy", "link", "delete"}
        plan = views.bulk_plan(ins, app.state.harness, marked)
        on, off = plan["on"], plan["off"]
        if any(on.values()) or any(off.values()):
            out.add("switch")
        out.update(k for k in ("update", "link", "delete") if plan[k])
        out.add("copy")
    return frozenset(out)


# Commands that have no other owner


async def toggle_everywhere(app: AtlasApp, path: str | None = None) -> None:
    """shift+x: turn the skill off in every harness that loads it, or on when it is off in all."""
    ins = app.data.insights
    s = app.data.skill(path or app.current()[0])
    if ins is None or s is None:
        toast(app, "Select a skill, then press shift+x.")
        return
    if not ins.writable:
        toast(app, "This build is read-only. Run atlas to change skills.")
        return
    every = _everywhere(ins, s)
    if not every:
        toast(app, f"/{s['name']} has no switch in any harness.")
        return
    on = not any(sw["on"] for _, sw in every)
    by_kind: dict[tuple[str, str], list[str]] = {}
    for h, sw in every:
        if sw["on"] != on:
            by_kind.setdefault((sw["toggle"], sw["key"]), []).append(h)
    for (kind, name), hs in by_kind.items():
        await call(app, "jobs", "set_switch", hs, [name], on, kind=kind)


def cycle_sort(app: AtlasApp) -> None:
    """s: the next sort order, with the web's toast."""
    order = views.SORTS
    sort = order[(order.index(app.state.sort) + 1) % len(order)]
    app.set_state(sort=sort)
    toast(app, f"Sorted by {SORT_WORDS[sort]}.")


def _why(e: BaseException) -> str:
    return (str(e) or type(e).__name__).replace("`", "").rstrip(".")


LOCK_FIX = "Make sure that you can write to the lock file, then try again."


def _bold(lead: str, name: str, tail: str) -> Text:
    return Text.assemble(lead, (name, "bold"), tail)


async def stop_watching(app: AtlasApp, repo: str | None = None) -> None:
    """Stop the update check from listing new skills in repo, with undo."""
    repo = repo or (target_of(app) or Target("", "", "", {})).repo
    if not repo:
        return
    try:
        await app.fetch(app.atlas.watch, repo, False)
    except Exception as e:
        toast(app, f"Could not stop watching: {_why(e)}. {LOCK_FIX}", severity="error")
        return
    app.reload(["updates"])

    async def undo() -> None:
        try:
            await app.fetch(app.atlas.watch, repo, True)
        except Exception as e:
            fix = "Check your network, then press w to watch it again."
            toast(app, f"Could not watch {repo} again: {_why(e)}. {fix}", severity="error")
            return
        app.reload(["updates"])

    entry = jobs.push_undo(app, f"Stop watching {repo}", undo)
    text = _bold("Stopped watching ", repo, ".")
    toast(app, text, action=jobs.undo_action(app, entry))


async def dismiss_new(app: AtlasApp, repo: str, paths: list[str] | None = None) -> None:
    """Clear the "new" tags of a repo's skills. They stay under Available."""
    ins = app.data.insights
    if paths is None and ins is not None:
        paths = [a["path"] for a in views.new_in(ins, repo)]
    if not paths:
        return
    try:
        await app.fetch(app.atlas.dismiss, repo, paths)
    except Exception as e:
        toast(app, f"Could not dismiss: {_why(e)}. {LOCK_FIX}", severity="error")
        return
    app.reload(["updates"])
    n = views.plural(len(paths), "new skill")
    toast(app, _bold(f"Dismissed {n} from ", repo, ". They stay under Available."))


# A floating list with a filter field: the base of the action menu and the help screen


class Choices(OptionList, can_focus=False):
    """The list under a filter field. The field keeps the focus; up, down, and enter drive this."""

    DEFAULT_CSS = """
    Choices {
        height: auto; border: none; padding: 0; background: $atlas-surface-1;
        scrollbar-size-vertical: 1; scrollbar-background: $atlas-surface-1;
        scrollbar-background-hover: $atlas-surface-1; scrollbar-background-active: $atlas-surface-1;
    }
    Choices > .option-list--option { padding: 0 1; color: $atlas-text; }
    Choices > .option-list--option-highlighted {
        background: $atlas-selection; color: $atlas-text; text-style: none;
    }
    Choices > .option-list--option-hover { background: $atlas-surface-2; }
    Choices > .option-list--option-disabled { color: $atlas-muted; }
    Choices > .option-list--separator { color: $atlas-border; }
    """


class FilterField(Input):
    """The filter field. Keys in its screen's PASS_KEYS reach the screen instead of the text."""

    def check_consume_key(self, key: str, character: str | None) -> bool:
        if key in getattr(self.screen, "PASS_KEYS", ()):
            return False
        return super().check_consume_key(key, character)


class FilterModal(AtlasModal[None]):
    """A box with a bold title, a ✕, a filter field, and a list. Subclasses supply the rows."""

    PLACEHOLDER: ClassVar[str] = "Type to filter"
    PASS_KEYS: ClassVar[frozenset[str]] = frozenset()
    FILTER_IN_TITLE: ClassVar[bool] = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("down", "move(1)", "Next", show=False),
        Binding("up", "move(-1)", "Previous", show=False),
        Binding("pagedown", "page(1)", "Next page", show=False),
        Binding("pageup", "page(-1)", "Previous page", show=False),
        Binding("home", "jump(0)", "First", show=False, priority=True),
        Binding("end", "jump(-1)", "Last", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    FilterModal #box {
        width: auto; height: auto; max-height: 100%;
        background: $atlas-surface-1; border: round $atlas-border-strong; padding: 0 1;
    }
    FilterModal #top { height: 1; width: 100%; }
    FilterModal #title {
        width: 1fr; height: 1; padding: 0 1; text-wrap: nowrap; text-overflow: ellipsis;
    }
    FilterModal #filter {
        height: 1; border: none; padding: 0 1; margin: 1 0 0 0; background: $atlas-surface-2;
    }
    FilterModal #filter:focus { background: $atlas-surface-3; }
    FilterModal #filter > .input--placeholder { color: $atlas-faint; }
    FilterModal #filter > .input--cursor { text-style: none; }
    FilterModal Choices { margin: 1 0 0 0; }
    FilterModal #foot { color: $atlas-muted; padding: 0 1; margin: 1 0 0 0; height: auto; }
    """

    def heading(self) -> Content:
        return Content("")

    def footer(self) -> str:
        return ""

    def rows(self, query: str) -> list[Option | None]:
        raise NotImplementedError

    def choose(self, option_id: str) -> None:
        raise NotImplementedError

    def placeholder(self) -> str:
        return self.PLACEHOLDER

    def compose(self) -> ComposeResult:
        field = FilterField(placeholder=self.placeholder(), id="filter", compact=True)
        with Vertical(id="box"):
            with Horizontal(id="top"):
                yield field if self.FILTER_IN_TITLE else Static(self.heading(), id="title")
                yield CloseCell()
            if not self.FILTER_IN_TITLE:
                yield field
            yield Choices(id="choices")
            foot = self.footer()
            if foot:
                yield Static(foot, id="foot")

    def on_mount(self) -> None:
        self.fill()

    def on_click(self, event: events.Click) -> None:
        # Close only when the pointer is on the dim area; event.widget can be the screen itself.
        event.prevent_default()
        if self.get_widget_at(event.screen_x, event.screen_y)[0] is self:
            event.stop()
            self.dismiss(None)

    @property
    def choices(self) -> Choices:
        return self.query_one(Choices)

    @property
    def query_text(self) -> str:
        return self.query_one("#filter", Input).value.strip()

    def fill(self, keep: str | None = None) -> None:
        """Rebuild the rows for the filter text. keep: an option id to keep highlighted."""
        lst = self.choices
        lst.clear_options()
        lst.add_options(self.rows(self.query_text))
        ids = [lst.get_option_at_index(i).id for i in range(lst.option_count)]
        if keep in ids:
            lst.highlighted = ids.index(keep)
        else:
            lst.highlighted = next(
                (i for i in range(lst.option_count) if not lst.get_option_at_index(i).disabled),
                None,
            )

    @on(Input.Changed, "#filter")
    def _filter(self, event: Input.Changed) -> None:
        event.stop()
        self.fill()

    @on(Input.Submitted, "#filter")
    def _submit(self, event: Input.Submitted) -> None:
        event.stop()
        lst = self.choices
        if lst.highlighted is not None:
            option = lst.get_option_at_index(lst.highlighted)
            if not option.disabled and option.id:
                self.choose(option.id)

    @on(OptionList.OptionSelected)
    def _picked(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id:
            self.choose(event.option.id)

    def action_move(self, step: int) -> None:
        lst = self.choices
        lst.action_cursor_down() if step > 0 else lst.action_cursor_up()

    def action_page(self, step: int) -> None:
        lst = self.choices
        lst.action_page_down() if step > 0 else lst.action_page_up()

    def action_jump(self, where: int) -> None:
        lst = self.choices
        lst.action_first() if where == 0 else lst.action_last()


# The action menu


class ActionMenu(FilterModal):
    """The Finder-style menu for one target. It opens next to its row and stays on screen."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "close", "Close", show=False, priority=True)
    ]
    FILTER_IN_TITLE = True
    DEFAULT_CSS = """
    ActionMenu { align: left top; }
    ActionMenu.-center { align: center middle; }
    ActionMenu #filter, ActionMenu #filter:focus {
        width: 1fr; margin: 0; background: $atlas-surface-1; color: $atlas-text;
    }
    ActionMenu #filter > .input--placeholder { color: $atlas-text; text-style: bold; }
    ActionMenu Choices { margin: 0; }
    """

    def __init__(self, target: Target, acts: list[Action], at: Offset | None = None) -> None:
        super().__init__()
        self.target = target
        self.acts = acts
        self.notes = {a.id: a.note for a in acts}
        self.at = at
        self.keyw = max(len(a.key) for a in acts) + 2

    def placeholder(self) -> str:
        return f"Actions · {self.target.title}"

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#filter", Input).focus()
        self._place()
        self.run_worker(self._counts(), exclusive=True)

    def _measure(self) -> tuple[int, int]:
        """Border, box padding, and option padding around the widest row; rows plus 3."""
        wide = max(len(a.label) + len(a.note) for a in self.acts)
        extra = 12 if any(a.id == "history" for a in self.acts) else 0
        width = 2 + 2 + 2 + self.keyw + wide + extra
        title = 2 + 2 + 2 + len(self.placeholder()) + 3
        rows = len(self.acts) + any(a.danger for a in self.acts)
        return max(36, width, min(title, 60)), 2 + 1 + rows

    def _place(self) -> None:
        cols, lines = self.app.size
        width, height = self._measure()
        width = min(width, cols - 2)
        height = min(height, lines - 2)
        box = self.query_one("#box")
        box.styles.width = width
        self.choices.styles.height = max(1, height - 3)
        if self.at is None:
            self.add_class("-center")
            return
        x, y = self.at
        top = y + 1 if y + 1 + height <= lines else y - height
        if top < 0:
            top = max(0, lines - height)
        box.styles.offset = (max(0, min(x, cols - width)), top)

    async def _counts(self) -> None:
        """The History note, from local snapshots. An update file count would need a download."""
        app = app_of(self)
        name = views.lock_name(self.target.item) if self.target.kind == "skill" else None
        if not name:
            return
        if "history" in self.notes:
            try:
                h = await app.fetch(app.atlas.history, name)
            except Exception:
                self.notes["history"] = ""
            else:
                n = len(h.get("snapshots") or [])
                self.notes["history"] = f" · {views.plural(n, 'version')}" if n else " · none yet"
            self._refresh_rows()

    def _refresh_rows(self) -> None:
        lst = self.choices
        hl = lst.highlighted
        keep = lst.get_option_at_index(hl).id if hl is not None else None
        self.fill(keep)

    def _row(self, a: Action) -> Option:
        tone = "$atlas-danger" if a.danger else "$atlas-text"
        parts: list[tuple[str, str]] = [
            (a.key.ljust(self.keyw), "$atlas-danger" if a.danger else "$atlas-accent"),
            (a.label, tone),
        ]
        note = self.notes.get(a.id, "")
        if note.startswith(" · "):
            rest = note[3:]
            look = "$atlas-faint" if rest == "–" else "$atlas-muted"
            parts += [(" · ", "$atlas-faint"), (rest, look)]
        elif note:
            parts.append((note, "$atlas-muted"))
        return Option(Content.assemble(*parts), id=a.id)

    def rows(self, query: str) -> list[Option | None]:
        if not query:
            out: list[Option | None] = []
            for a in self.acts:
                if a.danger and out:
                    out.append(None)
                out.append(self._row(a))
            return out
        matcher = Matcher(query)
        scored = []
        for i, a in enumerate(self.acts):
            exact = query == a.key
            score = matcher.match(a.label)
            if exact or score > 0:
                scored.append((not exact, -score, i, a))
        if not scored:
            return [Option(Content(f"No actions match “{query}”"), disabled=True)]
        return [self._row(row[-1]) for row in sorted(scored, key=lambda r: r[:3])]

    def choose(self, option_id: str) -> None:
        act = next((a for a in self.acts if a.id == option_id), None)
        self.dismiss(None)
        if act is not None:
            self.app.call_later(act.run)


def _anchor(app: AtlasApp) -> Offset | None:
    """Where the list cursor row is on screen, so the menu can open beside it."""
    found = app.main.query("#list")
    if not found:
        return None
    lst = found.first()
    line = lst.highlighted if isinstance(lst, OptionList) else getattr(lst, "cursor", None)
    if not isinstance(line, int) or line < 0:
        return None
    area = lst.scrollable_content_region
    y = area.y + line - int(lst.scroll_offset.y)
    return Offset(area.x + NAME_COL, y) if area.y <= y < area.bottom else None


def open_actions(app: AtlasApp, target: str | None = None, *, at: Offset | None = None) -> None:
    """ctrl+k or a right-click: the action menu for a skill path, a group id, or `a:<repo>:<path>`.

    at is the screen cell to open beside, such as the pointer; by default the list cursor row.
    """
    t = target_of(app, target)
    if t is None:
        toast(app, "Move to a skill or a group, then press ctrl+k.")
        return
    acts = actions_for(app, t)
    if not acts:
        return
    path, item = app.current()
    if target is not None and target != (path or item):
        _select(app, t, False)
    app.push_screen(ActionMenu(t, acts, at if at is not None else _anchor(app)))


# The command palette


class AtlasPalette(CommandPalette):
    """Textual's palette in the Atlas look: one floating surface, and the theme's selection."""

    DEFAULT_CSS = """
    AtlasPalette > .command-palette--help-text { color: $atlas-muted; text-style: none; }
    AtlasPalette > .command-palette--highlight { color: $atlas-accent; text-style: none; }
    AtlasPalette:nocolor > .command-palette--highlight { text-style: bold; }
    AtlasPalette > Vertical { width: 90%; max-width: 88; background: $atlas-surface-1; }
    AtlasPalette #--input {
        border: round $atlas-border-strong; background: $atlas-surface-1; padding: 0 1;
    }
    AtlasPalette #--input.--list-visible { border-bottom: none; }
    AtlasPalette SearchIcon { display: none; }
    AtlasPalette CommandInput { width: 1fr; }
    AtlasPalette CommandInput, AtlasPalette CommandInput:focus {
        border: none; height: 1; padding: 0 1; background: $atlas-surface-1;
    }
    AtlasPalette CommandInput > .input--placeholder { color: $atlas-faint; }
    AtlasPalette CommandInput > .input--cursor { text-style: none; }
    AtlasPalette CommandList, AtlasPalette CommandList:focus {
        border: round $atlas-border-strong; border-top: none; background: $atlas-surface-1;
        padding: 0 1; scrollbar-size-vertical: 1; scrollbar-background: $atlas-surface-1;
        scrollbar-background-hover: $atlas-surface-1; scrollbar-background-active: $atlas-surface-1;
    }
    AtlasPalette CommandList.--populating { border-bottom: none; }
    AtlasPalette CommandList > .option-list--option {
        padding: 0 1; color: $atlas-text; text-style: none;
    }
    AtlasPalette CommandList > .option-list--option-highlighted {
        background: $atlas-selection; color: $atlas-text; text-style: none;
    }
    AtlasPalette CommandList > .option-list--option-hover { background: $atlas-surface-2; }
    AtlasPalette CommandList > .option-list--option-disabled { color: $atlas-muted; }
    AtlasPalette LoadingIndicator {
        border: none; background: $atlas-surface-1; color: $atlas-accent;
        border-left: round $atlas-border-strong; border-right: round $atlas-border-strong;
    }
    """

    def __init__(self) -> None:
        super().__init__(
            providers=[AtlasCommands],
            placeholder="Search commands, views, and skills…",
            id="--command-palette",
        )

    def on_mount(self) -> None:
        self.query_one("#--input").mount(PaletteClose())


class PaletteClose(CloseCell):
    """The palette's ✕. It closes the palette as esc does."""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        event.prevent_default()
        self.app.call_later(self.screen.run_action, "escape")


def open_palette(app: AtlasApp) -> None:
    """ctrl+p: every command, view, harness, display setting, and skill."""
    if not CommandPalette.is_open(cast("App[object]", app)):
        app.push_screen(AtlasPalette())


@dataclass
class Entry:
    """One palette entry. key shows in the left column; note follows the title, muted."""

    title: str
    run: Callable[[], Any]
    key: str = ""
    note: str = ""


PALETTE_KEYW = 9
BULK = (
    ("Turn on marked skills", "turn_on"),
    ("Turn off marked skills", "turn_off"),
    ("Update marked skills", "update"),
    ("Link marked skills to GitHub…", "link"),
    ("Copy marked skills as prompt", "copy_prompt"),
    ("Save marked skills as profile…", "save_profile"),
    ("Delete marked skills…", "delete"),
    ("Clear marks", "clear"),
)
SKILL_SET = (
    ("Export the skill set to a file…", "open_export"),
    ("Copy the skill set as JSON", "copy_manifest"),
    ("Import a skill set from a file…", "open_import"),
    ("Restore missing skills from the lock file…", "open_restore"),
)


class AtlasCommands(Provider):
    """Every key action, view, harness, palette, mode, display toggle, and "Go to /name"."""

    def _app(self) -> AtlasApp:
        return app_of(self.screen)

    def commands(self) -> list[Entry]:
        """The entries that discovery lists, in order. Skills come only from search.

        First what the marks and the selection allow, then views, harnesses, other keys, and
        display.
        """
        app = self._app()
        have = flags(app)
        usable = [k for k in keys.KEYS if k.help and k.palette and (not k.needs or k.needs in have)]
        here = [k for k in usable if k.group == "Skill" and k.needs]
        out = []
        if app.state.marked:
            out += [Entry(title, _later(app, "widgets.bulkbar", fn)) for title, fn in BULK]
        out += [Entry(k.help, partial(app.run_key, k), k.short) for k in here]
        t = target_of(app)
        if t is not None:
            out += [
                Entry(a.label, a.run, note=a.note.strip(" ·–"))
                for a in actions_for(app, t)
                if a.id not in ACTION_KEYS
            ]
        out += self._views(app)
        out += self._harnesses(app)
        out += [Entry(k.help, partial(app.run_key, k), k.short) for k in usable if k not in here]
        out.append(Entry("Mark all shown skills", _later(app, "widgets.bulkbar", "mark_all")))
        out += [Entry(title, _later(app, "screens.transfer", func)) for title, func in SKILL_SET]
        out += self._display(app)
        for c in app.get_system_commands(self.screen):
            if c.title not in SKIP_SYSTEM:
                out.append(Entry(c.title, c.callback))
        return out

    def _views(self, app: AtlasApp) -> list[Entry]:
        n = counts(app)
        current = app.state.view
        out = []
        for v, _label, _title in views.VIEWS:
            note = "current" if v == current else (str(n[v]) if v in n else "")
            out.append(
                Entry(VIEW_TITLES[v], partial(app.set_state, view=v), keys.view_key(v), note)
            )
        return out

    def _harnesses(self, app: AtlasApp) -> list[Entry]:
        ins = app.data.insights
        if ins is None:
            return []
        out = [Entry("Switch harness", _later(app, "widgets.header", "open_harness_menu"))]
        for h in views.harness_choices(ins):
            title = (
                "Switch to all harnesses" if h == "all" else f"Switch to {harness_label(app, h)}"
            )
            note = "current" if h == app.state.harness else ""
            out.append(Entry(title, partial(app.set_state, harness=h), note=note))
        errors = (app.data.updates or {}).get("errors") or {}
        if errors:
            run = _later(app, "widgets.header", "show_source_errors")
            out.append(Entry("Show unchecked sources", run, note=str(len(errors))))
        return out

    def _display(self, app: AtlasApp) -> list[Entry]:
        st = app.state
        out = [
            Entry(
                f"Sort by {SORT_WORDS[s]}",
                partial(_sort, app, s),
                note="current" if st.sort == s else "",
            )
            for s in views.SORTS
        ]
        for g, word in (("source", "source"), ("type", "scope")):
            note = "current" if st.group_by == g else ""
            out.append(Entry(f"Group by {word}", partial(app.set_state, group_by=g), note=note))
        toggles = (
            ("row_detail", "Show descriptions in the list", "Hide descriptions in the list"),
            ("show_project", "Show project skills", "Hide project skills"),
            ("show_stale", "Show old plugin versions", "Hide old plugin versions"),
            ("key_hints", "Show keyboard hints", "Hide keyboard hints"),
        )
        for name, show, hide in toggles:
            value = getattr(st, name)
            out.append(Entry(hide if value else show, partial(_flip, app, name)))
        for p in theme.PALETTES:
            note = "current" if st.palette == p else ""
            title = f"Use the {p.capitalize()} palette"
            out.append(Entry(title, partial(app.set_state, palette=p), note=note))
        for m in theme.MODES:
            note = "current" if st.mode == m else ""
            out.append(Entry(f"Use {m} mode", partial(app.set_state, mode=m), note=note))
        for level in MOTIONS:
            note = "current" if st.motion == level else ""
            title = "Turn off motion" if level == "off" else f"Use {level} motion"
            out.append(Entry(title, partial(app.set_state, motion=level), note=note))
        return out

    def _skills(self, app: AtlasApp) -> Iterator[Entry]:
        ins = app.data.insights
        if ins is None:
            return
        for s in ins.skills:
            title = f"Go to /{s.get('invoke') or s['name']}"
            yield Entry(title, partial(go_to, app, s["path"]), note=views.group_label(ins, s))

    def _display_of(self, c: Entry, title: Content) -> Content:
        parts: list[Any] = [(c.key.ljust(PALETTE_KEYW), "$atlas-muted"), title]
        if c.note:
            parts += [(" · ", "$atlas-faint"), (c.note, "$atlas-muted")]
        return Content.assemble(*parts)

    async def discover(self) -> Hits:
        for c in self.commands():
            yield DiscoveryHit(self._display_of(c, Content(c.title)), c.run, text=c.title)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        app = self._app()
        for c in [*self.commands(), *self._skills(app)]:
            score = matcher.match(c.title)
            if score > 0:
                shown = self._display_of(c, matcher.highlight(c.title))
                yield Hit(score, shown, c.run, text=c.title)


def _sort(app: AtlasApp, sort: str) -> None:
    app.set_state(sort=sort)
    toast(app, f"Sorted by {SORT_WORDS[sort]}.")


def _flip(app: AtlasApp, name: str) -> None:
    app.set_state(**{name: not getattr(app.state, name)})


def go_to(app: AtlasApp, path: str) -> None:
    """Select a skill and open its details. Change the harness, view, or search to show it."""
    ins = app.data.insights
    s = app.data.skill(path)
    if ins is None or s is None:
        return
    st = app.state
    changes: dict[str, Any] = {}
    if s.get("scope") == "project":
        if not st.show_project:
            changes["show_project"] = True
    elif not views.loads(st.harness or "all", s):
        choices = views.harness_choices(ins)
        changes["harness"] = next((h for h in s.get("harnesses") or [] if h in choices), "all")
    if s.get("status") == "stale" and not st.show_stale:
        changes["show_stale"] = True
    vs = st.view_state()
    for k in ("harness", "show_project", "show_stale"):
        if k in changes:
            setattr(vs, k, changes[k])
    if not views.visible(ins, vs, s):
        changes.update(view="all", query="")
    gid = views.group_key(ins, s)
    if gid in st.collapsed:
        changes["collapsed"] = st.collapsed - {gid}
    if changes:
        app.set_state(**changes)
    app.post_message(SkillSelected(path, open=True))
