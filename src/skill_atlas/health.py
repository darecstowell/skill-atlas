"""Find SKILL.md and skill-store problems a user should fix. Read-only: it never changes a file."""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import scan

NAME_MAX = 64
DESC_MAX = 1024
NAME_OK = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BOOL_KEYS = ("disable-model-invocation", "user-invocable")

FENCE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)
MD_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
TICKED = re.compile(r"`((?:\./)?[\w.-]+(?:/[\w.-]+)+\.\w+)`")
SKILL_DIR_VARS = re.compile(r"^(?:\$\{CLAUDE_SKILL_DIR\}|\$CLAUDE_SKILL_DIR|\{baseDir\})/")


def problem(code: str, level: str, message: str, hint: str, **extra) -> dict:
    return {"code": code, "level": level, "message": message, "hint": hint, **extra}


def frontmatter_problems(text: str, fm: dict, dir_name: str) -> list[dict]:
    lines = text.removeprefix("﻿").split("\n")
    if not lines or lines[0].strip() != "---":
        return [
            problem(
                "frontmatter-missing",
                "error",
                "The file has no frontmatter.",
                "Start SKILL.md with a --- line, then name and description, then a --- line.",
            )
        ]
    close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if close is None:
        return [
            problem(
                "frontmatter-unclosed",
                "error",
                "The frontmatter has no closing --- line.",
                "Add a --- line after the last frontmatter key.",
            )
        ]
    if not fm and any(ln.strip() and not ln.lstrip().startswith("#") for ln in lines[1:close]):
        return [
            problem(
                "frontmatter-unparsable",
                "error",
                "The frontmatter has no key that can be read.",
                "Write each key as 'key: value' at the start of a line.",
            )
        ]

    out = []
    name = fm.get("name")
    if not isinstance(name, str) or not name.strip():
        out.append(
            problem(
                "name-missing",
                "error",
                "The name field is missing or empty.",
                f"Add 'name: {dir_name}' to the frontmatter.",
            )
        )
    else:
        name = name.strip()
        if len(name) > NAME_MAX or not NAME_OK.match(name):
            out.append(
                problem(
                    "name-format",
                    "warn",
                    f"The name '{name[:80]}' does not follow the Agent Skills rules.",
                    f"Use only lowercase letters, digits, and single hyphens. "
                    f"Use {NAME_MAX} characters or fewer.",
                )
            )
        if name != dir_name:
            out.append(
                problem(
                    "name-mismatch",
                    "warn",
                    f"The name '{name[:80]}' is not the same as the folder name '{dir_name}'.",
                    "Make the name and the folder name the same.",
                )
            )

    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        out.append(
            problem(
                "description-missing",
                "error",
                "The description field is missing or empty.",
                "Add a description that tells the agent when to use this skill.",
            )
        )
    elif len(desc) > DESC_MAX:
        out.append(
            problem(
                "description-long",
                "warn",
                f"The description has {len(desc)} characters. The limit is {DESC_MAX}.",
                "Make the description shorter. Move the details into the body.",
            )
        )

    for key in BOOL_KEYS:
        if key in fm and str(fm[key]).strip().lower() not in ("true", "false"):
            out.append(
                problem(
                    "bool-value",
                    "warn",
                    f"The value of {key} is '{str(fm[key])[:40]}'. It must be true or false.",
                    f"Set {key} to true or false.",
                )
            )
    return out


def _target(ref: str) -> str | None:
    ref = SKILL_DIR_VARS.sub("", ref.split("#", 1)[0].split("?", 1)[0])
    if not ref or ref.startswith(("/", "~", "$")) or any(c in ref for c in ":*{}<>|"):
        return None
    return ref.removeprefix("./")


def file_problems(skill_dir: Path, body: str) -> list[dict]:
    prose = FENCE.sub("", body)
    # A backticked scripts/x.py often means the project's file, so only folders the skill has count.
    subdirs = {p.name for p in skill_dir.iterdir() if p.is_dir()} | {"references"}
    refs: dict[str, bool] = {}
    for m in MD_LINK.finditer(prose):
        t = _target(m.group(1))
        if t:
            refs[t] = True
    for m in TICKED.finditer(prose):
        t = _target(m.group(1))
        if t and t.split("/", 1)[0] in subdirs:
            refs.setdefault(t, False)

    out = []
    for ref, linked in refs.items():
        if (skill_dir / ref).exists():
            continue
        out.append(
            problem(
                "broken-link" if linked else "missing-file",
                "error" if linked else "warn",
                f"SKILL.md {'links to' if linked else 'names'} {ref}, but that file "
                "does not exist.",
                "Add the file, or correct the path in SKILL.md.",
                path=ref,
            )
        )

    for root, dirs, files in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        for n in dirs + files:
            p = Path(root, n)
            if p.is_symlink() and not p.exists():
                rel = str(p.relative_to(skill_dir))
                out.append(
                    problem(
                        "broken-symlink",
                        "error",
                        f"The link {rel} points to {os.readlink(p)}, which does not exist.",
                        "Remove the link, or point it to a file that exists.",
                        path=rel,
                    )
                )
    return out


def skill_problems(skill_md: Path, text: str, fm: dict, body: str) -> list[dict]:
    """Every problem in one skill: its frontmatter, then the files its body names."""
    skill_dir = skill_md.parent
    return frontmatter_problems(text, fm, skill_dir.name) + file_problems(skill_dir, body)


def store_health(skills_dirs: list[Path], store: Path | None) -> dict:
    """Store-level problems: lock entries with no folder, and folders with no SKILL.md."""
    out = []
    if store and store.is_dir():
        for lock_name in (".skill-lock.json", scan.ATLAS_LOCK):
            lock = store.parent / lock_name
            entries = scan.as_dict(scan.read_json(lock).get("skills"))
            for key in sorted(entries):
                if not (store / key).exists():
                    out.append(
                        problem(
                            "ghost-lock",
                            "warn",
                            f"{lock_name} has an entry for {key}, but the folder is missing.",
                            f"Install {key} again, or remove its entry from {lock_name}.",
                            path=str(lock),
                            skill=key,
                        )
                    )
    for d in skills_dirs:
        try:
            children = sorted(d.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name.startswith("."):
                continue
            if child.is_symlink() and not child.exists():
                out.append(
                    problem(
                        "broken-symlink",
                        "error",
                        f"The link {child.name} points to {os.readlink(child)}, "
                        "which does not exist.",
                        "Remove the link, or point it to a skill folder that exists.",
                        path=str(child),
                        skill=child.name,
                    )
                )
            elif child.is_dir() and not (child / "SKILL.md").is_file():
                out.append(
                    problem(
                        "no-skill-md",
                        "warn",
                        f"The folder {child.name} has no SKILL.md, so no harness loads it.",
                        "Install the skill again, or remove the folder.",
                        path=str(child),
                        skill=child.name,
                    )
                )
    return {
        "problems": out,
        "errors": sum(p["level"] == "error" for p in out),
        "warnings": sum(p["level"] == "warn" for p in out),
    }
