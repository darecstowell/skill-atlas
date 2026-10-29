"""Serve the atlas on localhost so it can toggle, update, link, and delete skills."""

from __future__ import annotations

import argparse
import errno
import json
import os
import secrets
import shutil as shutil
import sys
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from . import REPO, WEB, profiles, usage
from . import assets as assets
from .build import render_page
from .core.atlas import SAFE_NAME, Atlas, config_roots, source_hash
from .core.atlas import write_setting as write_setting
from .core.atlas import write_settings as write_settings
from .scan import config_path, scan, write_user_config

TEXTURES = WEB / "bg"
TOKEN = secrets.token_urlsafe(24)
ROOTS: dict[str, Path] = {}
MAX_BODY = 1 << 20
RESTART = "Stop ./atlas (Ctrl-C) and start it again"
BUILD = source_hash()


def server_info() -> dict:
    """The build this server runs, and whether the code on disk is newer."""
    return {"build": BUILD, "stale": source_hash() != BUILD}


# The lambda reads `scan` at each call, so tests that patch serve.scan reach the Atlas.
ATLAS = Atlas(ROOTS, REPO, scanner=lambda repo: scan(repo), info=server_info)
LAST_SCAN = ATLAS.last_scan
page_scan = ATLAS.page_scan
scanned_record = ATLAS.scanned_record


