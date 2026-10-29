"""Actions that write: switches, update and install jobs, delete, undo, copy, and their toasts.

Each public function returns at once. Writes and jobs run in workers; the screen changes first.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from rich.cells import cell_len, set_cell_size
from rich.style import Style
from rich.text import Text

from ..core import views
from .messages import DataChanged, JobChanged
from .widgets import toast as toasts
from .widgets.progress import VERBS
from .widgets.progress import headline as _headline

if TYPE_CHECKING:
    from .app import AtlasApp

POLL = 0.25
MISSES = 20
HOLD = 0.9
TICKS = 2.0
CONFIRM = 4.0
UNDO_DEPTH = 20
COPY_CELLS = 48
GONE = "that job is gone"
READ_ONLY = "This build is read-only. Run atlas to change skills."
BOLD = Style(bold=True)
_MISSING = object()


@dataclass(eq=False)
class UndoEntry:
    """One change that `z` can take back. Only the last delete can be undone, as in the core."""

    label: str
    callback: Callable[[], Any]
    kind: str = ""


@dataclass(eq=False)
class _Job:
    kind: str
    names: list[str]
    repo: str = ""
    note: str = ""
    view: dict = field(default_factory=dict)


@dataclass
class _Jobs:
    job: _Job | None = None
    done: set[str] = field(default_factory=set)
    failed: dict[str, str] = field(default_factory=dict)
    flashes: dict[str, float] = field(default_factory=dict)
    confirm: str | None = None
    confirm_toast: toasts.AtlasToast | None = None
    undo: list[UndoEntry] = field(default_factory=list)
    lock: asyncio.Lock | None = None
    pending: int = 0
    dirty: bool = False


_STATE: WeakKeyDictionary[AtlasApp, _Jobs] = WeakKeyDictionary()


def _of(app: AtlasApp) -> _Jobs:
    jobs = _STATE.get(app)
    if jobs is None:
        jobs = _STATE[app] = _Jobs()
    return jobs


def _plain(text: str) -> str:
    return text.replace("`", "").strip().rstrip(".")


def _msg(app: AtlasApp, e: BaseException) -> str:
    if isinstance(e, (KeyError, TypeError, AttributeError)):
        app.log.error(repr(e))
        what = e.args[0] if isinstance(e, KeyError) and e.args else None
        return (
            f"something in the request was missing ({what})"
            if what
            else ("something in the request was wrong")
        )
    return _plain(str(e) or type(e).__name__)


def _again(kind: str) -> str:
    return f"Check your network, then press {'u' if kind == 'update' else 'i'} again."


def _target(app: AtlasApp) -> tuple[str | None, str]:
    """(skill path, item key) that a key acts on: the selection, else the list's cursor row."""
    path, key = app.current()
    return path, key or ""


def _harness_name(app: AtlasApp, harness: str | None = None) -> str:
    h = app.data.harnesses.get(harness or app.state.harness) or {}
    return h.get("name") or "agent"


def _restart(app: AtlasApp, harness: str | None = None) -> str:
    return f"Restart {_harness_name(app, harness)} sessions to pick it up."


def _over_ssh() -> bool:
    return bool(os.environ.get("SSH_TTY"))


def _changed(app: AtlasApp) -> None:
    if app.data.scan is not None:
        app.data.put("scan", app.data.scan)
    app.broadcast(lambda: DataChanged(frozenset({"scan"})))


def _changed_after_paint(app: AtlasApp) -> None:
    """Repaint the rows on screen now; rebuild Insights, the list, and counts after that frame."""
    from .widgets.skill_list import SkillList

    lists = app.main.query(SkillList)
    if not lists:
        _changed(app)
        return
    lst = lists.first()
    lst.refresh_visible()
    jobs = _of(app)
    if not jobs.dirty:
        jobs.dirty = True
        # A widget's call_after_refresh waits for its screen's next paint; the app's does not.
        lst.call_after_refresh(_flush, app)


def _flush(app: AtlasApp) -> None:
    _of(app).dirty = False
    _changed(app)


def _job_changed(app: AtlasApp) -> None:
    view = current(app)
    app.broadcast(lambda: JobChanged(view))


