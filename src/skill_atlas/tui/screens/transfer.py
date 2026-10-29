"""The skill set: export it to a file or the clipboard, import it, and restore missing skills."""

from __future__ import annotations

import json
import os
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Input, Static

from . import HintButton
from .confirm import (
    Dialog,
    Field,
    Fold,
    PickRow,
    fetch_slow,
    follow_job,
    items,
    jobs,
    plural,
    reason,
    run_job,
    said,
    spawn,
    tilde,
    toast,
    writable,
)

if TYPE_CHECKING:
    from ..app import AtlasApp

DEFAULT_FILE = "~/skill-set.json"
MAX_BYTES = 1 << 20
CHECK_DELAY = 0.15
LEAD = (
    "Save your skills, sources, and switches to a file. "
    "Import the file on a different computer to get the same set."
)


class PathError(Exception):
    """A problem with a path the user typed. The message says how to fix it."""


def resolve(text: str) -> Path:
    """The typed path with `~` expanded, made absolute."""
    return Path(os.path.abspath(Path(text.strip()).expanduser()))


def manifest_text(m: dict) -> str:
    return json.dumps(m, indent=2) + "\n"


def write_manifest(path: Path, text: str) -> None:
    shown = tilde(str(path))
    if path.is_dir():
        raise PathError(
            f"Could not export: {shown} is a folder. "
            f"Add a file name, such as {shown}/skill-set.json."
        )
    if not path.parent.is_dir():
        raise PathError(
            f"Could not export: the folder {tilde(str(path.parent))} is not there. "
            "Create it, or pick another folder."
        )
    tmp = path.with_name(path.name + ".atlas-tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except PermissionError as e:
        tmp.unlink(missing_ok=True)
        raise PathError(
            f"Could not export: you cannot write to {tilde(str(path.parent))}. Pick another folder."
        ) from e
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise PathError(f"Could not export: {e.strerror or e}. Pick another file.") from e


def read_manifest(path: Path) -> dict:
    name, shown = path.name, tilde(str(path))
    if not path.exists():
        raise PathError(f"Could not import {name}: {shown} is not there. Check the path.")
    if path.is_dir():
        raise PathError(f"Could not import {name}: it is a folder. Type the path of a .json file.")
    try:
        if path.stat().st_size > MAX_BYTES:
            raise PathError(f"{name} is too large to be a manifest. Pick the file you exported.")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise PathError(f"{name} is not a JSON file. Pick the file you exported.") from e
    except OSError as e:
        raise PathError(f"Could not import {name}: {e.strerror or e}.") from e
    if not isinstance(data, dict):
        raise PathError(f"Could not import {name}: this file is not a Skill Atlas manifest.")
    return data


def exported_on(stamp: object) -> str:
    """`Oct 28, 2026` from the manifest's ISO time, in local time."""
    if not isinstance(stamp, str) or not stamp:
        return ""
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    return f"{when:%b} {when.day}, {when.year}"


# Export


class ExportDialog(Dialog[None]):
    """Write the skill set to a file, with `~` expanded and a note before a file is replaced."""

    AUTO_FOCUS = "Input"
    BINDINGS: ClassVar[list[BindingType]] = [Binding("ctrl+y", "copy", show=False)]

    def __init__(self) -> None:
        super().__init__()
        self.field = Field("File", value=DEFAULT_FILE, placeholder=DEFAULT_FILE)
        self._timer: Timer | None = None

    def heading(self) -> str:
        return "Export skill set"

    def body(self) -> ComposeResult:
        yield Static(LEAD, classes="lead")
        yield self.field

    def buttons(self) -> ComposeResult:
        yield HintButton("esc", "Cancel", "close", id="cancel")
        yield Static(classes="gap")
        yield HintButton("ctrl+y", "Copy JSON", "copy", busy_label="Copying…", id="copy")
        yield HintButton(
            "enter", "Export", "go", variant="primary", busy_label="Exporting…", id="go"
        )

    def on_mount(self) -> None:
        self._check_soon()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.field.clear()
        self.query_one("#go", HintButton).relabel("Export")
        self._check_soon()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_go()

    def _check_soon(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(CHECK_DELAY, self._check)

    def _check(self) -> None:
        spawn(self, partial(self._exists, self.field.value), exclusive=True, group="exists")

    async def _exists(self, text: str) -> None:
        if not text.strip():
            return
        path = resolve(text)
        found = await self.atlas_app.fetch(path.is_file)
        if not found or not self.alive or self.field.value != text or self.field.failed:
            return
        self.query_one("#go", HintButton).relabel("Replace file")
        self.field.show_note(f"{tilde(str(path))} exists. Export replaces it.")

    def action_go(self) -> None:
        text = self.field.value
        if not text.strip():
            self.field.show_error(f"Type a file path, such as {DEFAULT_FILE}.")
            return
        self.submit(lambda: self._export(resolve(text)))

    async def _export(self, path: Path) -> None:
        app = self.atlas_app
        try:
            m = await app.fetch(app.atlas.export)
            await app.fetch(write_manifest, path, manifest_text(m))
        except PathError as e:
            self._failed(str(e))
            return
        except Exception as e:
            self._failed(f"Could not export: {reason(e)}.")
            return
        if self.alive:
            self.dismiss(None)
        n = plural(len(m.get("skills") or []), "skill")
        toast(app, said(f"Exported {n} to ", (tilde(str(path)), "bold"), "."))

    def action_copy(self) -> None:
        self.submit(self._copy, "#copy")

    async def _copy(self) -> None:
        app = self.atlas_app
        try:
            m = await app.fetch(app.atlas.export)
        except Exception as e:
            self._failed(f"Could not copy: {reason(e)}.")
            return
        if self.alive:
            self.dismiss(None)
        await run_job("copy", app, manifest_text(m), "the skill set")

    def _failed(self, message: str) -> None:
        if self.alive:
            self.field.show_error(message)
        else:
            toast(self.atlas_app, message, severity="error")


# Import


class ImportDialog(Dialog[tuple[dict, dict] | None]):
    """Read a manifest from a path. Returns the manifest and the core's plan for it."""

    AUTO_FOCUS = "Input"

    def __init__(self) -> None:
        super().__init__()
        self.field = Field("File", value=DEFAULT_FILE, placeholder=DEFAULT_FILE)

    def heading(self) -> str:
        return "Import skill set"

    def body(self) -> ComposeResult:
        yield Static(
            "Type the path of a file that Skill Atlas exported. "
            "You see each change before the import starts.",
            classes="lead",
        )
        yield self.field
        yield Static(
            "To import from a different computer, copy the file to this one first.",
            classes="muted",
        )

    def buttons(self) -> ComposeResult:
        yield HintButton("esc", "Cancel", "close", id="cancel")
        yield Static(classes="gap")
        yield HintButton(
            "enter", "See changes", "go", variant="primary", busy_label="Reading…", id="go"
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        self.field.clear()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_go()

    def action_go(self) -> None:
        text = self.field.value
        if not text.strip():
            self.field.show_error(f"Type the path of a manifest file, such as {DEFAULT_FILE}.")
            return
        self.submit(lambda: self._read(resolve(text)))

    async def _read(self, path: Path) -> None:
        app = self.atlas_app
        try:
            m = await app.fetch(read_manifest, path)
            plan = await app.fetch(app.atlas.import_plan, {"manifest": m})
        except PathError as e:
            message = str(e)
        except Exception as e:
            message = f"Could not import {path.name}: {reason(e)}."
        else:
            if self.alive:
                self.dismiss((m, plan))
            return
        if self.alive:
            self.field.show_error(message)


class PlanDialog(Dialog[None]):
    """What an import or a restore does, in groups the user can skip, before it runs."""

    AUTO_FOCUS = "PickRow, #cancel"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("i", "key('i')", show=False),
        Binding("r", "key('r')", show=False),
    ]
    DEFAULT_CSS = """
    PlanDialog .group { height: auto; }
    PlanDialog .skipped { color: $atlas-muted; }
    """

    def __init__(self, plan: dict, req: dict) -> None:
        super().__init__()
        self.plan = plan
        self.req = req
        self.restore = bool(req.get("restore"))
        self.key = "r" if self.restore else "i"
        self.acts = bool(plan["install"] or plan["harness"] or plan["watch"])

    def heading(self) -> str:
        if self.restore:
            return f"Restore {plural(len(self.plan['install']), 'missing skill')}?"
        return "Import skill set?"

    def lead(self) -> str:
        if not self.acts:
            if self.restore:
                return "No skill is missing now."
            return "This computer already has everything in the file that the atlas can install."
        if self.restore:
            return (
                "Download each skill again from its GitHub source. "
                "You get the version that the repo has now."
            )
        m = self.req.get("manifest") or {}
        host, when = m.get("host"), exported_on(m.get("exported_at"))
        source = f"From {host}" if host else "From the file"
        dated = f", exported {when}" if when else ""
        return f"{source}{dated}. To skip a group, set its switch to off."

    def body(self) -> ComposeResult:
        p = self.plan
        yield Static(self.lead(), classes="lead")
        if p["install"]:
            verb = "Restore" if self.restore else "Install"
            with Vertical(classes="group"):
                yield PickRow(
                    f"{verb} {plural(len(p['install']), 'skill')}", "from GitHub", value="install"
                )
                yield Static(
                    items((i["name"], "", i["repo"]) for i in p["install"]), classes="items"
                )
        for h in p["harness"]:
            with Vertical(classes="group"):
                yield PickRow(
                    f"Turn off {plural(len(h['off']), 'skill')}",
                    f"in {h['name']}",
                    value=f"harness:{h['harness']}",
                )
                yield Static(items((n, "", "") for n in h["off"]), classes="items")
        if p["watch"]:
            with Vertical(classes="group"):
                yield PickRow(
                    f"Watch {plural(len(p['watch']), 'repo')}", "for new skills", value="watch"
                )
                yield Static(items((r, "", "") for r in p["watch"]), classes="items")
        here = [(s["name"], "", s.get("source") or "") for s in p["same"]]
        here += [(s["name"], "other files", s.get("source") or "") for s in p["differ"]]
        if here:
            with Vertical(classes="group"):
                listed = Static(items(here), classes="items")
                yield Fold(f"Already here: {len(here)}", listed)
                yield listed
        if p["untracked"]:
            why = (
                "Its lock entry names a different folder"
                if self.restore
                else "Not from GitHub. Copy it by hand"
            )
            with Vertical(classes="group"):
                listed = Static(
                    items((u["name"], "", why) for u in p["untracked"]), classes="items"
                )
                yield Fold(f"Cannot install: {len(p['untracked'])}", listed)
                yield listed
        if p["skipped"]:
            names = ", ".join(h["name"] for h in p["skipped"])
            yield Static(
                f"Not on this computer, so switches stay as they are: {names}.", classes="skipped"
            )

    def buttons(self) -> ComposeResult:
        if not self.acts:
            yield HintButton("esc", "Close", "close", id="cancel")
            return
        verb = "Restore" if self.restore else "Import"
        yield HintButton("esc", "Cancel", "close", id="cancel")
        yield Static(classes="gap")
        yield HintButton(
            self.key, verb, "go", variant="primary", busy_label=f"{verb[:-1]}ing…", id="go"
        )

    def on_pick_row_changed(self, event: PickRow.Changed) -> None:
        self.query_one("#go", HintButton).disabled = not any(self.picks().values())

    def picks(self) -> dict[str, list[str]]:
        on = {r.value for r in self.query(PickRow) if r.on}
        p = self.plan
        return {
            "install": [i["name"] for i in p["install"]] if "install" in on else [],
            "harness": [h["harness"] for h in p["harness"] if f"harness:{h['harness']}" in on],
            "watch": list(p["watch"]) if "watch" in on else [],
        }

    def action_key(self, key: str) -> None:
        if key == self.key:
            self.action_go()

    def action_go(self) -> None:
        pick = self.picks()
        if not self.acts or not any(pick.values()):
            return
        app = self.atlas_app
        if jobs().running(app):
            toast(app, "Another job is still running.")
            return
        self.submit(lambda: self._apply({**self.req, **pick}))

    async def _apply(self, req: dict) -> None:
        app = self.atlas_app
        verb = "restore" if self.restore else "import"
        try:
            r = await app.fetch(app.atlas.import_apply, req)
        except Exception as e:
            if self.alive:
                self.show_error(f"Could not {verb}: {reason(e)}.")
            else:
                toast(app, f"Could not {verb}: {reason(e)}.", severity="error")
            return
        if self.alive:
            self.dismiss(None)
        errors = [str(e).rstrip(".") for e in r.get("errors") or []]
        switched, watched = int(r.get("switched") or 0), int(r.get("watched") or 0)
        done = " ".join(
            part
            for part in (
                f"Turned off {plural(switched, 'skill switch', 'skill switches')}."
                if switched
                else "",
                f"Watching {plural(watched, 'new repo')}." if watched else "",
                f"{plural(len(errors), 'step')} failed: {errors[0]}." if errors else "",
            )
            if part
        )
        if r.get("job"):
            await follow_job(app, r["job"], note=f" {done}" if done else "")
            return
        app.reload(["scan", "updates"] if watched else ["scan"], refresh=bool(watched))
        toast(app, done or "Nothing changed.", severity="warning" if errors else "information")


class ReadingDialog(Dialog[None]):
    """Shows only when the lock file takes more than 300 ms to read."""

    AUTO_FOCUS = "#cancel"

    def heading(self) -> str:
        return "Restore missing skills"

    def body(self) -> ComposeResult:
        yield Static("Reading the lock file…", classes="muted")

    def buttons(self) -> ComposeResult:
        yield HintButton("esc", "Cancel", "close", id="cancel")


# Feature functions


async def open_export(app: AtlasApp) -> None:
    """Write the skill set to a file, or copy its JSON."""
    if writable(app) is not None:
        app.push_screen(ExportDialog())


async def copy_manifest(app: AtlasApp) -> None:
    """Copy the skill set's JSON to the clipboard, with no dialog."""
    try:
        m = await app.fetch(app.atlas.export)
    except Exception as e:
        toast(app, f"Could not copy: {reason(e)}.", severity="error")
        return
    await run_job("copy", app, manifest_text(m), "the skill set")


async def open_import(app: AtlasApp) -> None:
    """Read a manifest file, then show its plan."""
    if writable(app) is None:
        return

    def read(result: tuple[dict, dict] | None) -> None:
        if result is not None:
            m, plan = result
            app.push_screen(PlanDialog(plan, {"manifest": m}))

    app.push_screen(ImportDialog(), read)


async def open_restore(app: AtlasApp) -> None:
    """Download the skills that the lock file names but that have no folder."""
    if writable(app) is None:
        return
    wait = ReadingDialog()
    shown: list[bool] = []

    def show() -> None:
        shown.append(True)
        app.push_screen(wait)

    try:
        plan = await fetch_slow(app, show, app.atlas.import_plan, {"restore": True})
    except Exception as e:
        if app.screen is wait:
            wait.dismiss(None)
        toast(app, f"Could not read the lock file: {reason(e)}.", severity="error")
        return
    if shown and not wait.alive:
        return
    dialog = PlanDialog(plan, {"restore": True})
    if app.screen is wait:
        app.switch_screen(dialog)
    else:
        app.push_screen(dialog)
