"""A static, read-only scan of one skill folder for code, network, and secret-access risks."""

from __future__ import annotations

import bisect
import hashlib
import os
import re
import stat
from pathlib import Path

MAX_BYTES = 1 << 20
MAX_FILES = 400
MAX_FINDINGS = 120
MAX_PER_RULE = 25
EXCERPT = 100
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
SCRIPT_EXT = {
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".psm1", ".bat", ".cmd",
    ".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx", ".jsx",
    ".rb", ".pl", ".php", ".lua", ".go", ".rs", ".swift", ".kt", ".java", ".applescript",
}  # fmt: skip
DOC_EXT = {".md", ".markdown", ".txt", ".mdx", ".rst", ""}
LEVELS = ("high", "medium", "info")

RULES = {
    "code": ("info", "Ships a script the agent can run."),
    "tools": ("medium", "allowed-tools grants broad power without a limit."),
    "remote-exec": ("high", "Downloads code and runs it at once."),
    "decode-exec": ("high", "Decodes hidden data and runs it."),
    "blob": ("medium", "Long encoded blob. It can hide code or data."),
    "escapes": ("medium", "A run of \\x escapes. It can hide text."),
    "secrets": ("high", "Reads a credential store or private keys."),
    "env-leak": ("high", "Sends the environment to the network."),
    "injection": ("medium", "Text that tries to steer the agent past its instructions."),
    "hidden-comment": ("medium", "Hidden HTML comment with instructions for the agent."),
    "invisible": ("medium", "Zero-width or direction-control characters. They hide text."),
    "network": ("info", "Calls this host."),
}

