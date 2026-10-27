import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import serve


@pytest.fixture
def server_root(tmp_path):
    return tmp_path


@pytest.fixture
def server(server_root):
    serve.ROOTS.clear()
    serve.ROOTS["personal"] = server_root
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    serve.ROOTS.clear()


def raw(url, method="GET", body=b"", headers=None, token=serve.TOKEN):
    req = urllib.request.Request(
        url,
        data=body if method == "POST" else None,
        method=method,
        headers={"X-Atlas-Token": token, **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), e.headers


def get(url, token=serve.TOKEN):
    return raw(url, token=token)[:2]


def post(url, body, token=serve.TOKEN):
    return raw(url, "POST", json.dumps(body).encode(), token=token)[:2]