def str_list(req: dict, key: str) -> list[str]:
    v = req.get(key)
    if not isinstance(v, list):
        raise ValueError(f"{key} must be a list")
    return [str(x) for x in v]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Atlas-Build", BUILD)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # the browser left; nobody waits for this answer

    def _json(self, code: int, data) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def _authorized(self) -> bool:
        # The token stops other sites in the browser from calling this port.
        return self.headers.get("X-Atlas-Token") == TOKEN

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 <= length <= MAX_BODY:
            self.close_connection = True
            raise OverflowError("request body is too large")
        req = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(req, dict):
            raise ValueError("request body must be a JSON object")
        return req

    def _not_found(self, path: str) -> None:
        if server_info()["stale"]:
            msg = f"This server is older than the page and has no {path}. {RESTART}."
        else:
            msg = f"unknown API call {path}"
        self._json(404, {"error": msg, "server": server_info()})

    def _answer(self, handle) -> None:
        """Run one request and always answer with JSON, even when the handler fails."""
        if not self._authorized():
            msg = "This page is from an earlier run of the server. Reload the page."
            return self._json(403, {"error": msg})
        try:
            handle()
        except OverflowError as e:
            self._json(413, {"error": str(e)})
        except NotImplementedError as e:
            self._json(501, {"error": str(e)})
        except RuntimeError as e:
            self._json(409, {"error": str(e)})
        except (KeyError, TypeError, AttributeError) as e:
            self._json(400, {"error": f"bad request: {e!r}"})
        except (ValueError, OSError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": f"server error: {e!r}"})

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html"):
            try:
                page = render_page(ATLAS.data(), api_token=TOKEN)
            except Exception as e:
                traceback.print_exc()
                msg = f"Skill Atlas could not build the page: {e!r}\n"
                return self._send(500, msg.encode(), "text/plain; charset=utf-8")
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if path.startswith("/bg/"):
            name = path[4:]
            if SAFE_NAME.match(name) and name.endswith(".webp") and (TEXTURES / name).is_file():
                return self._send(200, (TEXTURES / name).read_bytes(), "image/webp")
            return self._json(404, {"error": "not found"})
        if not path.startswith("/api/"):
            return self._json(404, {"error": "not found"})
        self._answer(lambda: self._get(path, query))

    def _get(self, path: str, query: str) -> None:
        q = {k: v[0] for k, v in parse_qs(query).items()}
        if path == "/api/version":
            return self._json(200, server_info())
        if path == "/api/data":
            return self._json(200, ATLAS.data())
        if path == "/api/profiles":
            return self._json(200, ATLAS.profiles())
        if path == "/api/usage":
            return self._json(200, ATLAS.usage())
        if path == "/api/updates":
            return self._json(200, ATLAS.updates(refresh=q.get("refresh") == "1"))
        if path == "/api/skill":
            return self._json(200, {"text": ATLAS.skill_text(q.get("path", ""))})
        if path == "/api/diff":
            return self._json(200, ATLAS.diff(q.get("name", "")))
        if path == "/api/history":
            return self._json(200, ATLAS.history(q.get("name", "")))
        if path == "/api/export":
            return self._json(200, ATLAS.export())
        if path == "/api/restore":
            return self._json(200, ATLAS.restore_plan())
        if path == "/api/compare":
            return self._json(200, ATLAS.compare(q.get("a", ""), q.get("b", "")))
        if path == "/api/security":
            return self._json(200, ATLAS.security(q.get("path", "")))
        if path.startswith("/api/jobs/"):
            job = ATLAS.job(path[10:])
            if job is None:
                return self._json(404, {"error": "that job is gone. The server may have restarted"})
            return self._json(200, job)
        self._not_found(path)

    def do_POST(self) -> None:
        self._answer(lambda: self._post(self.path.partition("?")[0]))

    def _post(self, path: str) -> None:
        req = self._body()
        if path == "/api/toggle":
            root = str(req["root"])
            names = str_list(req, "names") if req.get("names") else [str(req["name"])]
            return self._json(200, ATLAS.toggle(root, req["kind"], names, bool(req["on"])))
        if path == "/api/reveal":
            ATLAS.reveal(str(req["path"]))
            return self._json(200, {"ok": True})
        if path == "/api/repos":
            return self._json(200, ATLAS.repos(str_list(req, "repos")))
        if path == "/api/watch":
            on = bool(req.get("on", True))
            return self._json(200, ATLAS.watch(str(req["repo"]), on))
        if path in ("/api/available", "/api/install", "/api/dismiss"):
            repo, paths = str(req["repo"]), str_list(req, "paths")
            if path == "/api/available":
                return self._json(200, ATLAS.available(repo, paths))
            if path == "/api/dismiss":
                return self._json(200, ATLAS.dismiss(repo, paths))
            return self._json(200, ATLAS.install(repo, paths))
        if path == "/api/rollback":
            return self._json(200, ATLAS.rollback(str(req["name"]), str(req["id"])))
        if path.startswith("/api/profiles/") and path[14:] in profiles.ACTIONS:
            return self._json(200, ATLAS.profile(path[14:], req))
        if path == "/api/import/plan":
            return self._json(200, ATLAS.import_plan(req))
        if path == "/api/import/apply":
            return self._json(200, ATLAS.import_apply(req))
        if path == "/api/undo-delete":
            return self._json(200, ATLAS.undo_delete())
        if path in ("/api/update", "/api/link", "/api/delete"):
            names = str_list(req, "names")
            if path == "/api/delete":
                return self._json(200, ATLAS.delete(names))
            if path == "/api/link":
                return self._json(200, ATLAS.link(names, str(req["repo"])))
            return self._json(200, ATLAS.update(names))
        self._not_found(path)

    def log_message(self, fmt, *args) -> None:
        pass


def bind(port: int, tries: int = 20) -> ThreadingHTTPServer:
    """The first free port from `port` up, so a second atlas or another app is no blocker."""
    for p in range(port, port + tries):
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), Handler)
        except OSError as e:
            # Windows refuses ports it reserves with EACCES, not EADDRINUSE.
            if e.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
    raise SystemExit(f"No free port from {port} to {port + tries - 1}.")


def init(force: bool) -> int:
    try:
        path = write_user_config(force)
    except FileExistsError as e:
        print(f"{e} already exists. Edit it, or run ./atlas init --force to replace it.")
        return 1
    print(f"Wrote {path}:\n{path.read_text(encoding='utf-8')}")
    print("Add folders to project_roots to see project skills. Rename a root to change its tab.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Serve the Skill Atlas with working switches.")
    ap.add_argument("command", nargs="?", choices=["init"], help="init: write a starter config")
    ap.add_argument("--port", type=int, default=7381)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--force", action="store_true", help="with init: replace an existing config")
    args = ap.parse_args()
    if args.command == "init":
        return init(args.force)

    ROOTS.update(config_roots(REPO))
    if not ATLAS.page_scan()["harnesses"]:
        where = config_path(REPO)
        print(f"No agent harness found. Set config_roots in {where}.", file=sys.stderr)
    usage.start(list(ROOTS.values()))

    server = bind(args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Skill Atlas on {url}  (Ctrl-C to stop)")
    if os.environ.get("SSH_TTY"):
        print('Over SSH? Run "atlas tui" for the terminal version.')
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass  # no browser here; the URL above is enough
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
