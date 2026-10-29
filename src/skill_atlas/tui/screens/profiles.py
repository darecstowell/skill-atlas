"""Profiles: the list, save, rename, delete, and apply after a preview of each change."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from rich.cells import cell_len
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static

from ...core import views
from ...profiles import MAX_NAME
from . import HintButton
from .confirm import (
    Dialog,
    Field,
    PickRow,
    fetch_slow,
    marked_skills,
    merge_settings,
    meta,
    plural,
    reason,
    said,
    sentence,
    spawn,
    toast,
    writable,
)

if TYPE_CHECKING:
    from ..app import AtlasApp

Mode = Literal["current", "selection", "rename"]
EMPTY = (
    "No profiles yet. A profile keeps which skills are on and off, "
    "so you can switch them all in one step."
)


def clean(name: str) -> str:
    return " ".join(name.split())


def label_of(app: AtlasApp, hid: str) -> str:
    h = app.data.harnesses.get(hid) or {}
    return h.get("label") or h.get("name") or hid


def where(app: AtlasApp) -> str:
    harness = app.state.harness or "all"
    return "each harness" if harness == "all" else label_of(app, harness)


def can_save(app: AtlasApp) -> bool:
    ins = app.data.insights
    harness = app.state.harness or "all"
    return harness == "all" or (ins is not None and views.switchable(ins, harness))


def no_switch(app: AtlasApp) -> str:
    return (
        f"{label_of(app, app.state.harness)} has no on/off switch for skills. "
        "Pick another harness to save a profile."
    )


def picked(app: AtlasApp, names: Iterable[str] | None = None) -> dict[str, list[str]]:
    """The skills a profile can switch: own skills by name, plugin skills by plugin."""
    ins = app.data.insights
    if ins is None or not can_save(app):
        return {"skills": [], "plugins": []}
    if names is None:
        chosen = marked_skills(app)
    else:
        want = set(names)
        chosen = [
            s
            for s in ins.skills
            if s["path"] in want
            or (s.get("scope") == "personal" and want & {s["name"], s.get("dir_name")})
            or (s.get("scope") == "plugin" and s.get("plugin_ref") in want)
        ]
    chosen = [s for s in chosen if s.get("status") != "stale"]
    return {
        "skills": list(dict.fromkeys(s["name"] for s in chosen if s.get("scope") == "personal")),
        "plugins": list(
            dict.fromkeys(s["plugin_ref"] for s in chosen if s.get("scope") == "plugin")
        ),
    }


def profile_meta(app: AtlasApp, p: dict) -> Content:
    ids = list(p.get("harnesses") or {})
    spot = label_of(app, ids[0]) if len(ids) == 1 else plural(len(ids), "harness", "harnesses")
    return meta(f"{p['on']} on", f"{p['off']} off", spot)


def refresh_lists(app: AtlasApp) -> None:
    for screen in app.screen_stack:
        if isinstance(screen, ProfilesDialog):
            screen.load()


async def delete_profile(app: AtlasApp, name: str) -> list[dict] | None:
    """Delete a profile at once; the toast and `z` put it back. Returns the new list."""
    try:
        r = await app.fetch(app.atlas.profile, "delete", {"name": name})
    except Exception as e:
        toast(app, f"Could not delete the profile: {reason(e)}", severity="error")
        return None

    async def undo() -> None:
        try:
            await app.fetch(app.atlas.profile, "restore", {"profile": r["deleted"]})
        except Exception as e:
            toast(app, f"Could not undo: {reason(e)}", severity="error")
            return
        refresh_lists(app)
        toast(app, said("Put back the profile ", (name, "bold"), "."))

    toast(
        app,
        said("Deleted the profile ", (name, "bold"), "."),
        undo=undo,
        label=f"Deleted the profile {name}.",
    )
    return r["profiles"]


# The list


class RowAction(Widget):
    """`enter Apply…` at the right of a profile row. Other rows show the word only, in the
    same cell, so nothing moves when focus moves."""

    DEFAULT_CSS = """
    RowAction { width: auto; height: 1; padding: 0 1; color: $atlas-muted; }
    ProfileRow:focus RowAction { color: $atlas-text; }
    RowAction:hover { background: $atlas-surface-3; color: $atlas-text; }
    """
    ALLOW_SELECT = False

    def __init__(self, key: str, label: str, verb: str, tip: str) -> None:
        super().__init__()
        self.key, self.label, self.verb = key, label, verb
        self.tooltip = tip

    def get_content_width(self, container: Any, viewport: Any) -> int:
        return cell_len(self.key) + 1 + cell_len(self.label)

    def get_content_height(self, container: Any, viewport: Any, width: int) -> int:
        return 1

    @property
    def row(self) -> ProfileRow:
        return next(a for a in self.ancestors if isinstance(a, ProfileRow))

    def render(self) -> Content:
        if self.row.has_focus:
            return Content.assemble((self.key, "$atlas-accent"), " ", self.label)
        return Content(" " * (cell_len(self.key) + 1) + self.label)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.row.focus()
        self.row.post_message(ProfileRow.Act(self.verb, self.row.profile["name"]))


class ProfileRow(Vertical, can_focus=True):
    """The name and the row's actions, then the counts across the full width."""

    DEFAULT_CSS = """
    ProfileRow { height: 2; }
    ProfileRow:hover { background: $atlas-surface-2; }
    ProfileRow:focus { background: $atlas-selection; }
    ProfileRow > Horizontal { height: 1; }
    ProfileRow .bar { width: 1; color: $atlas-text; visibility: hidden; }
    ProfileRow:focus .bar { visibility: visible; }
    ProfileRow .name, ProfileRow .meta {
        width: 1fr; padding-left: 1; text-wrap: nowrap; text-overflow: ellipsis;
    }
    ProfileRow .name { text-style: bold; color: $atlas-text; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,a", "act('apply')", show=False),
        Binding("r", "act('rename')", show=False),
        Binding("delete,backspace", "act('delete')", show=False),
    ]

    class Act(Message):
        def __init__(self, verb: str, name: str) -> None:
            super().__init__()
            self.verb = verb
            self.name = name

    def __init__(self, profile: dict, info: Content) -> None:
        super().__init__()
        self.profile = profile
        self.info = info

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("▌", classes="bar")
            yield Static(Content(self.profile["name"]), classes="name")
            yield RowAction("enter", "Apply…", "apply", "See the changes, then apply")
            yield RowAction("r", "Rename", "rename", "Rename the profile")
            yield RowAction("delete", "Delete", "delete", "Delete the profile. You can undo it")
        with Horizontal():
            yield Static("▌", classes="bar")
            yield Static(self.info, classes="meta")

    def action_act(self, verb: str) -> None:
        self.post_message(self.Act(verb, self.profile["name"]))

    def on_click(self, event: events.Click) -> None:
        self.focus()

    def on_focus(self) -> None:
        self.query(RowAction).refresh()

    def on_blur(self) -> None:
        self.query(RowAction).refresh()


class ProfilesDialog(Dialog[None]):
    """The profiles, each with Apply…, Rename, and Delete, and Save current as profile…"""

    AUTO_FOCUS = "#cancel"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("s", "save", show=False),
        Binding("down,j", "move(1)", show=False),
        Binding("up,k", "move(-1)", show=False),
    ]
    DEFAULT_CSS = """
    ProfilesDialog #rows { height: auto; }
    ProfilesDialog #state.-error { color: $atlas-danger; }
    """
    last_rows: ClassVar[int] = 0

    def __init__(self, savable: bool, blocked: str) -> None:
        super().__init__()
        self.savable = savable
        self.blocked = blocked
        self.profiles: list[dict] | None = None
        self.error: str | None = None
        self._loaded = False

    def heading(self) -> str:
        return "Profiles"

    def body(self) -> ComposeResult:
        yield Static(id="state", classes="muted")
        yield Vertical(id="rows")
        yield HintButton("enter", "Try again", "retry", id="retry")
        if not self.savable:
            yield Static(self.blocked, classes="muted", id="blocked")

    def buttons(self) -> ComposeResult:
        yield HintButton("esc", "Close", "close", id="cancel")
        yield Static(classes="gap")
        if self.savable:
            yield HintButton("s", "Save current as profile…", "save", variant="primary", id="save")

    def on_mount(self) -> None:
        self.waiting()
        self.load()

    def waiting(self) -> None:
        """Keep the last list's room, with no text: the list is often in before 300 ms."""
        self.query_one("#state").display = False
        self.query_one("#retry").display = False
        rows = self.query_one("#rows")
        rows.styles.min_height = 2 * self.last_rows
        rows.display = bool(self.last_rows)

    def show_loading(self) -> None:
        state = self.query_one("#state", Static)
        state.update("Loading profiles…")
        state.display = True
        self.call_after_refresh(self.fit)

    def load(self) -> None:
        app = self.atlas_app
        show = self.show_loading if self.profiles is None else lambda: None

        async def run() -> None:
            try:
                listing = await fetch_slow(self, show, app.atlas.profiles)
            except Exception as e:
                self.profiles, self.error = None, reason(e)
            else:
                self.profiles, self.error = listing.get("profiles") or [], None
            if self.alive:
                await self.draw()

        spawn(self, run, exclusive=True, group="load")

    async def draw(self) -> None:
        state = self.query_one("#state", Static)
        rows = self.query_one("#rows", Vertical)
        listed = self.profiles or []
        state.set_class(bool(self.error), "-error")
        if self.error:
            state.update(Content(f"✗ Could not read the profiles. {sentence(self.error)}"))
        else:
            state.update(EMPTY)
        state.display = not listed
        self.query_one("#retry").display = bool(self.error)
        rows.styles.min_height = None
        rows.display = bool(listed)
        if self.profiles is not None:
            ProfilesDialog.last_rows = len(listed)
        self.set_heading("Profiles", str(len(listed)) if listed else "")
        before = self.focused.profile["name"] if isinstance(self.focused, ProfileRow) else None
        await rows.remove_children()
        app = self.atlas_app
        made = [ProfileRow(p, profile_meta(app, p)) for p in listed]
        await rows.mount_all(made)
        keep = next((r for r in made if r.profile["name"] == before), None)
        if keep is not None:
            keep.focus()
        elif made and (not self._loaded or before is not None):
            made[0].focus()
        if self.profiles is not None:
            self._loaded = True
        self.call_after_refresh(self.fit)

    def action_retry(self) -> None:
        if self.error:
            self.error = None
            self.waiting()
            self.load()

    def action_move(self, step: int) -> None:
        rows = list(self.query(ProfileRow))
        if not rows:
            return
        at = rows.index(self.focused) if self.focused in rows else (-1 if step > 0 else 0)
        rows[max(0, min(len(rows) - 1, at + step))].focus()

    def action_save(self) -> None:
        if not self.savable:
            return
        names = [p["name"] for p in self.profiles or []]
        app = self.atlas_app
        self.app.push_screen(
            SaveDialog("current", where(app), names=names, harness=app.state.harness or "all"),
            lambda saved: self.load() if saved else None,
        )

    async def on_profile_row_act(self, event: ProfileRow.Act) -> None:
        event.stop()
        app = self.atlas_app
        if event.verb == "apply":
            self.dismiss(None)
            await apply_profile(app, event.name)
        elif event.verb == "rename":
            names = [p["name"] for p in self.profiles or []]
            self.app.push_screen(
                SaveDialog("rename", "", old=event.name, names=names),
                lambda done: self.load() if done else None,
            )
        elif event.verb == "delete":
            listed = await delete_profile(app, event.name)
            if listed is not None and self.alive:
                self.profiles = listed
                await self.draw()


