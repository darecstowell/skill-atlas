"""The agent harnesses that load skills: where each one looks, and how each turns a skill off."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import scan


@dataclass
class Harness:
    id: str
    name: str
    home: Path
    dirs: list[Path]
    switch: str | None = None
    config: Path | None = None
    label: str = ""

    def view(self) -> dict:
        return {
            "name": self.name,
            "label": self.label or self.name,
            "home": str(self.home),
            "switch": self.switch,
            "config": str(self.config) if self.config else "",
        }


def _env_dir(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or default).expanduser()


def known() -> list[Harness]:
    """Every harness other than Claude Code, with the global skill folders each one reads."""
    home = Path.home()
    xdg = _env_dir("XDG_CONFIG_HOME", "~/.config")
    agents, claude = home / ".agents" / "skills", home / ".claude" / "skills"
    codex = _env_dir("CODEX_HOME", "~/.codex")
    gemini = home / ".gemini"
    copilot = _env_dir("COPILOT_HOME", "~/.copilot")
    opencode = xdg / "opencode"
    return [
        Harness(
            "codex", "Codex", codex, [agents, codex / "skills"], "codex", codex / "config.toml"
        ),
        Harness(
            "cursor",
            "Cursor",
            home / ".cursor",
            [agents, home / ".cursor" / "skills", claude, codex / "skills"],
        ),
        Harness(
            "gemini-cli",
            "Gemini CLI",
            gemini,
            [gemini / "skills", agents],
            "gemini",
            gemini / "settings.json",
        ),
        Harness(
            "antigravity",
            "Antigravity",
            gemini / "antigravity",
            [gemini / "antigravity" / "skills"],
        ),
        Harness(
            "copilot-cli",
            "Copilot CLI",
            copilot,
            # COPILOT_HOME also stops the ~/.agents load.
            [copilot / "skills"] + ([] if os.environ.get("COPILOT_HOME") else [agents]),
            "copilot",
            copilot / "settings.json",
        ),
        Harness(
            "opencode",
            "OpenCode",
            opencode,
            [opencode / "skills", opencode / "skill", claude, agents],
            "opencode",
            opencode / "opencode.json",
        ),
        Harness(
            "amp",
            "Amp",
            xdg / "amp",
            [xdg / "agents" / "skills", agents, xdg / "amp" / "skills", claude],
        ),
        Harness(
            "goose",
            "Goose",
            xdg / "goose",
            [agents, xdg / "goose" / "skills", claude, xdg / "agents" / "skills"],
        ),
        Harness(
            "windsurf",
            "Windsurf",
            home / ".codeium" / "windsurf",
            [xdg / "devin" / "skills", home / ".codeium" / "windsurf" / "skills"],
        ),
        Harness("cline", "Cline", home / ".cline", [home / ".cline" / "skills", agents]),
        Harness("kiro", "Kiro", home / ".kiro", [home / ".kiro" / "skills"]),
        Harness("roo", "Roo Code", home / ".roo", [home / ".roo" / "skills", agents]),
    ]


def claude_code(roots: dict[str, Path]) -> list[Harness]:
    """One Claude Code harness per config root, named after the root when there are several."""
    many = len(roots) > 1
    return [
        Harness(
            "claude-code" + (f":{label}" if many else ""),
            "Claude Code",
            root,
            [root / "skills"],
            "claude",
            root / "settings.json",
            f"Claude Code · {label}" if many else "Claude Code",
        )
        for label, root in roots.items()
    ]


def detect(roots: dict[str, Path], only: list[str] | None = None) -> list[Harness]:
    """Claude Code roots, then each other harness whose home folder exists here."""
    found = claude_code(roots) + [h for h in known() if h.home.is_dir()]
    return [h for h in found if only is None or h.id.split(":")[0] in only or h.id in only]


# --------------------------------------------------------------------------
# switches
# --------------------------------------------------------------------------

TOML_BLOCK = re.compile(r"^\[\[skills\.config\]\]\s*$")
TOML_TABLE = re.compile(r"^\s*\[")
TOML_PAIR = re.compile(
    r"""^\s*(path|name|enabled)\s*=\s*("(?:[^"\\]|\\.)*"|'[^']*'|true|false)\s*(#.*)?$"""
)


def _toml_value(v: str):
    if v in ("true", "false"):
        return v == "true"
    return json.loads(v) if v.startswith('"') else v[1:-1]


def codex_blocks(text: str) -> list[dict]:
    """The [[skills.config]] tables in a Codex config.toml, with their line spans."""
    lines = text.split("\n")
    out: list[dict] = []
    for i, line in enumerate(lines):
        if TOML_BLOCK.match(line):
            out.append({"start": i, "end": len(lines)})
        elif out and out[-1]["end"] == len(lines) and TOML_TABLE.match(line):
            out[-1]["end"] = i
        elif out and out[-1]["end"] == len(lines) and (m := TOML_PAIR.match(line)):
            out[-1][m.group(1)] = _toml_value(m.group(2))
    return out


def _real(p: str) -> str:
    return str(Path(p).expanduser().resolve())