def _spawn(app: AtlasApp, work: Awaitable[Any], group: str) -> None:
    app.run_worker(work, group=group)


def _later(app: AtlasApp, seconds: float, fn: Callable[[], None]) -> None:
    app.set_timer(seconds, fn)


# Reads for other widgets


def current(app: AtlasApp) -> dict | None:
    """The job view while a job runs and while its bar holds full; None after."""
    job = _of(app).job
    return job.view if job else None


def running(app: AtlasApp) -> bool:
    job = _of(app).job
    return job is not None and not job.view.get("done")


def state_of(app: AtlasApp, name: str | None) -> str | None:
    """A row's job state by lock name: queued, downloading, installing, done, failed, or None."""
    if not name:
        return None
    jobs = _of(app)
    if jobs.job is not None:
        item = (jobs.job.view.get("items") or {}).get(name)
        if item:
            return item.get("state")
    if name in jobs.done:
        return "done"
    return "failed" if name in jobs.failed else None


def error_of(app: AtlasApp, name: str | None) -> str | None:
    """Why the last job failed for this name, or None."""
    jobs = _of(app)
    if jobs.job is not None and name:
        item = (jobs.job.view.get("items") or {}).get(name) or {}
        if item.get("state") == "failed":
            return _plain(item.get("error") or "")
    return jobs.failed.get(name or "")


def headline(app: AtlasApp) -> str | None:
    """`Updating 3 of 8…` or `Updated 7 of 8` for the header, while a job shows."""
    view = current(app)
    return _headline(view) if view else None


def confirming(app: AtlasApp) -> str | None:
    """The lock name that waits for a second `u` to replace local edits."""
    return _of(app).confirm


def flashes(app: AtlasApp) -> dict[str, float]:
    """Names to flash, by `time.monotonic()` start: restored by undo, or just updated."""
    return _of(app).flashes


def escape(app: AtlasApp) -> bool:
    """Cancel a pending `Replace my edits`. True when esc had that to do."""
    if _of(app).confirm is None:
        return False
    _end_confirm(app)
    return True


# Toasts and undo


def toast(
    app: AtlasApp,
    text: str | Text,
    *,
    severity: toasts.Severity = "information",
    action: toasts.Action | None = None,
) -> toasts.AtlasToast:
    """Show one toast. A str is plain text; pass a Text to make a name bold."""
    return toasts.toast(app, text, severity=severity, action=action)


def push_undo(app: AtlasApp, label: str, callback: Callable[[], Any]) -> UndoEntry:
    """Put a change on the undo stack; `z` runs the newest. The callback may be async."""
    return _push(app, UndoEntry(label, callback))


def _push(app: AtlasApp, entry: UndoEntry) -> UndoEntry:
    stack = _of(app).undo
    if entry.kind == "delete":
        stack[:] = [e for e in stack if e.kind != "delete"]
    stack.append(entry)
    del stack[:-UNDO_DEPTH]
    return entry


def undo_action(app: AtlasApp, entry: UndoEntry) -> toasts.Action:
    """The `z Undo` action for a toast; a click runs this entry once."""
    return ("z", "Undo", lambda: _run_undo(app, entry))


def undo(app: AtlasApp) -> None:
    """`z`: take back the newest change. Nothing happens when there is none."""
    stack = _of(app).undo
    if stack:
        _run_undo(app, stack[-1])


def _run_undo(app: AtlasApp, entry: UndoEntry) -> None:
    stack = _of(app).undo
    if entry not in stack:
        return
    stack.remove(entry)
    toasts.dismiss(app)
    result = entry.callback()
    if inspect.isawaitable(result):
        _spawn(app, result, "atlas-write")


# Switches


def _apply(app: AtlasApp, harness: str, kind: str, names: list[str], on: bool) -> dict:
    """Change the loaded settings the way the core writes them. Returns the old values."""
    scan = app.data.scan or {}
    h = (scan.get("harnesses") or {}).get(harness) or {}
    settings = scan.setdefault("settings", {}).setdefault(harness, {})
    before: dict[str, object] = {}
    if h.get("switch") == "claude":
        section = settings.setdefault("skillOverrides" if kind == "skill" else "enabledPlugins", {})
        for n in names:
            before[n] = section.get(n, _MISSING)
            if kind == "plugin":
                section[n] = on
            elif on:
                section.pop(n, None)
            else:
                section[n] = "off"
        return before
    off = settings.setdefault("off", [])
    for n in names:
        before[n] = n in off
        if on and n in off:
            off.remove(n)
        elif not on and n not in off:
            off.append(n)
    return before


