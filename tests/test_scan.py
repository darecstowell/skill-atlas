import shutil
import subprocess

import pytest

from scan import as_list, git_tree_hash, parse_frontmatter


def test_frontmatter_scalars_lists_and_maps():
    fm, body = parse_frontmatter(
        "---\n"
        'name: "demo"\n'
        "description: Does a thing\n"
        "allowed-tools:\n  - Read\n  - Bash\n"
        "metadata:\n  version: 1.2\n"
        "---\n# Body\n"
    )
    assert fm["name"] == "demo"
    assert fm["description"] == "Does a thing"
    assert fm["allowed-tools"] == ["Read", "Bash"]
    assert fm["metadata"] == {"version": "1.2"}
    assert body.strip() == "# Body"


def test_frontmatter_missing():
    fm, body = parse_frontmatter("# Just a body\n")
    assert fm == {}
    assert "Just a body" in body


def test_as_list():
    assert as_list(None) == []
    assert as_list(["a", "b"]) == ["a", "b"]
    assert as_list("a, b") == ["a", "b"]


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_git_tree_hash_matches_git(tmp_path):
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: skill\n---\n")
    run = skill / "scripts" / "run.sh"
    run.write_text("#!/bin/sh\necho hi\n")
    run.chmod(0o755)

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git("add", ".")
    assert git_tree_hash(skill) == git("rev-parse", f"{git('write-tree')}:skill")