def off_names(h: Harness, skills: list[dict]) -> list[str]:
    """Names of the skills this harness loads that its config turns off."""
    if h.config is None:
        return []
    mine = [s for s in skills if h.id in s.get("harnesses", [])]
    if h.switch == "codex":
        try:
            blocks = codex_blocks(h.config.read_text(encoding="utf-8"))
        except OSError:
            blocks = []
        off_paths = {_real(b["path"]) for b in blocks if b.get("enabled") is False and "path" in b}
        off = {b["name"] for b in blocks if b.get("enabled") is False and "name" in b}
        return sorted(
            {s["name"] for s in mine if s["name"] in off or _real(s["path"]) in off_paths}
        )
    cfg = scan.read_json(h.config)
    if h.switch == "gemini":
        listed = set(
            _str_list(
                (cfg.get("skills") or {}).get("disabled")
                if isinstance(cfg.get("skills"), dict)
                else []
            )
        )
        return sorted({s["name"] for s in mine if s["name"] in listed})
    if h.switch == "copilot":
        listed = set(_str_list(cfg.get("disabledSkills")))
        return sorted({s["name"] for s in mine if s["name"] in listed})
    if h.switch == "opencode":
        return sorted({s["name"] for s in mine if _opencode_action(cfg, s["name"]) == "deny"})
    return []


def _str_list(v) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else []


def _opencode_rules(cfg: dict) -> dict:
    perm = cfg.get("permission")
    rules = perm.get("skill") if isinstance(perm, dict) else None
    return rules if isinstance(rules, dict) else {}


def _opencode_action(cfg: dict, name: str) -> str:
    # The last pattern that matches wins, so an exact name after "*" overrides it.
    action = "allow"
    for pattern, value in _opencode_rules(cfg).items():
        if fnmatch.fnmatchcase(name, str(pattern)):
            action = str(value)
    return action


def state(h: Harness, skills: list[dict]) -> dict:
    """What the page needs to draw this harness's switches."""
    if not h.switch or h.switch == "claude":
        return {}
    return {"path": str(h.config), "off": off_names(h, skills)}


def _write(path: Path, text: str) -> None:
    """Back up once, then replace the file in one step. Writes through a symlink."""
    target = path.resolve()
    if target.exists() and not os.access(target, os.W_OK):
        raise ValueError(f"{target} is read-only, so the atlas cannot change it")
    backup = path.with_name(path.name + ".atlas-bak")
    if target.exists() and not backup.exists():
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".atlas-tmp")
    tmp.write_text(text, encoding="utf-8")
    if target.exists():
        shutil.copymode(target, tmp)
    os.replace(tmp, target)


def _write_json(path: Path, data: dict) -> None:
    _write(path, json.dumps(data, indent=2) + "\n")


def set_skills(h: Harness, skills: list[dict], on: bool) -> None:
    """Turn these skills on or off in one harness's own config file."""
    set_skill_states(h, [(s, on) for s in skills])


def set_skill_states(h: Harness, changes: list[tuple[dict, bool]]) -> None:
    """Turn each skill on or off, with one write of the harness's config file."""
    if not h.switch or h.switch == "claude" or h.config is None:
        raise NotImplementedError(f"{h.name} has no per-skill switch")
    want = {s["name"]: on for s, on in changes}
    if h.switch == "codex":
        _set_codex(h.config, changes)
        return
    cfg = scan.read_json_strict(h.config.resolve())
    if h.switch in ("gemini", "copilot"):
        if h.switch == "gemini":
            section = cfg.setdefault("skills", {})
            if not isinstance(section, dict):
                raise ValueError(
                    f"skills in {h.config} is not an object. Fix the file, then try again."
                )
            holder, key = section, "disabled"
        else:
            holder, key = cfg, "disabledSkills"
        current = [n for n in _str_list(holder.get(key)) if want.get(n) is not True]
        holder[key] = current + sorted(n for n, on in want.items() if not on and n not in current)
        _write_json(h.config, cfg)
        return
    perm = cfg.setdefault("permission", {})
    if not isinstance(perm, dict):
        raise ValueError(
            f"permission in {h.config} is not an object. Fix the file, then try again."
        )
    rules = perm.setdefault("skill", {})
    if not isinstance(rules, dict):
        raise ValueError(
            f"permission.skill in {h.config} is not an object. Fix the file, then try again."
        )
    for name, on in sorted(want.items()):
        rules.pop(name, None)
        if on and _opencode_action(cfg, name) == "deny":
            rules[name] = "allow"
        elif not on:
            rules[name] = "deny"
    _write_json(h.config, cfg)


def _set_codex(config: Path, changes: list[tuple[dict, bool]]) -> None:
    """Off adds an enabled = false table per SKILL.md path; on removes the tables that match."""
    skills = [s for s, _ in changes]
    try:
        text = config.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    lines = text.split("\n")
    want = {_real(s["path"]): s for s in skills}
    names = {s["name"] for s in skills}
    drop: set[int] = set()
    for b in codex_blocks(text):
        if ("path" in b and _real(b["path"]) in want) or b.get("name") in names:
            drop.update(range(b["start"], b["end"]))
    kept = [ln for i, ln in enumerate(lines) if i not in drop]
    while kept and not kept[-1].strip():
        kept.pop()
    off = {_real(s["path"]) for s, on in changes if not on}
    for path in sorted(want):
        if path in off:
            kept += ["", "[[skills.config]]", f"path = {json.dumps(path)}", "enabled = false"]
    _write(config, "\n".join(kept) + "\n")