def _restore(app: AtlasApp, harness: str, kind: str, before: dict) -> None:
    scan = app.data.scan or {}
    h = (scan.get("harnesses") or {}).get(harness) or {}
    settings = scan.setdefault("settings", {}).setdefault(harness, {})
    if h.get("switch") == "claude":
        section = settings.setdefault("skillOverrides" if kind == "skill" else "enabledPlugins", {})
        for n, value in before.items():
            if value is _MISSING:
                section.pop(n, None)
            else:
                section[n] = value
        return
    off = settings.setdefault("off", [])
    for n, was_off in before.items():
        if was_off and n not in off:
            off.append(n)
        elif not was_off and n in off:
            off.remove(n)


def _lock(jobs: _Jobs) -> asyncio.Lock:
    if jobs.lock is None:
        jobs.lock = asyncio.Lock()
    return jobs.lock


Change = tuple[str, str, list[str]]


def _switch(app: AtlasApp, changes: Iterable[Change], on: bool, message: Text | None) -> None:
    """Flip (harness, kind, names) switches now, then write them in order.

    message None means no toast and no undo entry.
    """
    todo = [(h, kind, list(names)) for h, kind, names in changes if names]
    if not todo or app.data.scan is None:
        return
    befores = [_apply(app, h, kind, names, on) for h, kind, names in todo]
    _changed_after_paint(app)
    _spawn(app, _write(app, todo, befores, on, message), "atlas-write")


async def _write(
    app: AtlasApp, todo: list[Change], befores: list[dict], on: bool, message: Text | None
) -> None:
    jobs = _of(app)
    jobs.pending += 1
    results: dict[str, Any] = {}
    error: tuple[int, Exception] | None = None
    try:
        async with _lock(jobs):
            for i, (h, kind, names) in enumerate(todo):
                try:
                    results[h] = await app.fetch(app.atlas.toggle, h, kind, names, on)
                except Exception as e:
                    error = (i, e)
                    break
    finally:
        jobs.pending -= 1
    scan = app.data.scan
    if error is not None:
        first, why = error
        for (h, kind, _), before in zip(todo[first:], befores[first:], strict=True):
            _restore(app, h, kind, before)
        _changed_after_paint(app)
        fix = "Check the file's permissions, then try again."
        toast(app, f"Could not save: {_msg(app, why)}. {fix}", severity="error")
        return
    if jobs.pending == 0 and scan is not None:
        settings = scan.setdefault("settings", {})
        fresh = {h: r for h, r in results.items() if isinstance(r, dict) and settings.get(h) != r}
        if fresh:
            settings.update(fresh)
            _changed_after_paint(app)
    if message is None:
        return
    entry = _push(app, UndoEntry(message.plain, lambda: _switch(app, todo, not on, None)))
    toast(app, message, action=undo_action(app, entry))


def _turned(what: str, on: bool, tail: str) -> Text:
    return Text.assemble("Turned ", (what, BOLD), f" {'on' if on else 'off'}{tail}")


def _what(kind: str, names: list[str]) -> str:
    if len(names) == 1:
        return f"plugin {names[0].split('@')[0]}" if kind == "plugin" else names[0]
    return views.plural(len(names), kind)


def set_switch(
    app: AtlasApp, harness: str | Sequence[str], names: list[str], on: bool, kind: str = "skill"
) -> None:
    """Turn skills (by name) or plugins (by ref) on or off in one or more harnesses.

    One toast and one undo entry cover every harness.
    """
    hs = [harness] if isinstance(harness, str) else list(dict.fromkeys(harness))
    names = list(dict.fromkeys(names))
    if not names or not hs:
        return
    if len(hs) == 1:
        tail = f". {_restart(app, hs[0])}"
    else:
        tail = f" in {len(hs)} harnesses. Restart agent sessions to pick it up."
    message = _turned(_what(kind, names), on, tail)
    _switch(app, [(h, kind, names) for h in hs], on, message)


