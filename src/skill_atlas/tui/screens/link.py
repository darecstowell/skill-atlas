"""Link store skills to a GitHub repo, and watch a repo for new skills."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.widgets import Input, Static

from ...core import views
from ...updates import parse_repo
from ..messages import DataChanged, ItemSelected
from . import HintButton
from .confirm import (
    Dialog,
    Field,
    marked_skills,
    plural,
    reason,
    said,
    sentence,
    toast,
    writable,
)

if TYPE_CHECKING:
    from ..app import AtlasApp


def repo_problem(text: str) -> str | None:
    """Why the text is not a GitHub repo, with the fix; None when it is one."""
    text = text.strip()
    if not text:
        return "Type a repo as owner/repo, or paste its GitHub URL."
    try:
        parse_repo(text)
    except ValueError:
        return f"“{text}” is not a GitHub repo. Type it as owner/repo, or paste its GitHub URL."
    return None


class RepoDialog(Dialog[None]):
    """One `GitHub repo` field. The repo is checked when the user submits, then on each change."""

    AUTO_FOCUS = "Input"
    PLACEHOLDER = "owner/repo"
    VERB = ""
    BUSY = ""

    def __init__(self) -> None:
        super().__init__()
        self.field = Field("GitHub repo", placeholder=self.PLACEHOLDER)
        self.verb = self.VERB

    def lead(self) -> str:
        return ""

    def body(self) -> ComposeResult:
        yield Static(self.lead(), classes="lead")
        yield self.field

    def buttons(self) -> ComposeResult:
        yield HintButton("esc", "Cancel", "close", id="cancel")
        yield Static(classes="gap")
        yield HintButton("enter", self.verb, "go", variant="primary", busy_label=self.BUSY, id="go")

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.field.failed:
            problem = repo_problem(event.value)
            if problem:
                self.field.show_error(problem)
            else:
                self.field.clear()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_go()

    def action_go(self) -> None:
        text = self.field.value.strip()
        problem = repo_problem(text)
        if problem:
            self.field.show_error(problem)
            return
        self.submit(lambda: self.run(text))

    async def run(self, text: str) -> None:
        raise NotImplementedError

    def failed(self, message: str) -> None:
        if self.alive:
            self.field.show_error(message)
        else:
            toast(self.atlas_app, message, severity="error")


class LinkDialog(RepoDialog):
    """Link skills to the repo that holds a folder of the same name, so updates can be checked."""

    VERB = "Link"
    BUSY = "Linking…"

    def __init__(self, names: list[str], *, group: bool = False) -> None:
        super().__init__()
        self.names = names
        self.group = group
        self.verb = "Link" if len(names) == 1 or group else f"Link {len(names)}"

    def heading(self) -> str:
        if len(self.names) == 1 and not self.group:
            return f"Link /{self.names[0]} to GitHub"
        return f"Link {plural(len(self.names), 'skill')} to GitHub"

    def lead(self) -> str:
        return (
            "Skill Atlas looks in the repo for a folder with the same name as each skill. "
            "Then it can check the skill for updates."
        )

    async def run(self, text: str) -> None:
        app = self.atlas_app
        try:
            r = await app.fetch(app.atlas.link, self.names, text)
        except Exception as e:
            self.failed(sentence(reason(e)))
            return
        if not r.get("linked"):
            these = "this skill" if len(self.names) == 1 and not self.group else "these skills"
            self.failed(f"No folder in {r.get('repo') or text} has the same name as {these}.")
            return
        if self.alive:
            self.dismiss(None)
        app.reload(["scan", "updates"], refresh=True)
        missing = r.get("missing") or []
        tail = f" No folder for: {', '.join(missing)}." if missing else ""
        toast(app, said("Linked ", (str(len(r["linked"])), "bold"), f" to {r['repo']}.{tail}"))


class WatchDialog(RepoDialog):
    """Watch a repo, so its skills that you do not have show in the list."""

    PLACEHOLDER = "owner/repo or URL"
    VERB = "Watch"
    BUSY = "Watching…"

    def heading(self) -> str:
        return "Watch a GitHub repo for new skills"

    def lead(self) -> str:
        return "Skills in the repo that you do not have show under it in the list."

    async def run(self, text: str) -> None:
        app = self.atlas_app
        try:
            r = await app.fetch(app.atlas.watch, text, True)
        except Exception as e:
            self.failed(sentence(reason(e)))
            return
        repo = r["repo"]
        app.set_state(collapsed=app.state.collapsed - {f"src:{repo}"})
        n = None
        try:
            fresh = await app.fetch(lambda: app.atlas.updates(refresh=True))
        except Exception:
            app.reload(["updates"], refresh=True)
        else:
            app.data.put("updates", fresh)
            app.data.errors.pop("updates", None)
            app.broadcast(lambda: DataChanged(frozenset({"updates"})))
            n = len(app.data.available.get(repo) or [])
        if self.alive:
            self.dismiss(None)
        app.post_message(ItemSelected(f"src:{repo}"))
        tail = (
            ""
            if n is None
            else f" {plural(n, 'skill')} available."
            if n
            else " You have all its skills."
        )
        toast(app, said("Watching ", (repo, "bold"), f".{tail}"))


def link_targets(app: AtlasApp) -> tuple[list[str], bool]:
    """Folder names to link: the marks, the selected skill, or the selected local group."""
    ins = app.data.insights
    if ins is None:
        return [], False
    harness = app.state.harness or "all"
    if app.state.marked:
        return [
            s["dir_name"] for s in views.bulk_plan(ins, harness, marked_skills(app))["link"]
        ], True
    skill = app.data.skill(app.state.selected)
    if skill is not None:
        ok = skill.get("store") and not views.lock_name(skill)
        return ([skill["dir_name"]] if ok else []), False
    key = app.state.selected_key or ""
    if key.startswith("src:") and views.is_local_group(key[4:]):
        members = views.members_of(ins, harness, key)
        return [s["dir_name"] for s in members if s.get("store")], True
    return [], False


async def open_link(app: AtlasApp, names: Iterable[str] | None = None) -> None:
    """Link store skills (by folder name; default the selection or marks) to a GitHub repo."""
    if writable(app) is None:
        return
    if names is not None:
        chosen, group = list(dict.fromkeys(names)), False
    else:
        chosen, group = link_targets(app)
    if not chosen:
        toast(app, "Only skills in your skill store that have no GitHub source can be linked.")
        return
    app.push_screen(LinkDialog(chosen, group=group and len(chosen) > 1))


async def open_watch(app: AtlasApp) -> None:
    """Watch a GitHub repo for new skills (`w`)."""
    if writable(app) is not None:
        app.push_screen(WatchDialog())
