from skill_atlas.tui.state import UIState


def test_repos_start_folded_in_the_all_view_only():
    folds = UIState().folds()
    assert "src:acme/skills" in folds and "plg:docs" in folds and "prj:web" in folds
    assert "sec:personal" not in folds and "av:acme/skills" not in folds
    assert "src:acme/skills" not in UIState(view="updates").folds()


def test_opening_a_repo_or_all_repos_unfolds_it_and_a_fold_wins():
    assert "src:a" not in UIState(opened=frozenset({"src:a"})).folds()
    every = UIState(opened=frozenset({"*"}), collapsed=frozenset({"src:b"})).folds()
    assert "src:a" not in every and "src:b" in every
    assert list(every) == ["src:b"] and len(every) == 1