def _writable(app: AtlasApp) -> views.Insights | None:
    ins = app.data.insights
    if ins is not None and not ins.writable:
        toast(app, READ_ONLY)
        return None
    return ins


def _can_switch(app: AtlasApp, ins: views.Insights) -> bool:
    harness = app.state.harness
    if harness in ("", "all"):
        toast(app, "Pick a harness to switch skills. Press [ or ] to change it.")
        return False
    if not views.switchable(ins, harness):
        toast(app, f"{_harness_name(app)} has no per-skill switch.")
        return False
    return True


def _no_switch(mode: str) -> str:
    if mode == "project only":
        return "Project skills load only inside their project, so they have no switch."
    if mode == "old version":
        return "Old version. Claude Code no longer loads this copy."
    return "This skill has no switch in this harness."


def toggle(app: AtlasApp) -> None:
    """`x` and `space`: the marks, the selected group, or the selected skill, on or off."""
    ins = _writable(app)
    if ins is None:
        return
    st = app.state
    if st.marked:
        _toggle_marks(app, ins)
        return
    path, key = _target(app)
    if key.startswith(("src:", "plg:", "prj:")):
        _toggle_group(app, ins, key)
        return
    s = app.data.skill(path)
    if s is None or not _can_switch(app, ins):
        return
    sw = views.switch_state(ins, st.harness, s)
    if not sw["toggle"]:
        toast(app, _no_switch(sw["mode"]))
        return
    set_switch(app, st.harness, [sw["key"]], not sw["on"], sw["toggle"])


def _toggle_group(app: AtlasApp, ins: views.Insights, key: str) -> None:
    if key.startswith("prj:"):
        toast(app, _no_switch("project only"))
        return
    if not _can_switch(app, ins):
        return
    harness = app.state.harness
    members = views.members_of(ins, harness, key)
    if not members:
        return
    if key.startswith("plg:"):
        sw = views.switch_state(ins, harness, members[0])
        if sw["toggle"] != "plugin":
            toast(app, _no_switch(sw["mode"]))
            return
        set_switch(app, harness, [sw["key"]], not sw["on"], "plugin")
        return
    lit = [views.switch_state(ins, harness, s) for s in members]
    on = not all(sw["on"] for sw in lit)
    changed = [sw["key"] for sw in lit if sw["on"] != on and sw["toggle"] == "skill"]
    what = f"{views.plural(len(changed), 'skill')} from {key[4:]}"
    _switch(app, [(harness, "skill", changed)], on, _turned(what, on, f". {_restart(app)}"))


def _marked(app: AtlasApp, ins: views.Insights) -> list[dict]:
    return [s for s in ins.skills if s["path"] in app.state.marked]


def switch_marks(app: AtlasApp, on: bool | None = None) -> None:
    """Turn the marked skills and plugins on or off. None picks the side most of them need."""
    ins = _writable(app)
    if ins is not None:
        _toggle_marks(app, ins, on)


def _toggle_marks(app: AtlasApp, ins: views.Insights, on: bool | None = None) -> None:
    if not _can_switch(app, ins):
        return
    plan = views.bulk_plan(ins, app.state.harness, _marked(app, ins))
    count = {side: len(plan[side]["skills"]) + len(plan[side]["plugins"]) for side in ("on", "off")}
    if on is None:
        if not count["on"] and not count["off"]:
            toast(app, f"No marked skill has a switch in {_harness_name(app)}.")
            return
        on = count["on"] >= count["off"] and count["on"] > 0
    side = plan["on" if on else "off"]
    names = [s["name"] for s in side["skills"]]
    refs = list(side["plugins"])
    if not names and not refs:
        return
    what = " and ".join(
        views.plural(len(x), word) for x, word in ((names, "skill"), (refs, "plugin")) if x
    )
    message = _turned(what, on, f". {_restart(app)}")
    harness = app.state.harness
    _switch(app, [(harness, "skill", names), (harness, "plugin", refs)], on, message)


# Update and install jobs


