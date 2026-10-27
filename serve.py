#!/usr/bin/env python3
"""Serve the atlas on localhost so it can toggle, update, link, and delete skills."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import assets
import remove
import updates
import usage
from build import render_page
from scan import read_json_strict, scan, settings_state

REPO = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(24)
ROOTS: dict[str, Path] = {}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][\w.-]*$")
MAX_BODY = 1 << 20
RESTART = "Stop ./atlas (Ctrl-C) and start it again"


def source_hash() -> str:
    """A hash of the Python files, so a server can tell that its code changed on disk."""
    h = hashlib.sha256()
    for path in sorted(REPO.glob("*.py")):
        try:
            h.update(path.name.encode() + b"\0" + path.read_bytes())
        except OSError:
            continue
    return h.hexdigest()[:12]


BUILD = source_hash()


def server_info() -> dict:
    """The build this server runs, and whether the code on disk is newer."""
    return {"build": BUILD, "stale": source_hash() != BUILD}


def write_setting(root: Path, kind: str, names: list[str], on: bool) -> None:
    if kind not in ("skill", "plugin"):
        raise ValueError(f"unknown kind {kind!r}")
    path = root / "settings.json"
    # Write through a symlink, so a settings file kept in a dotfiles repo stays linked.
    target = path.resolve()
    settings = read_json_strict(target)
    if target.exists() and not os.access(target, os.W_OK):
        raise ValueError(f"{target} is read-only, so the atlas cannot change it")
    backup = path.with_name("settings.json.atlas-bak")
    if target.exists() and not backup.exists():
        shutil.copy2(target, backup)

    key = "skillOverrides" if kind == "skill" else "enabledPlugins"
    section = settings.get(key, {})
    if not isinstance(section, dict):
        raise ValueError(f"{key} in {target} is not an object. Fix the file, then try again.")
    if kind == "skill":
        for name in names:
            if on:
                section.pop(name, None)
            else:
                section[name] = "off"
    else:
        section.update(dict.fromkeys(names, on))
    if section:
        settings[key] = section
    else:
        settings.pop(key, None)

    tmp = target.with_name("settings.json.atlas-tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    if target.exists():
        shutil.copymode(target, tmp)
    os.replace(tmp, target)


def reveal(path: str) -> None:
    """Show a file in the system file manager."""
    if sys.platform == "darwin":
        cmd = ["open", "-R", path]
    elif os.name == "nt":
        cmd = ["explorer", f"/select,{path}"]
    else:
        cmd = ["xdg-open", str(Path(path).parent)]
    if not shutil.which(cmd[0]):
        raise NotImplementedError(f"cannot show files on this system: {cmd[0]} is not installed")
    try:
        subprocess.run(cmd, check=False, timeout=10, capture_output=True)
    except subprocess.TimeoutExpired:
        pass  # the file manager is open; it only did not exit


def roots() -> list[Path]:
    if not ROOTS:
        raise ValueError("no Claude config folder found. Set config_roots in config.json")
    return list(ROOTS.values())


def scanned_path(path: str) -> str:
    """Only paths the scan itself reported, so the page cannot reach arbitrary files."""
    if path not in {s["path"] for s in scan(REPO)["skills"]}:
        raise ValueError("unknown skill path")
    return path


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
                data = {**scan(REPO), "server": server_info()}
                page = render_page(data, api_token=TOKEN)
            except Exception as e:
                traceback.print_exc()
                msg = f"Skill Atlas could not build the page: {e!r}\n"
                return self._send(500, msg.encode(), "text/plain; charset=utf-8")
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if not path.startswith("/api/"):
            return self._json(404, {"error": "not found"})
        self._answer(lambda: self._get(path, query))

    def _get(self, path: str, query: str) -> None:
        if path == "/api/version":
            return self._json(200, server_info())
        if path == "/api/data":
            return self._json(200, {**scan(REPO), "server": server_info()})
        if path == "/api/usage":
            return self._json(200, usage.snapshot(list(ROOTS.values())))
        if path == "/api/updates":
            return self._json(200, updates.check(roots(), refresh="refresh=1" in query))
        if path == "/api/skill":
            want = scanned_path(parse_qs(query).get("path", [""])[0])
            text = Path(want).read_text(encoding="utf-8", errors="replace")
            return self._json(200, {"text": text})
        if path.startswith("/api/jobs/"):
            job = updates.JOBS.get(path[10:])
            if job is None:
                return self._json(404, {"error": "that job is gone. The server may have restarted"})
            return self._json(200, updates.job_view(job))
        self._not_found(path)

    def do_POST(self) -> None:
        self._answer(lambda: self._post(self.path.partition("?")[0]))

    def _post(self, path: str) -> None:
        req = self._body()
        if path == "/api/toggle":
            root = ROOTS[req["root"]]
            names = str_list(req, "names") if req.get("names") else [str(req["name"])]
            write_setting(root, req["kind"], names, bool(req["on"]))
            return self._json(200, settings_state(root))
        if path == "/api/reveal":
            reveal(scanned_path(str(req["path"])))
            return self._json(200, {"ok": True})
        if path == "/api/repos":
            repos = sorted({updates.parse_repo(r) for r in str_list(req, "repos")})[:50]
            return self._json(200, assets.fetch(repos))
        if path == "/api/watch":
            on = bool(req.get("on", True))
            return self._json(200, updates.watch(str(req["repo"]), on, roots()))
        if path in ("/api/available", "/api/install", "/api/dismiss"):
            repo = updates.parse_repo(str(req["repo"]))
            paths = str_list(req, "paths")
            if not paths or any(
                x.startswith("/") or ".." in x.split("/") or not x.endswith("SKILL.md")
                for x in paths
            ):
                raise ValueError("bad skill paths")
            if path == "/api/available":
                return self._json(200, updates.describe(repo, paths, roots()))
            if path == "/api/dismiss":
                return self._json(200, updates.dismiss(repo, paths, roots()))
            return self._json(200, updates.job_view(updates.start_install(repo, paths, roots())))
        if path == "/api/undo-delete":
            return self._json(200, remove.undo())
        if path in ("/api/update", "/api/link", "/api/delete"):
            names = str_list(req, "names")
            if not names or not all(SAFE_NAME.match(n) for n in names):
                raise ValueError("bad skill names")
            if path == "/api/delete":
                return self._json(200, remove.trash(names, roots()))
            if path == "/api/link":
                return self._json(200, updates.link(names, str(req["repo"]), roots()))
            return self._json(200, updates.job_view(updates.start_update(names, roots())))
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Serve the Skill Atlas with working switches.")
    ap.add_argument("--port", type=int, default=7381)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    data = scan(REPO)
    ROOTS.update({label: Path(p) for label, p in data["config_roots"].items()})
    if not ROOTS:
        print("No Claude config folder found. Set config_roots in config.json.", file=sys.stderr)
    usage.start(list(ROOTS.values()))

    server = bind(args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Skill Atlas on {url}  (Ctrl-C to stop)")
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
