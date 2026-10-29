import asyncio
import importlib
import json
import threading
import time
from datetime import datetime

import pytest
from textual.widgets import Input, Static

from skill_atlas.core.demo import DemoAtlas
from skill_atlas.tui.app import AtlasApp, settle
from skill_atlas.tui.screens import CloseCell, HintButton, confirm, link, profiles, transfer
from skill_atlas.tui.screens.confirm import ConfirmDelete, Field, Fold, PickRow

NOW = datetime(2026, 10, 28, 12, 0)
SIZE = (120, 36)


class Jobs:
    """Records what the dialogs hand to jobs, in place of its writes and toasts."""

    def __init__(self):
        self.calls = []
        self.toasts = []
        self.undos = []
        self.busy = False

    def toast(self, app, text, *, severity="information", action=None):
        self.toasts.append((str(text), severity, action))

    def push_undo(self, app, label, callback):
        self.undos.append(callback)

    def undo(self, app):
        self.calls.append(("undo",))

    def delete(self, app, names):
        self.calls.append(("delete", list(names)))

    def copy(self, app, text, what):
        self.calls.append(("copy", text, what))

    def running(self, app):
        return self.busy

    def follow(self, app, view, note=""):
        self.calls.append(("follow", view, note))

    @property
    def said(self):
        return [t for t, _, _ in self.toasts]


@pytest.fixture
def jobs(monkeypatch):
    rec = Jobs()
    real = importlib.import_module("skill_atlas.tui.jobs")
    for name in ("toast", "push_undo", "undo", "delete", "copy", "running"):
        monkeypatch.setattr(real, name, getattr(rec, name))
    monkeypatch.setattr(real, "follow", rec.follow, raising=False)
    return rec


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def app(prefs, jobs, home):
    return AtlasApp(DemoAtlas(n=1, now=NOW))


def shown(app):
    return "\n".join(s.text for s in app.screen._compositor.render_strips())


def text_of(screen, selector):
    return "\n".join(str(w.content) for w in screen.query(selector) if isinstance(w, Static))


def store_skill(app, **want):
    return next(
        s for s in app.data.skills if s.get("store") and all(s.get(k) == v for k, v in want.items())
    )


def text_of_row(row):
    return " ".join(str(a.render()) for a in row.query("RowAction"))


async def open_(pilot, fn, *args):
    await fn(pilot.app, *args)
    await settle(pilot)
    return pilot.app.screen


# Shared parts


def test_helpers_match_the_web_strings():
    assert confirm.harness_list(["A"]) == "A"
    assert confirm.harness_list(["A", "B"]) == "A and B"
    assert confirm.harness_list(["A", "B", "C"]) == "A, B, C"
    assert confirm.harness_list(list("ABCDE")) == "A, B, C, and 2 more"
    assert confirm.sentence("could not read x") == "Could not read x."
    assert confirm.sentence("Done.") == "Done."
    assert confirm.sentence("run `gh auth login`") == "Run gh auth login."
    assert link.repo_problem("acme/skills") is None
    assert link.repo_problem("https://github.com/acme/skills.git") is None
    assert "owner/repo" in link.repo_problem("")
    assert link.repo_problem("not a repo").startswith("“not a repo” is not a GitHub repo.")
    assert transfer.exported_on("2026-10-28T17:00:00Z") == "Oct 28, 2026"
    assert transfer.exported_on("") == ""
    assert confirm.trash_problem(DemoAtlas(n=1, now=NOW)) is None


# Delete