def update(app: AtlasApp, names: list[str] | None = None, *, confirmed: bool = False) -> None:
    """`u`: update the marks, the selected group, or the selected skill. names are lock names.

    confirmed: the user already agreed to replace local edits, so do not ask again."""
    ins = _writable(app)
    if ins is None:
        return
    st = app.state
    if names is not None:
        if len(names) == 1:
            _update_one(app, ins, names[0], confirmed)
        else:
            wanted = set(names)
            members = [s for s in ins.skills if views.lock_name(s) in wanted]
            _update_batch(app, ins, members, confirmed)
        return
    if st.marked:
        _update_batch(app, ins, views.bulk_plan(ins, st.harness, _marked(app, ins))["update"])
        return
    path, key = _target(app)
    if key.startswith("src:"):
        source = key[4:]
        members = [
            s for s in ins.skills if views.live(st.harness, s) and views.source_of(ins, s) == source
        ]
        _update_batch(app, ins, members)
        return
    s = app.data.skill(path)
    if s is None:
        return
    name = views.lock_name(s)
    if name is None:
        toast(app, f"/{s['name']} is not linked to a GitHub repo, so it has no updates.")
        return
    _update_one(app, ins, name, confirmed)


def update_all(app: AtlasApp) -> None:
    """`shift+u`: update each outdated skill in this harness, except ones with local edits."""
    ins = _writable(app)
    if ins is not None:
        _update_batch(app, ins, [s for s in ins.skills if views.live(app.state.harness, s)])


def _update_one(app: AtlasApp, ins: views.Insights, name: str, confirmed: bool = False) -> None:
    if running(app):
        toast(app, "An update is already running.")
        return
    s = next((x for x in ins.skills if views.lock_name(x) == name), None)
    if s is None:
        return
    if not views.is_outdated(ins, s) and state_of(app, name) != "failed":
        toast(app, f"/{s['name']} is up to date.")
        return
    if s.get("local_edits") and not confirmed and _of(app).confirm != name:
        _ask_confirm(app, name)
        return
    _end_confirm(app)
    _start(app, "update", [name], lambda: app.atlas.update([name]))


def _ask_confirm(app: AtlasApp, name: str) -> None:
    jobs = _of(app)
    _end_confirm(app)
    text = Text.assemble((f"/{name}", BOLD), " has changes you made. An update replaces them.")
    jobs.confirm_toast = toasts.toast(
        app,
        text,
        severity="warning",
        action=("u", "Replace my edits", lambda: _confirmed(app, name)),
        seconds=CONFIRM,
        on_close=lambda: _end_confirm(app, name),
    )
    jobs.confirm = name
    _job_changed(app)


def _confirmed(app: AtlasApp, name: str) -> None:
    ins = app.data.insights
    if ins is not None:
        _update_one(app, ins, name, confirmed=True)


def _end_confirm(app: AtlasApp, name: str | None = None) -> None:
    jobs = _of(app)
    if jobs.confirm is None or (name is not None and jobs.confirm != name):
        return
    jobs.confirm = None
    shown, jobs.confirm_toast = jobs.confirm_toast, None
    if shown is not None:
        shown.close()
    _job_changed(app)


def _update_batch(
    app: AtlasApp, ins: views.Insights, skills: list[dict], confirmed: bool = False
) -> None:
    if running(app):
        toast(app, "An update is already running.")
        return
    out = [s for s in skills if views.is_outdated(ins, s)]
    safe = out if confirmed else [s for s in out if not s.get("local_edits")]
    skipped = len(out) - len(safe)
    if not safe:
        text = "Everything is up to date."
        if skipped:
            text = f"All {skipped} have your edits. Update them one at a time."
        toast(app, text)
        return
    note = f" Skipped {skipped} you edited; update those one at a time." if skipped else ""
    names = [n for s in safe if (n := views.lock_name(s))]
    _start(app, "update", names, lambda: app.atlas.update(names), note=note)


def _repo_of_selection(app: AtlasApp) -> str | None:
    path, key = _target(app)
    if key.startswith("src:"):
        return key[4:]
    if key.startswith("a:"):
        return key[2:].partition(":")[0]
    s = app.data.skill(path)
    return views.repo_of(s) if s else None