SHELLS = r"(?:sudo\s+)?(?:ba|z|da|k|fi)?sh|python[0-9.]*|node|perl|ruby"
FETCH = r"(?:curl|wget|iwr|irm|Invoke-WebRequest|Invoke-RestMethod)"
PATTERNS: dict[str, list[re.Pattern]] = {
    "remote-exec": [
        re.compile(rf"\b{FETCH}\b[^|\n]*\|\s*(?:{SHELLS})\b(?!\s*-m\s+json)", re.I),
        re.compile(
            r"\b(?:iex|Invoke-Expression)\b[\s(]*(?:\(?\s*)(?:iwr|irm|Invoke-Web|Invoke-Rest|New-Object\s+Net\.WebClient)",
            re.I,
        ),
        re.compile(rf"(?:\beval|\b(?:ba|z)?sh\s+-c)\s+[\"']?\$\(\s*{FETCH}\b", re.I),
        re.compile(rf"(?:\bsource|\.|\b(?:ba|z)?sh)\s+<\(\s*{FETCH}\b", re.I),
        re.compile(
            r"\bpython[0-9.]*\s+-c\s+[\"'].*(?:urllib|requests|http\.client|socket)\b.*\bexec\(",
            re.I,
        ),
    ],
    "decode-exec": [
        re.compile(rf"\bbase64\s+(?:-d|-D|--decode)\b[^|\n]*\|\s*(?:{SHELLS})\b", re.I),
        re.compile(r"\beval\s*\(\s*(?:atob|unescape|Buffer\.from)\s*\(", re.I),
        re.compile(
            r"\b(?:exec|eval)\s*\(\s*(?:base64\.b64decode|zlib\.decompress|codecs\.decode|bytes\.fromhex)",
            re.I,
        ),
    ],
    "escapes": [re.compile(r"(?:\\x[0-9a-fA-F]{2}){12,}")],
    "secrets": [
        re.compile(
            r"(?:~|\$HOME|\$\{HOME\}|expanduser\([\"']~)/\.(?:ssh|aws|gnupg|kube|docker/config|netrc|npmrc|pypirc)\b"
        ),
        re.compile(r"\bid_(?:rsa|ed25519|ecdsa)\b(?!\.pub)"),
        re.compile(r"\bsecurity\s+(?:find|dump)-(?:generic|internet)-password\b|\bdump-keychain\b"),
        re.compile(r"\bsecret-tool\s+lookup\b|\bkeyring\.get_password\b"),
        re.compile(r"\b(?:cat|less|head|tail|cp|scp)\s+(?:[^\s|;]*/)?\.env\b(?![.\w-])"),
        re.compile(
            r"(?:Chrome|Chromium|Firefox|Brave|Safari)\b.*/"
            r"(?:Cookies|Login Data|key[34]\.db|logins\.json)\b"
        ),
    ],
}
ENV_DUMP = re.compile(
    r"\$\((?:env|printenv)\)|\b(?:env|printenv)\s*\||dict\(os\.environ\)|os\.environ\.copy\(\)"
    r"|json\.dumps\(\s*(?:dict\()?os\.environ|JSON\.stringify\(\s*process\.env\s*\)"
)
NET = re.compile(r"\b(?:curl|wget|requests\.(?:post|put)|fetch\(|urlopen|http\.client|nc\s)", re.I)
INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding|system)\s+"
    r"(?:instructions?|prompts?|messages?|rules|context)\b"
    r"|\b(?:do\s+not|don'?t|never)\s+(?:tell|inform|show|mention\s+(?:this|it)\s+to)\s+the\s+user\b"
    r"|\bwithout\s+(?:telling|asking|informing|notifying)\s+the\s+user\b",
    re.I,
)
QUOTES = {'"', "'", "“", "‘", "`"}
COMMENT = re.compile(r"<!--(.*?)-->", re.S)
IMPERATIVE = re.compile(
    r"\b(?:ignore|disregard|you\s+(?:must|should|are)|always|never|do\s+not|assistant|claude|the\s+agent|"
    r"system\s+prompt|instructions?|run|execute|send|upload)\b",
    re.I,
)
INVISIBLE = re.compile("[​‌‍⁠⁢⁣⁤‪-‮⁦-⁩﻿]")
BLOB = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
# Words a rule's patterns cannot match without, so most files skip the regex work.
HINTS = {
    "remote-exec": ("curl", "wget", "iwr", "irm", "invoke-", "iex"),
    "decode-exec": ("base64", "atob", "unescape", "buffer.from", "fromhex", "decompress"),
    "escapes": ("\\x",),
    "secrets": (".ssh", ".aws", ".gnupg", ".kube", ".docker", "netrc", "npmrc", "pypirc", "id_",
                "-password", "dump-keychain", "secret-tool", "keyring", ".env", "logins.json",
                "login data", "cookies", "key3.db", "key4.db"),
    "env-leak": ("env",),
    "injection": ("the user", "previous", "prior", "above", "earlier", "preceding", "system"),
}  # fmt: skip
DATA_URI = re.compile(r"data:[\w.+-]+/[\w.+-]+;base64,$")
HOST = re.compile(
    r"\b(?:https?|wss?|ftp)://([A-Za-z0-9.-]+\.[A-Za-z]{2,}|\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?"
)
TEST_FILE = re.compile(r"(?:^|/)(?:tests?|__tests__|fixtures)/|[._-](?:test|spec)\.\w+$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "example.com", "example.org", "example.net"}
TOOL = re.compile(r"[A-Za-z_][\w-]*(?:\([^)]*\))?")
UNLIMITED = re.compile(r"^(Bash|Write|Edit|MultiEdit|NotebookEdit|WebFetch)(?:\(\s*\*?\s*\))?$")

_CACHE: dict[str, tuple[str, dict]] = {}
_FILES: dict[tuple, list[dict]] = {}


def _files(root: Path) -> list[tuple[Path, os.stat_result]]:
    out: list[tuple[Path, os.stat_result]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath, name)
            try:
                st = p.lstat()
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                out.append((p, st))
            if len(out) >= MAX_FILES:
                return out
    return out


def _signature(files: list[tuple[Path, os.stat_result]], tools: list[str]) -> str:
    h = hashlib.sha1("\0".join(tools).encode())
    for p, st in files:
        h.update(f"{p}\0{st.st_size}\0{st.st_mtime_ns}\0{st.st_mode}\n".encode())
    return h.hexdigest()


def _excerpt(line: str, start: int = 0, end: int | None = None) -> str:
    """The text around a match, trimmed. Long encoded runs are cut, so no secret leaks out."""
    end = len(line) if end is None else end
    lo = max(0, start - 30)
    text = line[lo : max(end, lo + EXCERPT)][:EXCERPT].strip()
    text = re.sub(r"[A-Za-z0-9+/=_-]{40,}", lambda m: m.group(0)[:16] + "…", text)
    text = INVISIBLE.sub(lambda m: f"<U+{ord(m.group(0)):04X}>", text)
    return ("…" if lo else "") + text + ("…" if len(line) > lo + EXCERPT else "")


def _is_script(p: Path, st: os.stat_result, head: bytes) -> bool:
    return p.suffix.lower() in SCRIPT_EXT or head.startswith(b"#!") or bool(st.st_mode & 0o111)


def _tool_findings(skill_dir: Path, tools: list[str]) -> list[dict]:
    md = skill_dir / "SKILL.md"
    try:
        lines = md.read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        lines = []
    line = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("allowed-tools")), 1)
    out = []
    for item in tools:
        for tool in TOOL.findall(item):
            m = UNLIMITED.match(tool.strip())
            if not m:
                continue
            what = {
                "Bash": "Bash with no command limit can run any shell command.",
                "WebFetch": "WebFetch with no domain limit can reach any site.",
            }.get(m.group(1), f"{m.group(1)} with no path limit can change any file.")
            out.append(_finding("tools", "SKILL.md", line, tool.strip(), what))
    return out