@pytest.mark.asyncio
async def test_delete_confirm_keys(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        name = store_skill(app, local_edits=True)["dir_name"]
        screen = await open_(pilot, confirm.confirm_delete, [name])
        assert isinstance(screen, ConfirmDelete)
        assert screen.focused.id == "cancel"
        assert screen.query_one("#cancel").region.width == len(" esc Cancel ")
        assert f"Move /{name} to the Trash?" in shown(app)
        lead = text_of(screen, ".lead")
        assert lead.startswith("It stops loading in Claude Code · personal, Codex, Cursor, and ")
        assert lead.endswith("Lock entries and on/off settings for it go too.")
        assert "1 skill has changes you made after install." in text_of(screen, ".warn")
        await pilot.press("enter")
        await settle(pilot)
        assert not isinstance(app.screen, ConfirmDelete)
        assert jobs.calls == []
        await open_(pilot, confirm.confirm_delete, [name])
        await pilot.press("d")
        await settle(pilot)
        assert not isinstance(app.screen, ConfirmDelete)
        assert jobs.calls == [("delete", [name])]


@pytest.mark.asyncio
async def test_delete_confirm_mouse(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        names = [s["dir_name"] for s in app.data.skills if s.get("store")][:3]
        app.set_state(marked=frozenset(store_skill(app, dir_name=n)["path"] for n in names))
        screen = await open_(pilot, confirm.confirm_delete)
        assert "Move 3 skills to the Trash?" in shown(app)
        assert "Move 3 to Trash" in shown(app)
        await pilot.click(offset=(1, 1))
        assert app.screen is screen
        await pilot.hover("#go")
        await pilot.click("#go")
        await settle(pilot)
        assert jobs.calls == [("delete", names)]
        await open_(pilot, confirm.confirm_delete, names)
        await pilot.click(CloseCell)
        await settle(pilot)
        assert not isinstance(app.screen, ConfirmDelete)
        assert len(jobs.calls) == 1


@pytest.mark.asyncio
async def test_delete_without_a_trash_disables_the_action(app, jobs, monkeypatch):
    monkeypatch.setattr(confirm, "trash_problem", lambda atlas: "Delete needs a Trash folder")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        name = store_skill(app)["dir_name"]
        screen = await open_(pilot, confirm.confirm_delete, [name])
        assert screen.query_one("#go", HintButton).disabled
        assert "Delete needs a Trash folder. Remove the folders by hand" in text_of(
            screen, "#error"
        )
        await pilot.press("d")
        await pilot.click("#go")
        await settle(pilot)
        assert app.screen is screen and jobs.calls == []


@pytest.mark.asyncio
async def test_delete_only_store_skills(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        plugin = next(s for s in app.data.skills if s.get("scope") == "plugin")
        await confirm.confirm_delete(app, [plugin["path"]])
        await settle(pilot)
        assert not isinstance(app.screen, ConfirmDelete)
        assert jobs.said == [
            "Only skills in your skill store can move to the Trash. Pick one of those."
        ]


# Profiles


@pytest.mark.asyncio
async def test_profiles_list_rename_by_keys(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        screen = await open_(pilot, profiles.open_profiles)
        rows = list(screen.query(profiles.ProfileRow))
        assert [r.profile["name"] for r in rows] == [
            "Writing mode",
            "iOS release week",
            "Minimal context",
        ]
        assert screen.focused is rows[0]
        assert "10 on · 6 off · 2 harnesses" in shown(app)
        assert shown(app).count("enter Apply…") == 1 and shown(app).count("Apply…") == 3
        assert "enter apply" not in shown(app)
        widths = [a.region.width for a in rows[1].query(profiles.RowAction)]
        await pilot.press("down")
        assert screen.focused is rows[1]
        assert [a.region.width for a in rows[1].query(profiles.RowAction)] == widths
        assert "r Rename" in text_of_row(rows[1]) and "r Rename" not in text_of_row(rows[0])
        await pilot.press("r")
        await settle(pilot)
        rename = app.screen
        assert isinstance(rename, profiles.SaveDialog) and "Rename profile" in shown(app)
        await pilot.press(*"Writing mode")
        assert "Another profile has this name. Use a different name." in shown(app)
        assert rename.query_one("#go", HintButton).disabled
        await pilot.press("enter")
        await settle(pilot)
        assert app.screen is rename
        await pilot.press("ctrl+u", *"Ship week", "enter")
        await settle(pilot)
        assert app.screen is screen
        names = [p["name"] for p in app.atlas.profiles()["profiles"]]
        assert names == ["Writing mode", "Ship week", "Minimal context"]
        assert [r.profile["name"] for r in screen.query(profiles.ProfileRow)][1] == "Ship week"
        assert jobs.said[-1] == "Renamed the profile to Ship week."


@pytest.mark.asyncio
async def test_profile_delete_and_undo(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        screen = await open_(pilot, profiles.open_profiles)
        await pilot.press("delete")
        await settle(pilot)
        assert len(screen.query(profiles.ProfileRow)) == 2
        assert jobs.said[-1] == "Deleted the profile Writing mode."
        assert jobs.toasts[-1][2][:2] == ("z", "Undo")
        await jobs.undos[-1]()
        await settle(pilot)
        assert jobs.said[-1] == "Put back the profile Writing mode."
        assert len(screen.query(profiles.ProfileRow)) == 3


@pytest.mark.asyncio
async def test_profile_apply_preview_mouse_and_undo(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        n = app.atlas.profile("preview", {"name": "Writing mode"})["changed"]
        assert n > 1
        screen = await open_(pilot, profiles.open_profiles)
        apply_word = screen.query(profiles.RowAction).first()
        await pilot.hover(apply_word)
        await pilot.click(apply_word)
        await settle(pilot)
        dialog = app.screen
        assert isinstance(dialog, profiles.ApplyDialog)
        assert "Apply “Writing mode”?" in shown(app)
        assert text_of(dialog, ".lead").startswith(f"{n} switches change in ")
        assert dialog.focused.id == "cancel"
        lines = text_of(dialog, ".changes").splitlines()
        assert lines and all(line[:5] in ("on   ", "off  ") for line in lines)
        await pilot.click("#go")
        await settle(pilot)
        assert not isinstance(app.screen, profiles.ApplyDialog)
        assert app.atlas.profile("preview", {"name": "Writing mode"})["changed"] == 0
        assert jobs.said[-1] == (
            f"Applied Writing mode: {n} changes. Restart agent sessions to pick it up."
        )
        await jobs.undos[-1]()
        await settle(pilot)
        assert app.atlas.profile("preview", {"name": "Writing mode"})["changed"] == n
        assert jobs.said[-1] == "Put back the switches from before Writing mode."


@pytest.mark.asyncio
async def test_profile_apply_when_nothing_changes(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        app.atlas.profile("apply", {"name": "Writing mode"})
        dialog = await open_(pilot, profiles.apply_profile, "Writing mode")
        assert "Profile “Writing mode” already matches" in shown(app)
        assert "All switches already match this profile. Nothing changes." in shown(app)
        assert [h.id for h in dialog.query(HintButton)] == ["cancel"]
        await pilot.press("a")
        await settle(pilot)
        assert app.screen is dialog
        await pilot.press("escape")
        assert app.screen is not dialog


@pytest.mark.asyncio
async def test_save_current_profile(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        dialog = await open_(pilot, profiles.save_profile)
        assert "Save current switches as a profile" in shown(app)
        assert isinstance(dialog.focused, Input)
        await pilot.press("enter")
        assert "✗ Give the profile a name." in shown(app)
        await pilot.press(*"Writing mode")
        await pilot.pause()
        assert "A profile with this name exists. Saving replaces it." in shown(app)
        assert "Replace profile" in shown(app)
        await pilot.press("ctrl+u", *"Deep work", "enter")
        await settle(pilot)
        assert app.screen is not dialog
        saved = {p["name"]: p for p in app.atlas.profiles()["profiles"]}
        assert list(saved["Deep work"]["harnesses"]) == ["claude-code:personal"]
        assert jobs.said[-1] == "Saved the profile Deep work."


@pytest.mark.asyncio
async def test_save_from_the_list_keeps_the_harness(app, jobs, monkeypatch):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        sent = []
        real = app.atlas.profile

        def profile(action, req):
            sent.append((action, req))
            return real(action, req)

        monkeypatch.setattr(app.atlas, "profile", profile)
        await pilot.press("p")
        await settle(pilot)
        assert isinstance(app.screen, profiles.ProfilesDialog)
        await pilot.press("s")
        await settle(pilot)
        await pilot.press(*"Probe", "enter")
        await settle(pilot)
        assert sent[-1][0] == "save"
        assert sent[-1][1]["harnesses"] == [app.state.harness]


@pytest.mark.asyncio
async def test_profiles_slow_read_shows_loading_late(app, jobs, monkeypatch):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        listing = app.atlas.profiles
        done = threading.Event()

        def slow():
            done.wait(5)
            return listing()

        monkeypatch.setattr(app.atlas, "profiles", slow)
        await profiles.open_profiles(app)
        await pilot.pause()
        screen = app.screen
        assert "Loading profiles…" not in shown(app)
        for _ in range(100):
            await asyncio.sleep(0.02)
            if "Loading profiles…" in shown(app):
                break
        assert "Loading profiles…" in shown(app)
        done.set()
        await asyncio.sleep(0.1)
        await settle(pilot)
        assert "Loading profiles…" not in shown(app)
        assert len(screen.query(profiles.ProfileRow)) == 3


@pytest.mark.asyncio
async def test_save_selection_profile_by_mouse(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        marked = [s["path"] for s in app.data.skills if s.get("scope") == "personal"][:3]
        app.set_state(marked=frozenset(marked))
        dialog = await open_(pilot, profiles.save_profile)
        assert "Save 3 selected skills as a profile" in shown(app)
        rest = dialog.query_one("#rest", PickRow)
        assert not rest.on
        await pilot.click(rest)
        assert rest.on
        await pilot.click(dialog.query_one(Field).query_one(Input))
        await pilot.press(*"Three only")
        await pilot.click("#go")
        await settle(pilot)
        saved = {p["name"]: p for p in app.atlas.profiles()["profiles"]}["Three only"]
        assert saved["on"] == 3 and saved["off"] > 0


@pytest.mark.asyncio
async def test_profiles_without_a_switch(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        app.set_state(harness="cursor")
        await profiles.save_profile(app)
        await settle(pilot)
        blocked = "Cursor has no on/off switch for skills. Pick another harness to save a profile."
        assert jobs.said == [blocked]
        screen = await open_(pilot, profiles.open_profiles)
        assert not screen.query("#save")
        assert text_of(screen, "#blocked") == blocked


@pytest.mark.asyncio
async def test_profiles_error_empty_and_retry(app, jobs, monkeypatch):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        listing = app.atlas.profiles

        def broken():
            raise OSError("profiles.json is not valid JSON")

        monkeypatch.setattr(app.atlas, "profiles", broken)
        screen = await open_(pilot, profiles.open_profiles)
        assert "✗ Could not read the profiles. Profiles.json is not valid JSON." in shown(app)
        monkeypatch.setattr(app.atlas, "profiles", lambda: {"profiles": []})
        await pilot.click("#retry")
        await settle(pilot)
        assert profiles.EMPTY in text_of(screen, "#state")
        monkeypatch.setattr(app.atlas, "profiles", listing)
        screen.load()
        await settle(pilot)
        assert len(screen.query(profiles.ProfileRow)) == 3


# Export, import, restore


@pytest.mark.asyncio
async def test_export_to_the_default_file_then_replace(app, jobs, home):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        dialog = await open_(pilot, transfer.open_export)
        assert dialog.query_one(Field).value == "~/skill-set.json"
        await pilot.press("enter")
        await settle(pilot)
        written = json.loads((home / "skill-set.json").read_text())
        assert written["skill_atlas_manifest"] == 1
        n = len(written["skills"])
        assert jobs.said[-1] == f"Exported {n} skills to ~/skill-set.json."
        dialog = await open_(pilot, transfer.open_export)
        await pilot.pause(0.3)
        await settle(pilot)
        assert "~/skill-set.json exists. Export replaces it." in shown(app)
        assert "Replace file" in shown(app)


@pytest.mark.asyncio
async def test_export_path_errors_and_copy(app, jobs, home):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        dialog = await open_(pilot, transfer.open_export)
        await pilot.press("ctrl+u", "enter")
        assert "✗ Type a file path, such as ~/skill-set.json." in shown(app)
        await pilot.press(*"~/nowhere/set.json", "enter")
        await settle(pilot)
        assert "the folder ~/nowhere is not there. Create it" in text_of(dialog, ".field--line")
        (home / "dir").mkdir()
        await pilot.press("ctrl+u", *"~/dir", "enter")
        await settle(pilot)
        assert "~/dir is a folder. Add a file name" in text_of(dialog, ".field--line")
        assert app.screen is dialog
        await pilot.click("#copy")
        await settle(pilot)
        kind, text, what = jobs.calls[-1]
        assert (kind, what) == ("copy", "the skill set")
        assert json.loads(text)["host"] == "demo-mbp"
        assert app.screen is not dialog


def manifest(app, **extra):
    m = app.atlas.export()
    m["host"] = "work-laptop"
    m.update(extra)
    return m


@pytest.mark.asyncio
async def test_import_plan_groups_and_apply(app, jobs, home):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        source, watch = "mattpocock/skills", "orbit-tools/skills"
        offered = app.atlas.updates()["available"][source][0]
        m = manifest(
            app,
            skills=[{"name": offered["name"], "source": source, "skillPath": offered["path"]}],
            watched=[watch],
            harness_states={"codex": {"name": "Codex", "off": ["seo-audit"]}},
        )
        (home / "skill-set.json").write_text(json.dumps(m))
        await open_(pilot, transfer.open_import)
        await pilot.press("enter")
        await settle(pilot)
        plan = app.screen
        assert isinstance(plan, transfer.PlanDialog)
        assert "Import skill set?" in shown(app)
        assert text_of(plan, ".lead").startswith("From work-laptop, exported Oct 28, 2026.")
        rows = {r.value: r for r in plan.query(PickRow)}
        assert set(rows) == {"install", "harness:codex", "watch"}
        assert plan.focused is rows["install"]
        await pilot.click(rows["harness:codex"])
        assert not rows["harness:codex"].on
        await pilot.press("i")
        await settle(pilot)
        kind, view, note = jobs.calls[-1]
        assert kind == "follow" and list(view["items"]) == [offered["name"]]
        assert note == " Watching 1 new repo."
        assert watch in app.atlas.export()["watched"]


@pytest.mark.asyncio
async def test_import_nothing_to_do_and_all_groups_off(app, jobs, home):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        (home / "skill-set.json").write_text(json.dumps(manifest(app)))
        await open_(pilot, transfer.open_import)
        await pilot.click("#go")
        await settle(pilot)
        plan = app.screen
        assert "This computer already has everything in the file" in text_of(plan, ".lead")
        assert [h.id for h in plan.query(HintButton)] == ["cancel"]
        fold = plan.query_one(Fold)
        assert not fold.target.display
        await pilot.click(fold)
        assert fold.target.display
        await pilot.press("escape")
        plan = transfer.PlanDialog(
            {"install": [], "same": [], "differ": [], "untracked": [], "skipped": [],
             "harness": [{"harness": "codex", "name": "Codex", "off": ["ads"]}], "watch": []},
            {"manifest": {}},
        )  # fmt: skip
        app.push_screen(plan)
        await settle(pilot)
        await pilot.press("space")
        assert plan.query_one("#go", HintButton).disabled
        await pilot.press("i")
        await settle(pilot)
        assert app.screen is plan and jobs.calls == []


@pytest.mark.asyncio
async def test_import_file_errors(app, jobs, home):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        dialog = await open_(pilot, transfer.open_import)
        line = ".field--line"
        await pilot.press("ctrl+u", *"~/gone.json", "enter")
        await settle(pilot)
        assert "Could not import gone.json: ~/gone.json is not there." in text_of(dialog, line)
        (home / "notes.json").write_text("not json")
        await pilot.press("ctrl+u", *"~/notes.json", "enter")
        await settle(pilot)
        assert "notes.json is not a JSON file." in text_of(dialog, line)
        (home / "big.json").write_text(" " * (transfer.MAX_BYTES + 1))
        await pilot.press("ctrl+u", *"~/big.json", "enter")
        await settle(pilot)
        assert "big.json is too large to be a manifest." in text_of(dialog, line)
        (home / "other.json").write_text(json.dumps({"skills": []}))
        await pilot.press("ctrl+u", *"~/other.json", "enter")
        await settle(pilot)
        assert "this file is not a Skill Atlas manifest" in text_of(dialog, line)
        await pilot.press("a")
        assert text_of(dialog, line) == ""


@pytest.mark.asyncio
async def test_restore_missing_skills(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        plan = await open_(pilot, transfer.open_restore)
        assert "Restore 1 missing skill?" in shown(app)
        jobs.busy = True
        await pilot.press("r")
        await settle(pilot)
        assert jobs.said[-1] == "Another job is still running."
        assert app.screen is plan
        jobs.busy = False
        await pilot.click("#go")
        await settle(pilot)
        kind, view, _ = jobs.calls[-1]
        assert kind == "follow" and list(view["items"]) == ["ab-test-setup"]


@pytest.mark.asyncio
async def test_restore_slow_read_shows_reading(app, jobs, monkeypatch):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        plan = app.atlas.import_plan

        def slow(req):
            time.sleep(0.6)
            return plan(req)

        monkeypatch.setattr(app.atlas, "import_plan", slow)
        task = asyncio.create_task(transfer.open_restore(app))
        await asyncio.sleep(0.1)
        assert "Reading the lock file…" not in shown(app)
        await asyncio.sleep(0.35)
        assert isinstance(app.screen, transfer.ReadingDialog)
        assert "Reading the lock file…" in shown(app)
        await task
        await settle(pilot)
        assert isinstance(app.screen, transfer.PlanDialog)
        await pilot.press("escape")
        await settle(pilot)
        assert not isinstance(app.screen, (transfer.PlanDialog, transfer.ReadingDialog))


@pytest.mark.asyncio
async def test_restore_read_error(app, jobs, monkeypatch):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)

        def broken(req):
            raise ValueError("the lock file is not valid JSON")

        monkeypatch.setattr(app.atlas, "import_plan", broken)
        await transfer.open_restore(app)
        await settle(pilot)
        assert jobs.said == ["Could not read the lock file: the lock file is not valid JSON."]


# Link and watch


@pytest.mark.asyncio
async def test_link_validates_then_links(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        dialog = await open_(pilot, link.open_link, ["acme-deploy"])
        assert "Link /acme-deploy to GitHub" in shown(app)
        await pilot.press("enter")
        assert "✗ Type a repo as owner/repo, or paste its GitHub URL." in shown(app)
        await pilot.press(*"acme", "enter")
        assert "“acme” is not a GitHub repo." in text_of(dialog, ".field--line")
        await pilot.press(*"-corp/agent-skills")
        assert text_of(dialog, ".field--line") == ""
        await pilot.press("enter")
        await settle(pilot)
        assert app.screen is not dialog
        assert jobs.said[-1] == "Linked 1 to acme-corp/agent-skills."
        skill = store_skill(app, dir_name="acme-deploy")
        assert skill.get("origin", {}).get("source") == "acme-corp/agent-skills"


@pytest.mark.asyncio
async def test_link_errors_stay_in_the_dialog(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        skill = store_skill(app, dir_name="acli")
        app.set_state(selected=skill["path"])
        dialog = await open_(pilot, link.open_link)
        await pilot.press(*"acme-corp/agent-skills")
        await pilot.click("#go")
        await settle(pilot)
        assert app.screen is dialog
        assert text_of(dialog, ".field--line") == (
            "✗ No folder in acme-corp/agent-skills has the same name as this skill."
        )
        await pilot.press("ctrl+u", *"nobody/nothing", "enter")
        await settle(pilot)
        assert text_of(dialog, ".field--line").startswith(
            "✗ Could not read nobody/nothing from GitHub: not found."
        )
        await pilot.press("escape")
        assert app.screen is not dialog


@pytest.mark.asyncio
async def test_watch_a_source(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        dialog = await open_(pilot, link.open_watch)
        assert "Watch a GitHub repo for new skills" in shown(app)
        await pilot.press(*"elevenlabs/skills", "enter")
        await settle(pilot)
        assert text_of(dialog, ".field--line") == (
            "✗ Could not read elevenlabs/skills from GitHub: GitHub did not answer in time."
        )
        await pilot.press("ctrl+u", *"https://github.com/orbit-tools/skills", "enter")
        await settle(pilot)
        assert app.screen is not dialog
        n = len(app.data.available["orbit-tools/skills"])
        assert jobs.said[-1] == f"Watching orbit-tools/skills. {n} skills available."
        assert app.state.selected_key == "src:orbit-tools/skills"


@pytest.mark.asyncio
async def test_dialogs_close_on_a_click_outside(app, jobs):
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        for fn in (link.open_watch, transfer.open_export, profiles.open_profiles):
            dialog = await open_(pilot, fn)
            await pilot.click(offset=(1, 1))
            await settle(pilot)
            assert app.screen is not dialog
