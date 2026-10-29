"""The one interface the web server and the TUI both call.

Each method matches one `/api/...` route in `serve.py`, and returns the same JSON-ready dict.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class AtlasAPI(Protocol):
    # Reads
    def now(self) -> datetime: ...  # no route; the clock that ages and charts read
    def data(self) -> dict: ...  # /api/data: a fresh scan plus server info
    def skill_text(self, path: str) -> str: ...  # /api/skill
    def usage(self) -> dict: ...  # /api/usage
    def updates(self, refresh: bool = False) -> dict: ...  # /api/updates
    def diff(self, name: str) -> dict: ...  # /api/diff
    def history(self, name: str) -> dict: ...  # /api/history
    def snapshot_diff(self, name: str, snap_id: str) -> dict: ...  # no route; the TUI restore view
    def compare(self, a: str, b: str) -> dict: ...  # /api/compare, by skill path
    def security(self, path: str) -> dict: ...  # /api/security
    def profiles(self) -> dict: ...  # /api/profiles
    def export(self) -> dict: ...  # /api/export
    def restore_plan(self) -> dict: ...  # /api/restore
    def job(self, job_id: str) -> dict | None: ...  # /api/jobs/<id>; None when the job is gone
    def repos(self, repos: list[str]) -> dict: ...  # /api/repos: description, stars, images
    # No route; the web reads raw.githubusercontent itself.
    def available_text(self, repo: str, path: str) -> str: ...

    # Writes
    def toggle(self, root: str, kind: str, names: list[str], on: bool) -> dict: ...
    def reveal(self, path: str) -> None: ...
    def watch(self, repo: str, on: bool) -> dict: ...
    def available(self, repo: str, paths: list[str]) -> dict: ...
    def install(self, repo: str, paths: list[str]) -> dict: ...  # returns a job view
    def dismiss(self, repo: str, paths: list[str]) -> dict: ...
    def rollback(self, name: str, snap_id: str) -> dict: ...
    def profile(self, action: str, req: dict) -> dict: ...  # action is one of profiles.ACTIONS
    def import_plan(self, req: dict) -> dict: ...  # body of /api/import/plan
    def import_apply(self, req: dict) -> dict: ...  # body of /api/import/apply
    def undo_delete(self) -> dict: ...
    def update(self, names: list[str]) -> dict: ...  # returns a job view
    def link(self, names: list[str], repo: str) -> dict: ...
    def delete(self, names: list[str]) -> dict: ...
