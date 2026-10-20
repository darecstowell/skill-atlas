#!/usr/bin/env python3
"""Serve the atlas on localhost so it can toggle, update, link, and delete skills."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import remove
import updates
from build import render_page
from scan import scan, settings_state

REPO = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(24)
ROOTS: dict[str, Path] = {}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][\w.-]*$")


def write_setting(root: Path, kind: str, names: list[str], on: bool) -> None:
    path = root / "settings.json"
    settings = json.loads(path.read_text()) if path.exists() else {}
    backup = path.with_name("settings.json.atlas-bak")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)

    if kind == "skill":
        overrides = settings.setdefault("skillOverrides", {})
        for name in names:
            if on:
                overrides.pop(name, None)
            else:
                overrides[name] = "off"
        if not overrides:
            settings.pop("skillOverrides")
    elif kind == "plugin":
        settings.setdefault("enabledPlugins", {}).update(dict.fromkeys(names, on))
    else:
        raise ValueError(f"unknown kind {kind!r}")

    tmp = path.with_name("settings.json.atlas-tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n")
    os.replace(tmp, path)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def _authorized(self) -> bool:
        # The token stops other sites in the browser from calling this port.
        return self.headers.get("X-Atlas-Token") == TOKEN

    def _body(self) -> dict:
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html"):
            page = render_page(scan(REPO), api_token=TOKEN)
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if not self._authorized():
            return self._json(403, {"error": "forbidden"})
        if path == "/api/data":
            return self._json(200, scan(REPO))
        if path == "/api/updates":
            return self._json(200, updates.check(list(ROOTS.values()), refresh="refresh=1" in query))
        if path.startswith("/api/jobs/") and path[10:] in updates.JOBS:
            return self._json(200, updates.job_view(updates.JOBS[path[10:]]))
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if not self._authorized():
            return self._json(403, {"error": "forbidden"})
        try:
            req = self._body()
            if self.path == "/api/toggle":
                root = ROOTS[req["root"]]
                names = [str(n) for n in req.get("names") or [req["name"]]]
                write_setting(root, req["kind"], names, bool(req["on"]))
                return self._json(200, settings_state(root))
            if self.path == "/api/reveal":
                # Only paths the scan itself reported, so the page cannot open arbitrary files.
                path = str(req["path"])
                if path not in {s["path"] for s in scan(REPO)["skills"]}:
                    raise ValueError("unknown skill path")
                subprocess.run(["open", "-R", path], check=False)
                return self._json(200, {"ok": True})
            if self.path == "/api/watch":
                return self._json(200, updates.watch(str(req["repo"]), bool(req.get("on", True)), list(ROOTS.values())))
            if self.path in ("/api/available", "/api/install", "/api/dismiss"):
                repo = updates.parse_repo(str(req["repo"]))
                paths = [str(x) for x in req["paths"]]
                if not paths or any(x.startswith("/") or ".." in x.split("/") or not x.endswith("SKILL.md") for x in paths):
                    raise ValueError("bad skill paths")
                roots = list(ROOTS.values())
                if self.path == "/api/available":
                    return self._json(200, updates.describe(repo, paths, roots))
                if self.path == "/api/dismiss":
                    return self._json(200, updates.dismiss(repo, paths, roots))
                return self._json(200, updates.job_view(updates.start_install(repo, paths, roots)))
            if self.path == "/api/undo-delete":
                return self._json(200, remove.undo())
            if self.path in ("/api/update", "/api/link", "/api/delete"):
                names = [str(n) for n in req["names"]]
                if not names or not all(SAFE_NAME.match(n) for n in names):
                    raise ValueError("bad skill names")
                roots = list(ROOTS.values())
                if self.path == "/api/delete":
                    return self._json(200, remove.trash(names, roots))
                if self.path == "/api/link":
                    return self._json(200, updates.link(names, str(req["repo"]), roots))
                return self._json(200, updates.job_view(updates.start_update(names, roots)))
        except RuntimeError as e:
            return self._json(409, {"error": str(e)})
        except (KeyError, ValueError, OSError, json.JSONDecodeError) as e:
            return self._json(400, {"error": str(e)})
        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args) -> None:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Serve the Skill Atlas with working switches.")
    ap.add_argument("--port", type=int, default=7381)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    data = scan(REPO)
    ROOTS.update({label: Path(p) for label, p in data["config_roots"].items()})

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Skill Atlas on {url}  (Ctrl-C to stop)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