def install(app: AtlasApp, repo: str | None = None, paths: list[str] | None = None) -> None:
    """`i`: install the selected available skill, or the given paths from repo (None: all)."""
    if _writable(app) is None:
        return
    if repo is None:
        key = _target(app)[1]
        if key.startswith("src:"):
            install_new(app)
            return
        if not key.startswith("a:"):
            return
        repo, _, path = key[2:].partition(":")
        paths = [path]
    offered = app.data.available.get(repo) or []
    chosen = [a for a in offered if paths is None or a.get("path") in paths]
    _install_from(app, repo, chosen)


def install_new(app: AtlasApp) -> None:
    """`shift+i`: install the new skills from the selected source."""
    ins = _writable(app)
    repo = _repo_of_selection(app)
    if ins is None or not repo:
        return
    fresh = views.new_in(ins, repo)
    if not fresh:
        toast(app, f"No new skills from {repo}.")
        return
    _install_from(app, repo, fresh)


def _install_from(app: AtlasApp, repo: str, items: list[dict]) -> None:
    if running(app):
        toast(app, "Another job is still running.")
        return
    ok = [a for a in items if not a.get("taken")]
    if not ok:
        if items and items[0].get("taken") == "moved":
            toast(app, "This repo moved the folder of a skill you have. Update or relink it.")
        elif items:
            toast(app, f"A skill named {items[0].get('name')} is already installed.")
        return
    paths = [a["path"] for a in ok]
    names = [a["name"] for a in ok]
    _start(app, "install", names, lambda: app.atlas.install(repo, paths), repo=repo)


def _start(
    app: AtlasApp,
    kind: str,
    names: list[str],
    start: Callable[[], dict],
    *,
    note: str = "",
    repo: str = "",
) -> None:
    jobs = _of(app)
    if not names:
        return
    job = _Job(kind, names, repo, note)
    job.view = {"items": {n: {"state": "queued"} for n in names}, "done": False, "kind": kind}
    jobs.job = job
    jobs.done.clear()
    jobs.failed.clear()
    _job_changed(app)
    _spawn(app, _run(app, job, start), "atlas-job")


def follow(
    app: AtlasApp, job_view: dict, note: str = "", *, kind: str = "install", repo: str = ""
) -> None:
    """Track a job the core already started, such as an import: bar, rows, and the end toast."""
    view = dict(job_view)
    _start(app, kind, list(view.get("items") or {}), lambda: view, note=note, repo=repo)


def _gone(view: dict, error: str) -> dict:
    items = {
        n: {"state": "failed", "error": error} if i.get("state") in views.RUNNING else i
        for n, i in (view.get("items") or {}).items()
    }
    return {**view, "items": items, "done": True, "seconds": 0}


async def _run(app: AtlasApp, job: _Job, start: Callable[[], dict]) -> None:
    jobs = _of(app)
    try:
        view = await app.fetch(start)
    except Exception as e:
        if jobs.job is job:
            jobs.job = None
            _job_changed(app)
        toast(app, f"Could not start: {_msg(app, e)}. {_again(job.kind)}", severity="error")
        return
    job.view = {**view, "kind": job.kind}
    _job_changed(app)
    misses = 0
    while not job.view.get("done"):
        await asyncio.sleep(POLL)
        try:
            new = await app.fetch(app.atlas.job, view["id"])
        except Exception as e:
            misses += 1
            if misses < MISSES:
                continue
            new = _gone(job.view, _msg(app, e))
        else:
            misses = 0
            if new is None:
                new = _gone(job.view, GONE)
        moved = new.get("items") != job.view.get("items") or new.get("done")
        job.view = {**new, "kind": job.kind}
        if moved and jobs.job is job:
            _job_changed(app)
    _finish(app, job)


