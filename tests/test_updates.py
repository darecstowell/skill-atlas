import pytest

from updates import folder_of, folder_sha, parse_repo


@pytest.mark.parametrize(
    "text",
    [
        "owner/repo",
        "https://github.com/owner/repo",
        "https://github.com/owner/repo.git",
        "https://github.com/owner/repo/",
        "git@github.com:owner/repo.git",
    ],
)
def test_parse_repo_forms(text):
    assert parse_repo(text) == "owner/repo"


@pytest.mark.parametrize("text", ["", "repo", "https://gitlab.com/owner/repo", "a/b/c"])
def test_parse_repo_rejects(text):
    with pytest.raises(ValueError):
        parse_repo(text)


def test_folder_sha():
    tree = {
        "sha": "root",
        "tree": [
            {"type": "tree", "path": "skills/demo", "sha": "abc"},
            {"type": "blob", "path": "skills/demo/SKILL.md", "sha": "def"},
        ],
    }
    assert folder_of("skills/demo/SKILL.md") == "skills/demo"
    assert folder_sha(tree, "skills/demo/SKILL.md") == "abc"
    assert folder_sha(tree, "SKILL.md") == "root"
    assert folder_sha(tree, "skills/gone/SKILL.md") is None