# Save and rename


class SaveDialog(Dialog[str | None]):
    """Save the switches, or the selection, as a profile; or rename one. Returns the name."""

    AUTO_FOCUS = "Input"

    def __init__(
        self,
        mode: Mode,
        spot: str,
        *,
        old: str = "",
        names: list[str] | None = None,
        harness: str = "all",
        chosen: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.spot = spot
        self.old = old
        self.names = names
        self.harness = harness
        self.chosen = chosen or {"skills": [], "plugins": []}
        self.verb = "Rename" if mode == "rename" else "Save profile"
        self.field = Field(
            "Name", value=old, max_length=MAX_NAME, placeholder="Writing week", id="name"
        )
        self.field.input.select_on_focus = mode == "rename"

    @property
    def count(self) -> int:
        return len(self.chosen["skills"]) + len(self.chosen["plugins"])

    def heading(self) -> str:
        if self.mode == "rename":
            return "Rename profile"
        if self.mode == "selection":
            return f"Save {plural(self.count, 'selected skill')} as a profile"
        return "Save current switches as a profile"

    def body(self) -> ComposeResult:
        if self.mode == "selection":
            yield Static(f"Applying the profile turns these on in {self.spot}.", classes="lead")
        elif self.mode == "current":
            yield Static(
                f"The profile keeps which skills are on and off in {self.spot} now.",
                classes="lead",
            )
        yield self.field
        if self.mode == "selection":
            yield PickRow(f"Also turn off all other skills in {self.spot}", on=False, id="rest")

    def buttons(self) -> ComposeResult:
        busy = "Renaming…" if self.mode == "rename" else "Saving…"
        yield HintButton("esc", "Cancel", "close", id="cancel")
        yield Static(classes="gap")
        yield HintButton("enter", self.verb, "go", variant="primary", busy_label=busy, id="go")

    def on_mount(self) -> None:
        if self.names is None:
            spawn(self, self._names, exclusive=True, group="names")

    async def _names(self) -> None:
        app = self.atlas_app
        try:
            listing = await app.fetch(app.atlas.profiles)
        except Exception:
            return
        self.names = [p["name"] for p in listing.get("profiles") or []]
        if self.alive:
            self._check(self.field.value)

    def taken(self, value: str) -> bool:
        name = clean(value)
        return bool(name) and name != self.old and name in (self.names or [])

    def _check(self, value: str) -> None:
        go = self.query_one("#go", HintButton)
        taken = self.taken(value)
        self.field.clear()
        if self.mode == "rename":
            go.disabled = taken
            if taken:
                self.field.show_error("Another profile has this name. Use a different name.")
        else:
            go.relabel("Replace profile" if taken else self.verb)
            if taken:
                self.field.show_note("A profile with this name exists. Saving replaces it.")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._check(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_go()

    def action_go(self) -> None:
        name = clean(self.field.value)
        if not name:
            self.field.show_error("Give the profile a name.")
            return
        if self.mode == "rename" and self.taken(name):
            return
        self.submit(lambda: self._save(name))

    async def _save(self, name: str) -> None:
        app = self.atlas_app
        try:
            if self.mode == "rename":
                await app.fetch(app.atlas.profile, "rename", {"name": self.old, "to": name})
                done = said("Renamed the profile to ", (name, "bold"), ".")
            else:
                req: dict = {"name": name, "replace": name in (self.names or [])}
                if self.harness != "all":
                    req["harnesses"] = [self.harness]
                if self.mode == "selection":
                    req["picked"] = self.chosen
                    req["rest_off"] = self.query_one("#rest", PickRow).on
                r = await app.fetch(app.atlas.profile, "save", req)
                done = said("Saved the profile ", (r.get("saved") or name, "bold"), ".")
        except Exception as e:
            if self.alive:
                self.field.show_error(sentence(reason(e)))
            else:
                toast(app, f"Could not save the profile: {reason(e)}", severity="error")
            return
        if self.alive:
            self.dismiss(name)
        refresh_lists(app)
        toast(app, done)


# Apply


def changes(row: dict) -> list[tuple[bool, str]]:
    def plugin(ref: str) -> str:
        return f"plugin {ref.split('@')[0]}"

    return [
        *((True, x) for x in row["on"]),
        *((True, plugin(x)) for x in row["plugins_on"]),
        *((False, x) for x in row["off"]),
        *((False, plugin(x)) for x in row["plugins_off"]),
    ]


class ApplyDialog(Dialog[None]):
    """`Apply “Writing”?` with each switch that changes, by harness, before anything is written."""

    AUTO_FOCUS = "#cancel"
    BINDINGS: ClassVar[list[BindingType]] = [Binding("a", "go", show=False)]
    DEFAULT_CSS = """
    ApplyDialog .section { height: auto; }
    ApplyDialog .changes { text-wrap: nowrap; text-overflow: ellipsis; padding-left: 2; }
    ApplyDialog .missing { color: $atlas-muted; padding-left: 2; }
    """

    def __init__(self, name: str, preview: dict) -> None:
        super().__init__()
        self.profile = name
        self.preview = preview
        self.changed = int(preview.get("changed") or 0)

    def heading(self) -> Content:
        if self.changed:
            return Content.assemble("Apply “", self.profile, "”?")
        return Content.assemble("Profile “", self.profile, "” already matches")

    def body(self) -> ComposeResult:
        rows = self.preview.get("harnesses") or {}
        word = {True: "$atlas-on", False: "$atlas-muted"}
        n = self.changed
        hit = sum(1 for r in rows.values() if changes(r))
        if n:
            change = "switch changes" if n == 1 else "switches change"
            lead = (
                f"{n} {change} in {plural(hit, 'harness', 'harnesses')}. "
                "You can undo this from the toast."
            )
        else:
            lead = "All switches already match this profile. Nothing changes."
        yield Static(lead, classes="lead")
        app = self.atlas_app
        for hid, row in rows.items():
            moves = changes(row)
            if not moves and not row["missing"]:
                continue
            label = label_of(app, hid) if hid in app.data.harnesses else row.get("label") or hid
            with Vertical(classes="section"):
                ons = sum(1 for on, _ in moves if on)
                head: list[str | Content | tuple[str, str]] = [(label, "bold")]
                if moves:
                    head += ["  ", meta(f"{ons} on", f"{len(moves) - ons} off")]
                yield Static(Content.assemble(*head))
                if moves:
                    lines = [
                        Content.assemble(("on " if on else "off", word[on]), "  ", what)
                        for on, what in moves
                    ]
                    yield Static(Content("\n").join(lines), classes="changes")
                if row["missing"]:
                    gone = (
                        f"{plural(len(row['missing']), 'item')} in the profile "
                        f"{'is' if len(row['missing']) == 1 else 'are'} not installed here"
                        if row.get("found")
                        else f"{label} is not on this computer"
                    )
                    yield Static(
                        f"{gone}, so the atlas skips: {', '.join(row['missing'])}.",
                        classes="missing",
                    )

    def buttons(self) -> ComposeResult:
        if not self.changed:
            yield HintButton("esc", "Close", "close", id="cancel")
            return
        yield HintButton("esc", "Cancel", "close", id="cancel")
        yield Static(classes="gap")
        yield HintButton(
            "a",
            f"Apply {plural(self.changed, 'change')}",
            "go",
            variant="primary",
            busy_label="Applying…",
            id="go",
        )

    def action_go(self) -> None:
        if self.changed:
            self.submit(self._apply)

    async def _apply(self) -> None:
        app, name = self.atlas_app, self.profile
        try:
            r = await app.fetch(app.atlas.profile, "apply", {"name": name})
        except Exception as e:
            if self.alive:
                self.show_error(sentence(reason(e)))
            else:
                toast(app, f"Could not apply {name}: {reason(e)}", severity="error")
            return
        merge_settings(app, r.get("settings") or {})
        if self.alive:
            self.dismiss(None)

        async def undo() -> None:
            try:
                back = await app.fetch(app.atlas.profile, "apply", {"states": r["previous"]})
            except Exception as e:
                toast(app, f"Could not undo: {reason(e)}", severity="error")
                return
            merge_settings(app, back.get("settings") or {})
            toast(app, said("Put back the switches from before ", (name, "bold"), "."))

        n = plural(int(r.get("changed") or 0), "change")
        text = said("Applied ", (name, "bold"), f": {n}. Restart agent sessions to pick it up.")
        toast(app, text, undo=undo, label=f"Applied {name}.")


# Feature functions


async def open_profiles(app: AtlasApp) -> None:
    """The profiles list (`p`)."""
    if writable(app) is None:
        return
    blocked = "" if can_save(app) else no_switch(app)
    app.push_screen(ProfilesDialog(can_save(app), blocked))


async def save_profile(app: AtlasApp, names: Iterable[str] | None = None) -> None:
    """Save the current switches, or the marked (or named) skills, as a profile."""
    if writable(app) is None:
        return
    if not can_save(app):
        toast(app, no_switch(app))
        return
    harness = app.state.harness or "all"
    names = list(names) if names is not None else None
    if names is None and not app.state.marked:
        app.push_screen(SaveDialog("current", where(app), harness=harness))
        return
    chosen = picked(app, names)
    if not chosen["skills"] and not chosen["plugins"]:
        toast(app, f"None of the selected skills has an on/off switch in {where(app)}.")
        return
    app.push_screen(SaveDialog("selection", where(app), harness=harness, chosen=chosen))


async def apply_profile(app: AtlasApp, name: str) -> None:
    """Preview what the profile changes, then apply it after the user agrees."""
    if writable(app) is None:
        return
    try:
        preview = await app.fetch(app.atlas.profile, "preview", {"name": name})
    except Exception as e:
        toast(app, f"Could not read the profile: {reason(e)}", severity="error")
        return
    app.push_screen(ApplyDialog(name, preview))