def _finish(app: AtlasApp, job: _Job) -> None:
    jobs = _of(app)
    items = job.view.get("items") or {}
    failed = {
        n: _plain(i.get("error") or "") or "unknown error"
        for n, i in items.items()
        if i["state"] == "failed"
    }
    jobs.failed = dict(failed)
    app.reload(["scan", "updates"])
    ed = VERBS[job.kind][1]
    ok = len(items) - len(failed)
    if failed:
        key = "u" if job.kind == "update" else "i"
        first = next(iter(failed.values()))
        text = Text.assemble(
            f"{ed} {ok}, ",
            (f"{len(failed)} failed", BOLD),
            f": {first}. Press {key} on the row to try again.",
        )
        toast(app, text, severity="error")
    else:
        who = job.names[0] if ok == 1 else views.plural(ok, "skill")
        where = f" from {job.repo}" if job.kind == "install" and job.repo else ""
        secs = f"{float(job.view.get('seconds') or 0):g}"
        tail = f"{where} in {secs}s.{job.note} {_restart(app)}"
        toast(app, Text.assemble(f"{ed} ", (who, BOLD), tail))
    _later(app, HOLD, lambda: _fade(app, job))


def _fade(app: AtlasApp, job: _Job) -> None:
    jobs = _of(app)
    if jobs.job is not job:
        return
    items = job.view.get("items") or {}
    done = {n for n, i in items.items() if i.get("state") == "done"}
    jobs.job = None
    jobs.done = set(done)
    _job_changed(app)
    _later(app, TICKS - HOLD, lambda: _drop_ticks(app, done))


def _drop_ticks(app: AtlasApp, names: set[str]) -> None:
    jobs = _of(app)
    if jobs.job is not None or not names & jobs.done:
        return
    now = time.monotonic()
    for n in names & jobs.done:
        jobs.flashes[n] = now
    jobs.done -= names
    _job_changed(app)


def check_again(app: AtlasApp) -> None:
    """Ask each source for new versions now. Ignored while a check runs."""
    if "updates" not in app.data.loading:
        app.reload(["updates"], refresh=True)


# Delete


def delete(app: AtlasApp, names: list[str]) -> None:
    """Move store skills to the Trash, by folder name, after the confirm. `z` puts them back."""
    names = list(dict.fromkeys(names))
    if names and _writable(app) is not None:
        _spawn(app, _delete(app, names), "atlas-write")


async def _delete(app: AtlasApp, names: list[str]) -> None:
    try:
        await app.fetch(app.atlas.delete, names)
    except Exception as e:
        fix = "Check the folder's permissions, then press delete again."
        toast(app, f"Could not delete: {_msg(app, e)}. {fix}", severity="error")
        return
    ins = app.data.insights
    gone = {
        s["path"]
        for s in (ins.skills if ins else [])
        if s.get("dir_name") in names and s.get("store")
    }
    changes: dict[str, Any] = {}
    if app.state.selected in gone:
        changes["selected"] = None
    if app.state.marked & gone:
        changes["marked"] = app.state.marked - gone
    if changes:
        app.set_state(**changes)
    app.reload(["scan"])
    who = names[0] if len(names) == 1 else views.plural(len(names), "skill")
    entry = _push(app, UndoEntry(f"Moved {who} to the Trash.", lambda: _undelete(app), "delete"))
    toast(
        app, Text.assemble("Moved ", (who, BOLD), " to the Trash."), action=undo_action(app, entry)
    )


async def _undelete(app: AtlasApp) -> None:
    try:
        result = await app.fetch(app.atlas.undo_delete)
    except Exception as e:
        fix = "The skill is in the Trash. Move it back from there."
        toast(app, f"Could not undo: {_msg(app, e)}. {fix}", severity="error")
        return
    restored = list(result.get("restored") or [])
    now = time.monotonic()
    for n in restored:
        _of(app).flashes[n] = now
    app.reload(["scan"])
    toast(app, f"Put back {views.plural(len(restored), 'skill')}.")


# Clipboard, file manager, and browser


def _cut(text: str, cells: int) -> str:
    return text if cell_len(text) <= cells else set_cell_size(text, cells - 1) + "…"


def _local_mac() -> bool:
    return sys.platform == "darwin" and not _over_ssh() and shutil.which("pbcopy") is not None


def _pbcopy(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True, check=True, timeout=5, capture_output=True)