def _finding(rule: str, file: str, line: int, excerpt: str, message: str = "") -> dict:
    level, default = RULES[rule]
    return {
        "rule": rule,
        "level": level,
        "file": file,
        "line": line,
        "excerpt": excerpt,
        "message": message or default,
    }


class _Text:
    """One file's text with fast offset-to-line lookup."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def at(self, pos: int) -> tuple[int, str, int]:
        """The 1-based line number, the line text, and pos as an offset in that line."""
        i = bisect.bisect_right(self.starts, pos)
        lo = self.starts[i - 1]
        hi = self.starts[i] - 1 if i < len(self.starts) else len(self.text)
        return i, self.text[lo:hi], pos - lo

    def hit(self, rule: str, m: re.Match, message: str = "") -> dict:
        n, line, off = self.at(m.start())
        return _finding(rule, "", n, _excerpt(line, off, off + len(m.group(0))), message)


def _scan_text(rel: str, text: str, script: bool, doc: bool) -> list[dict]:
    t = _Text(text)
    out: list[dict] = []
    longest = max((b - a for a, b in zip(t.starts, t.starts[1:], strict=False)), default=len(text))
    minified = rel.endswith((".min.js", ".min.css", ".map")) or (script and longest > 2000)
    seen: set[tuple[str, int]] = set()

    def add(f: dict) -> None:
        if (f["rule"], f["line"]) not in seen:
            seen.add((f["rule"], f["line"]))
            out.append(f)

    low = text.lower()
    hinted = {r for r, words in HINTS.items() if any(w in low for w in words)}
    for rule, pats in PATTERNS.items():
        if rule not in hinted or (minified and rule == "escapes"):
            continue
        for pat in pats:
            for m in pat.finditer(text):
                f = t.hit(rule, m)
                if rule == "remote-exec" and doc:
                    f["level"], f["message"] = (
                        "medium",
                        "Docs tell the agent to pipe a download into a shell.",
                    )
                add(f)
    for m in ENV_DUMP.finditer(text if "env-leak" in hinted else ""):
        if NET.search(t.at(m.start())[1]):
            add(t.hit("env-leak", m))
    if not minified:
        for m in BLOB.finditer(text):
            if DATA_URI.search(text[max(0, m.start() - 60) : m.start()]):
                continue
            if text[m.end() : m.end() + 1].isalnum() or text[m.start() - 1 : m.start()] in (
                "_",
                "-",
            ):
                continue
            kind = "hex" if re.fullmatch(r"[0-9a-fA-F]+", m.group(0)) else "base64"
            add(
                t.hit(
                    "blob",
                    m,
                    f"Long {kind} blob ({len(m.group(0))} chars). It can hide code or data.",
                )
            )
    if script and not TEST_FILE.search(rel):
        hosts: set[str] = set()
        for m in HOST.finditer(text):
            host = m.group(1).lower().rstrip(".")
            if (
                host in hosts
                or host in LOCAL_HOSTS
                or host.endswith((".local", ".test", ".invalid"))
            ):
                continue
            hosts.add(host)
            out.append({**t.hit("network", m, f"Calls {host}."), "host": host})
    if doc:
        for m in INJECTION.finditer(text if "injection" in hinted else ""):
            # A quoted phrase is usually a warning about injection, not an attempt.
            if text[max(0, m.start() - 1) : m.start()] not in QUOTES:
                add(t.hit("injection", m))
        for m in COMMENT.finditer(text):
            body = " ".join(m.group(1).split())
            if len(body) >= 40 and len(IMPERATIVE.findall(body)) >= 2:
                f = t.hit("hidden-comment", m)
                f["excerpt"] = _excerpt("<!-- " + body + " -->")
                add(f)
    for m in INVISIBLE.finditer(text, 1 if text.startswith("\ufeff") else 0):
        add(t.hit("invisible", m))
    return out


def _file_findings(rel: str, data: bytes, script: bool, doc: bool) -> list[dict]:
    """Findings for one file. Copies of a skill share them, keyed by content."""
    key = (hashlib.sha1(data).hexdigest(), rel, script, doc)
    hit = _FILES.get(key)
    if hit is None:
        if len(_FILES) > 50_000:
            _FILES.clear()
        hit = _FILES[key] = _scan_text(rel, data.decode("utf-8", "replace"), script, doc)
    return [{**f, "file": rel} for f in hit]


def _build(skill_dir: Path, files: list[tuple[Path, os.stat_result]], tools: list[str]) -> dict:
    findings = _tool_findings(skill_dir, tools)
    hosts: dict[str, dict] = {}
    skipped = 0
    for p, st in files:
        rel = p.relative_to(skill_dir).as_posix()
        if st.st_size > MAX_BYTES:
            skipped += 1
            continue
        try:
            data = p.read_bytes()
        except OSError:
            skipped += 1
            continue
        if b"\0" in data[:8192]:
            continue
        script = _is_script(p, st, data[:2])
        if script:
            first = data[:200].split(b"\n", 1)[0].decode("utf-8", "replace")
            findings.append(
                _finding("code", rel, 1, _excerpt(first) if first.startswith("#!") else p.name)
            )
        doc = p.suffix.lower() in DOC_EXT and not script
        for f in _file_findings(rel, data, script, doc):
            if f["rule"] != "network":
                findings.append(f)
            else:
                hosts.setdefault(f["host"], f)
    findings += hosts.values()

    counts = dict.fromkeys(LEVELS, 0)
    by_rule: dict[str, int] = {}
    kept: list[dict] = []
    for f in sorted(findings, key=lambda f: LEVELS.index(f["level"])):
        counts[f["level"]] += 1
        by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
        if by_rule[f["rule"]] <= MAX_PER_RULE and len(kept) < MAX_FINDINGS:
            kept.append(f)
    level = next((lv for lv in LEVELS if counts[lv]), "none")
    return {
        "level": level,
        "counts": counts,
        "rules": by_rule,
        "code": by_rule.get("code", 0),
        "hosts": sorted(hosts),
        "findings": kept,
        "truncated": len(findings) - len(kept),
        "files": len(files),
        "skipped": skipped,
    }


def report(skill_dir: Path, tools: list[str] | None = None) -> dict:
    """Every finding for one skill folder. Cached until a file in it changes."""
    tools = list(tools or [])
    files = _files(skill_dir)
    sig = _signature(files, tools)
    key = str(skill_dir)
    hit = _CACHE.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    rep = _build(skill_dir, files, tools)
    _CACHE[key] = (sig, rep)
    return rep


def summary(skill_dir: Path, tools: list[str] | None = None) -> dict:
    """The short form kept on each scan record."""
    rep = report(skill_dir, tools)
    return {k: rep[k] for k in ("level", "counts", "code", "rules")}
