from scan import build_record
from tokens import LIST_OVERHEAD, costs, estimate


def test_estimate_rounds_up():
    assert estimate("") == 0
    assert estimate("abc") == 1
    assert estimate("abcd") == 1
    assert estimate("abcde") == 2
    assert estimate("x" * 400) == 100


def test_costs_split_listed_and_body():
    c = costs("lint", "Checks code for style errors.", "\n\n# Lint\n\nRun the linter.\n\n")
    assert c["tokens_listed"] == 1 + 8 + LIST_OVERHEAD
    assert c["tokens_body"] == 6


def test_empty_skill_still_costs_the_overhead():
    assert costs("", "", "") == {"tokens_listed": LIST_OVERHEAD, "tokens_body": 0}


def test_build_record_has_costs(tmp_path):
    md = tmp_path / "demo" / "SKILL.md"
    md.parent.mkdir()
    md.write_text("---\nname: demo\ndescription: " + "d" * 40 + "\n---\n" + "b" * 800 + "\n")
    rec = build_record(md, scope="personal")
    assert rec["tokens_listed"] == 1 + 10 + LIST_OVERHEAD
    assert rec["tokens_body"] == 200