def copy(app: AtlasApp, text: str, what: str) -> None:
    """Copy text: OSC 52 always, and pbcopy on a local Mac. what names it: `/ads`, `the path`."""
    app.copy_to_clipboard(text)
    if _local_mac():
        _spawn(app, _copy_local(app, text, what), "atlas-copy")
    else:
        toast(app, f"Sent {what} to your terminal's clipboard.")


async def _copy_local(app: AtlasApp, text: str, what: str) -> None:
    try:
        await app.fetch(_pbcopy, text)
    except Exception as e:
        toast(app, f"Could not copy: {_msg(app, e)}.", severity="error")
        return
    shown = what if text == what or "\n" in text else f"{what}: {text}"
    toast(app, _cut(f"Copied {shown}", COPY_CELLS))


def copy_prompt(app: AtlasApp, names: list[str] | None = None) -> None:
    """Copy `/name /name` for the marks, the given folder names, or the selected skill."""
    ins = app.data.insights
    if ins is None:
        return
    if names is not None:
        by_dir = {s.get("dir_name") or s["name"]: s for s in reversed(ins.skills)}
        skills = [by_dir[n] for n in names if n in by_dir]
    elif app.state.marked:
        skills = _marked(app, ins)
    else:
        s = app.data.skill(_target(app)[0])
        skills = [s] if s else []
    if not skills:
        return
    text = " ".join(f"/{s.get('invoke') or s['name']}" for s in skills)
    copy(app, text, text if len(skills) == 1 else views.plural(len(skills), "skill"))


def reveal(app: AtlasApp, path: str | None = None) -> None:
    """Show the skill's folder in the file manager. Over SSH, say why it cannot."""
    path = path or _target(app)[0]
    if not path:
        return
    if _over_ssh():
        toast(app, "Reveal does not work over SSH: the folder is on the remote machine.")
        return
    if _writable(app) is not None:
        _spawn(app, _reveal(app, path), "atlas-write")


async def _reveal(app: AtlasApp, path: str) -> None:
    try:
        await app.fetch(app.atlas.reveal, path)
    except Exception as e:
        fix = "Check that the folder is still there, then press R again."
        toast(app, f"Could not reveal: {_msg(app, e)}. {fix}", severity="error")


def github_url(s: dict) -> str:
    """The GitHub page of a skill record: its marketplace or source URL, as the web links it."""
    ms, o = s.get("marketplace_source") or {}, s.get("origin") or {}
    src = str(ms.get("url") or ms.get("repo") or o.get("sourceUrl") or o.get("source") or "")
    return src.removesuffix(".git") if src.startswith(("http://", "https://")) else ""


def _selection_url(app: AtlasApp) -> str:
    ins = app.data.insights
    path, key = _target(app)
    if ins is not None and key.startswith(("src:", "plg:", "prj:")):
        repo = views.group_for(ins, key).get("repo")
        return f"https://github.com/{repo}" if repo else ""
    if key.startswith("a:"):
        repo, _, sub = key[2:].partition(":")
        return f"https://github.com/{repo}/tree/HEAD/{sub.removesuffix('SKILL.md').rstrip('/')}"
    s = app.data.skill(path)
    return github_url(s) if s else ""


def _link_text(lead: str, url: str) -> Text:
    return Text.assemble(lead, (url, Style(link=url, underline=True)))


def open_github(app: AtlasApp, url: str | None = None) -> None:
    """Open the GitHub page in the browser. Over SSH, send the link to the clipboard instead."""
    url = url or _selection_url(app)
    if not url:
        toast(app, "This item has no GitHub page.")
        return
    if _over_ssh():
        app.copy_to_clipboard(url)
        toast(app, _link_text("Sent the GitHub link to your terminal's clipboard: ", url))
        return
    _spawn(app, _open(app, url), "atlas-copy")


async def _open(app: AtlasApp, url: str) -> None:
    try:
        opened = await app.fetch(webbrowser.open, url)
    except Exception:
        opened = False
    if opened:
        return
    app.copy_to_clipboard(url)
    lead = "Could not open a browser. Sent the link to your terminal's clipboard: "
    if _local_mac():
        try:
            await app.fetch(_pbcopy, url)
            lead = "Could not open a browser. Copied the link: "
        except Exception as e:
            app.log.error(repr(e))
    toast(app, _link_text(lead, url))
