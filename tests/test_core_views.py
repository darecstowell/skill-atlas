from datetime import datetime, timedelta

import pytest

from skill_atlas.core import views
from skill_atlas.core.views import Insights, ViewState

NOW = datetime(2026, 10, 28, 12, 0).astimezone()
CLAUDE, CODEX, CURSOR = "claude-code", "codex", "cursor"
NONE = {"level": "none", "counts": {"high": 0, "medium": 0, "info": 0}, "code": 0, "rules": {}}


def day(n: int) -> str:
    return (NOW.date() - timedelta(days=n)).isoformat()


def ts(n: int) -> str:
    return (NOW - timedelta(days=n)).isoformat(timespec="seconds")


def rec(name: str, scope: str = "personal", **kw) -> dict:
    base = "/h/.agents/skills" if scope == "personal" else f"/h/x/{name}"
    path = kw.pop("path", f"{base}/{kw.get('dir_name', name)}/SKILL.md")
    r = {
        "name": name,
        "dir_name": name,
        "description": f"Handles {name} work.",
        "scope": scope,
        "manual_only": False,
        "claude_only": False,
        "path": path,
        "dir": path.rsplit("/", 1)[0],
        "harnesses": [CLAUDE],
        "status": "enabled",
        "problems": [],
        "tokens_listed": 20,
        "tokens_body": 100,
        "security": NONE,
        "similar": [],
        "copies": [],
        "invoke": name,
    }
    if scope == "personal":
        r.update(origin={}, store=True, local_edits=False, source_root="/h/.agents/skills")
    r.update(kw)
    return r


def plugin(name: str, ref: str, version: str = "1.2.0", status: str = "enabled", **kw) -> dict:
    p, market = ref.split("@")
    return rec(
        name,
        "plugin",
        path=f"/h/.claude/plugins/cache/{market}/{p}/{version}/skills/{name}/SKILL.md",
        plugin=p,
        plugin_ref=ref,
        marketplace=market,
        plugin_version=version,
        status=status,
        invoke=f"{p}:{name}",
        marketplace_source={"source": "github", "repo": "acme/market"},
        **kw,
    )


def project(name: str, proj: str) -> dict:
    return rec(name, "project", harnesses=[], status="project-only", project=proj)


TRACKED = {"source": "acme/tools", "sourceUrl": "https://github.com/acme/tools.git"}


def make_data() -> dict:
    """A small scan shaped like /api/data, with updates, usage, and descriptions."""
    alpha = rec(
        "alpha",
        harnesses=[CLAUDE, CODEX, CURSOR],
        origin={**TRACKED, "skillFolderHash": "h1"},
        tokens_listed=300,
        similar=[{"path": "/h/.agents/skills/delta/SKILL.md", "name": "delta", "score": 0.5}],
    )
    beta = rec(
        "beta",
        harnesses=[CLAUDE, CODEX],
        origin={"source": "acme/tools", "skillFolderHash": "h2"},
        local_edits=True,
        tokens_listed=120,
        copies=[
            {
                "path": "/h/.claude/skills/beta/SKILL.md",
                "dir": "/h/.claude/skills/beta",
                "newer": "other",
                "trees_differ": False,
            }
        ],
    )
    beta_copy = rec(
        "beta",
        path="/h/.claude/skills/beta/SKILL.md",
        store=False,
        source_root="/h/.claude/skills",
        description="Another beta.",
    )
    skills = [
        alpha,
        beta,
        beta_copy,
        rec("gamma", description="Shared words.", tokens_listed=400, claude_only=True),
        rec("Zeta", tokens_listed=35),
        rec(
            "delta",
            harnesses=[CLAUDE, CURSOR],
            description="Shared words.",
            manual_only=True,
            tokens_listed=90,
            security={**NONE, "level": "medium", "counts": {"high": 0, "medium": 1, "info": 0}},
            similar=[{"path": alpha["path"], "name": "alpha", "score": 0.5}],
        ),
        rec("kit-py-lint", harnesses=[CODEX, CURSOR], tokens_listed=30),
        rec("kit-py-test", harnesses=[CODEX, CURSOR], tokens_listed=250),
        rec(
            "kit-py-fmt",
            harnesses=[CODEX, CURSOR],
            tokens_listed=50,
            security={**NONE, "code": 1, "rules": {"code": 1}},
        ),
        rec("two-a"),
        rec("two-b"),
        rec("a-c"),
        rec("a_b"),
        rec(
            "omega",
            origin={"source": "zed/pack", "skillFolderHash": "h3"},
            tokens_listed=200,
            problems=[{"level": "error", "code": "x", "message": "Bad name", "hint": "Fix it"}],
            security={**NONE, "level": "high", "counts": {"high": 2, "medium": 0, "info": 0}},
        ),
        rec("solo", harnesses=[]),
        plugin("fmt", "tools@market", tokens_listed=60),
        plugin("fmt", "tools@market", version="1.1.0", status="stale"),
        plugin("nap", "off@market", status="disabled"),
        plugin("ghost", "unset@market", status="installed"),
        project("proj-a", "webapp"),
        project("proj-b", "api"),
    ]
    skills.sort(key=lambda r: (r["scope"], r["name"].lower()))
    harnesses = {
        CLAUDE: {"name": "Claude Code", "label": "Claude Code", "switch": "claude", "store": False},
        CODEX: {"name": "Codex", "label": "Codex", "switch": "codex", "store": True},
        CURSOR: {"name": "Cursor", "label": "Cursor", "switch": None, "store": True},
    }
    scan = {
        "home": "/h",
        "bundled_skills_disabled": True,
        "harnesses": harnesses,
        "settings": {
            CLAUDE: {
                "path": "/h/.claude/settings.json",
                "skillOverrides": {"beta": "off", "gamma": "user-invocable-only"},
                "enabledPlugins": {"tools@market": True, "off@market": False},
            },
            CODEX: {"path": "/h/.codex/config.toml", "off": ["alpha"]},
            CURSOR: {},
        },
        "health": {
            "problems": [
                {"level": "warn", "code": "ghost-lock", "message": "m", "hint": "h", "path": "/x"}
            ]
        },
        "skills": skills,
    }
    updates = {
        "checked_at": (NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "skills": {"alpha": "outdated", "beta": "current", "omega": "unknown"},
        "errors": {},
        "available": {
            "acme/tools": [
                {"name": "acme-new", "path": "skills/acme-new/SKILL.md", "new": True, "taken": ""},
                {"name": "old-one", "path": "skills/old-one/SKILL.md", "new": False, "taken": ""},
                {"name": "gamma", "path": "skills/gamma/SKILL.md", "new": False, "taken": "taken"},
            ],
            "fresh/repo": [{"name": "shiny", "path": "shiny/SKILL.md", "new": True, "taken": ""}],
            "quiet/repo": [],
        },
        "watched": ["quiet/repo", "fresh/repo"],
    }
    usage = {
        "status": "ready",
        "error": None,
        "progress": [3, 3],
        "counters": {
            "alpha": {"count": 10, "last": ts(2)},
            "tools:fmt": {"count": 3, "last": ts(200)},
        },
        "skills": {
            "alpha": {
                "days": {day(2): 4, day(9): 2},
                "projects": {"webapp": 5, "api": 1},
                "last": ts(2),
            },
            "py-lint": {"days": {day(1): 1}, "projects": {}, "last": ts(1)},
            "delta": {"days": {day(100): 1}, "projects": {}, "last": ts(100)},
        },
    }
    descs = {
        "acme/tools": {"skills": {"skills/acme-new/SKILL.md": {"description": "Builds widgets"}}}
    }
    return {"scan": scan, "updates": updates, "usage": usage, "descs": descs, "now": NOW}


def insights(**over) -> Insights:
    d = {**make_data(), **over}
    return Insights(
        d["scan"],
        d["updates"],
        d["usage"],
        now=d["now"],
        descs=d["descs"],
        **{k: v for k, v in over.items() if k in ("writable", "missing")},
    )


@pytest.fixture
def ins() -> Insights:
    return insights()


def by(ins: Insights, name: str, scope: str = "personal", status: str = "") -> dict:
    return next(
        s
        for s in ins.skills
        if s["name"] == name and s["scope"] == scope and (not status or s["status"] == status)
    )


def names(skills) -> list[str]:
    return [s["name"] for s in skills]


# --------------------------------------------------------------------------
# switches
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("harness", "name", "scope", "status", "on", "mode", "toggle"),
    [
        (CLAUDE, "alpha", "personal", "", True, "on", "skill"),
        (CLAUDE, "beta", "personal", "", False, "off", "skill"),
        (CLAUDE, "gamma", "personal", "", True, "user-invocable-only", "skill"),
        (CLAUDE, "fmt", "plugin", "enabled", True, "", "plugin"),
        (CLAUDE, "fmt", "plugin", "stale", False, "old version", ""),
        (CLAUDE, "nap", "plugin", "", False, "", "plugin"),
        (CLAUDE, "ghost", "plugin", "", False, "not set", "plugin"),
        (CLAUDE, "proj-a", "project", "", True, "project only", ""),
        (CODEX, "alpha", "personal", "", False, "off", "skill"),
        (CODEX, "kit-py-lint", "personal", "", True, "on", "skill"),
        (CODEX, "proj-a", "project", "", True, "project only", ""),
        (CURSOR, "alpha", "personal", "", True, "", ""),
        ("all", "alpha", "personal", "", True, "", ""),
        ("all", "nap", "plugin", "", False, "", ""),
        ("all", "fmt", "plugin", "stale", False, "old version", ""),
        ("all", "proj-a", "project", "", True, "project only", ""),
        ("all", "solo", "personal", "", False, "", ""),
    ],
)
def test_switch_state(ins, harness, name, scope, status, on, mode, toggle):
    st = views.switch_state(ins, harness, by(ins, name, scope, status))
    assert (st["on"], st["mode"], st["toggle"]) == (on, mode, toggle)


def test_all_is_on_when_any_harness_is_on(ins):
    beta = by(ins, "beta")
    assert not views.switch_state(ins, CLAUDE, beta)["on"]
    assert views.switch_state(ins, CODEX, beta)["on"]
    assert views.switch_state(ins, "all", beta)["on"]


@pytest.mark.parametrize(
    ("harness", "switchable", "reads_store", "meta"),
    [
        ("all", False, True, ["pick a harness to switch skills"]),
        (CLAUDE, True, False, ["built-ins off", "writes ~/.claude/settings.json"]),
        (CODEX, True, True, ["writes ~/.codex/config.toml"]),
        (CURSOR, False, True, ["Cursor has no per-skill switch"]),
    ],
)
def test_harness_rules(ins, harness, switchable, reads_store, meta):
    assert views.switchable(ins, harness) is switchable
    assert views.reads_store(ins, harness) is reads_store
    assert views.header_meta(ins, harness) == meta


def test_harness_choices():
    assert views.harness_choices(insights()) == ["all", CLAUDE, CODEX, CURSOR]
    one = make_data()["scan"]
    one["harnesses"] = {CLAUDE: one["harnesses"][CLAUDE]}
    assert views.harness_choices(Insights(one)) == [CLAUDE]
    assert views.default_harness(Insights(one)) == CLAUDE
    assert views.default_harness(Insights({"skills": []})) == "all"


# --------------------------------------------------------------------------
# index: sources, prefix groups, duplicates, search
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("alpha", "acme/tools"),
        ("kit-py-lint", "kit-py-*"),
        ("kit-py-fmt", "kit-py-*"),
        ("two-a", views.NO_SOURCE),
        ("gamma", views.NO_SOURCE),
        ("omega", "zed/pack"),
    ],
)
def test_source_of_and_prefix_groups(ins, name, source):
    assert views.source_of(ins, by(ins, name)) == source


def test_prefix_label_is_the_longest_shared_part():
    scan = {"skills": [rec("acme-a-x"), rec("acme-b-y"), rec("acme-c-z")]}
    ins = Insights(scan)
    assert {views.source_of(ins, s) for s in ins.skills} == {"acme-*"}
    tracked = rec("acme-d-w", origin={"source": "o/r", "skillFolderHash": "h"})
    ins = Insights({"skills": [*scan["skills"], tracked]})
    assert views.source_of(ins, tracked) == "o/r"


@pytest.mark.parametrize(
    ("source", "local"),
    [(views.NO_SOURCE, True), ("kit-py-*", True), ("acme/tools", False)],
)
def test_is_local_group(source, local):
    assert views.is_local_group(source) is local


def test_dupes_are_personal_skills_with_the_same_description(ins):
    assert views.dupes(ins, by(ins, "gamma")) == ["delta"]
    assert views.dupes(ins, by(ins, "delta")) == ["gamma"]
    assert views.dupes(ins, by(ins, "alpha")) == []


@pytest.mark.parametrize(
    ("text", "out"),
    [
        ("Use when the user wants to deploy apps", "Wants to deploy apps"),
        ("When the user asks for help with SQL", "Help with SQL"),
        ("This skill should be used when tests fail", "Tests fail"),
        ("use this skill when the user types", "Types"),
        ("Plain text", "Plain text"),
        ("", ""),
        (None, ""),
    ],
)
def test_clean_desc(text, out):
    assert views.clean_desc(text) == out


def test_search_haystack_has_the_source_and_path(ins):
    hay = views.search_haystack(ins, by(ins, "kit-py-lint"))
    assert "kit-py-*" in hay
    assert "/h/.agents/skills/kit-py-lint/skill.md" in hay
    assert "tools:fmt" in views.search_haystack(ins, by(ins, "fmt", "plugin", "enabled"))


# --------------------------------------------------------------------------
# views and search
# --------------------------------------------------------------------------

PERSONAL_ALL = {"alpha", "beta", "gamma", "delta", "kit-py-lint", "kit-py-test", "kit-py-fmt"}
PERSONAL_ALL |= {"two-a", "two-b", "a-c", "a_b", "omega", "Zeta"}


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"harness": "all"}, PERSONAL_ALL | {"fmt", "nap", "ghost"}),
        ({"harness": CODEX}, {"alpha", "beta", "kit-py-lint", "kit-py-test", "kit-py-fmt"}),
        ({"harness": CODEX, "view": "on"}, {"beta", "kit-py-lint", "kit-py-test", "kit-py-fmt"}),
        ({"harness": CODEX, "view": "off"}, {"alpha"}),
        ({"harness": CLAUDE, "view": "off"}, {"beta", "nap", "ghost"}),
        ({"harness": "all", "show_stale": True, "view": "off"}, {"beta", "nap", "ghost", "fmt"}),
        (
            {"harness": CLAUDE, "show_project": True, "view": "on", "query": "proj"},
            {"proj-a", "proj-b"},
        ),
        ({"harness": CLAUDE, "view": "updates"}, {"alpha"}),
        ({"harness": CLAUDE, "view": "issues"}, {"omega"}),
        ({"harness": CLAUDE, "view": "review"}, {"omega"}),
        ({"harness": CLAUDE, "view": "new"}, set()),
        ({"harness": CLAUDE, "view": "similar"}, {"alpha", "delta"}),
        ({"harness": CODEX, "view": "similar"}, set()),
        ({"harness": "all", "view": "diverged"}, {"beta"}),
        ({"harness": CURSOR, "view": "unused"}, {"kit-py-test", "kit-py-fmt", "delta"}),
        ({"harness": CLAUDE, "view": "costly"}, {"gamma", "omega"}),
        ({"harness": "all", "query": "KIT  py-f"}, {"kit-py-fmt"}),
        ({"harness": "all", "query": "acme handles"}, {"alpha", "beta"}),
        ({"harness": "all", "query": "market tools"}, {"fmt"}),
        ({"harness": "all", "query": "nothing-matches"}, set()),
    ],
)
def test_visible(ins, state, expected):
    assert set(names(views.visible_skills(ins, ViewState(**state)))) == expected


def test_unused_view_needs_ready_usage():
    ins = insights(usage={**make_data()["usage"], "status": "indexing"})
    assert views.visible_skills(ins, ViewState(harness=CURSOR, view="unused")) == []
    assert not views.costly_unused(ins, CLAUDE)


def test_in_view_hides_project_and_stale_until_asked(ins):
    proj, stale = by(ins, "proj-a", "project"), by(ins, "fmt", "plugin", "stale")
    assert not views.in_view(ins, ViewState(), proj)
    assert views.in_view(ins, ViewState(show_project=True), proj)
    assert not views.in_view(ins, ViewState(), stale)
    assert views.in_view(ins, ViewState(show_stale=True), stale)
    assert not views.in_view(ins, ViewState(), by(ins, "solo"))


@pytest.mark.parametrize(
    ("sort", "order"),
    [
        ("name", ["a_b", "a-c", "alpha", "beta", "beta", "delta", "fmt", "gamma", "ghost", "nap"]),
        ("uses", ["alpha", "fmt", "delta", "a_b", "a-c", "beta"]),
        ("recent", ["alpha", "delta", "fmt", "a_b", "a-c", "beta"]),
        ("cost", ["gamma", "alpha", "omega", "beta", "delta", "fmt", "Zeta", "a_b", "a-c"]),
    ],
)
def test_sort(ins, sort, order):
    shown = names(views.visible_skills(ins, ViewState(harness=CLAUDE, sort=sort)))
    assert shown[: len(order)] == order
    assert shown[-1] == "Zeta" or sort == "cost"


@pytest.mark.parametrize(
    ("a", "b"),
    [("a_b", "a-c"), ("a-c", "ab"), ("abc", "Abc"), ("skill10", "skill2"), ("ab", "äc")],
)
def test_collate_follows_locale_compare(a, b):
    assert views.collate(a) < views.collate(b)


def test_collate_base_ignores_case_and_accents():
    assert views.collate("Abc", base=True) == views.collate("abc", base=True)
    assert views.collate("äbc", base=True) == views.collate("abc", base=True)


# --------------------------------------------------------------------------
# updates and available skills
# --------------------------------------------------------------------------


def test_update_rules(ins):
    assert views.lock_name(by(ins, "alpha")) == "alpha"
    assert views.lock_name(by(ins, "gamma")) is None
    assert views.lock_name(by(ins, "fmt", "plugin", "enabled")) is None
    assert views.is_outdated(ins, by(ins, "alpha"))
    assert not views.is_outdated(ins, by(ins, "beta"))
    assert views.update_status(ins, by(ins, "omega")) == "unknown"
    assert views.new_total(ins) == 2
    assert names(views.new_in(ins, "acme/tools")) == ["acme-new"]


@pytest.mark.parametrize(
    ("state", "writable", "expected"),
    [
        ({}, True, ["acme-new", "old-one", "gamma"]),
        ({"view": "new"}, True, ["acme-new"]),
        ({"query": "widgets"}, True, ["acme-new"]),
        ({"query": "acme/tools old"}, True, ["old-one"]),
        ({"group_by": "type"}, True, []),
        ({"group_by": "type", "view": "new"}, True, ["acme-new"]),
        ({"view": "on"}, True, []),
        ({}, False, []),
    ],
)
def test_avail_shown(state, writable, expected):
    ins = insights(writable=writable)
    assert names(views.avail_shown(ins, ViewState(**state), "acme/tools")) == expected


@pytest.mark.parametrize(
    ("state", "repo", "installed", "collapsed", "open_"),
    [
        ({}, "acme/tools", 2, set(), True),
        ({}, "acme/tools", 2, {"av:acme/tools"}, False),
        ({}, "zed/pack", 1, set(), False),
        ({}, "zed/pack", 1, {"+av:zed/pack"}, True),
        ({}, "zed/pack", 0, set(), True),
        ({"query": "x"}, "acme/tools", 2, {"av:acme/tools"}, True),
        ({"view": "new"}, "acme/tools", 2, {"av:acme/tools"}, True),
    ],
)
def test_avail_open(ins, state, repo, installed, collapsed, open_):
    assert views.avail_open(ins, ViewState(**state), repo, installed, collapsed) is open_


# --------------------------------------------------------------------------
# counts and view tabs
# --------------------------------------------------------------------------


def test_counts(ins):
    n = views.counts(ins, ViewState(harness=CLAUDE))
    assert n == {
        "all": 14,
        "on": 10,
        "off": 4,
        "updates": 1,
        "issues": 1,
        "new": 2,
        "unused": 13,
        "costly": 2,
        "review": 1,
    }


def test_window_title_badges_updates_and_new_skills(ins):
    assert views.window_title(ins, CLAUDE) == "(1↑ · 2 new) Skill Atlas"
    assert views.window_title(insights(writable=False), CLAUDE) == "Skill Atlas"
    assert views.window_title(Insights({"skills": []}), CLAUDE) == "Skill Atlas"


@pytest.mark.parametrize(
    ("over", "state", "expected"),
    [
        ({}, {}, ["all", "on", "off", "updates", "issues", "new", "unused", "review"]),
        (
            {},
            {"view": "similar"},
            ["all", "on", "off", "updates", "issues", "new", "unused", "similar", "review"],
        ),
        ({}, {"harness": CODEX}, ["all", "on", "off", "updates", "new", "unused"]),
        (
            {},
            {"harness": CODEX, "view": "costly"},
            ["all", "on", "off", "updates", "new", "unused", "costly"],
        ),
        ({"writable": False}, {"harness": CODEX}, ["all", "on", "off"]),
        (
            {"usage": {"status": "error"}},
            {"harness": CODEX},
            ["all", "on", "off", "updates", "new"],
        ),
        (
            {"updates": None},
            {"harness": CODEX, "view": "new"},
            ["all", "on", "off", "updates", "new", "unused"],
        ),
    ],
)
def test_shown_views(over, state, expected):
    assert views.shown_views(insights(**over), ViewState(**state)) == expected


def test_unused_tab_waits_for_usage():
    tabs = views.view_tabs(insights(usage=None), ViewState(harness=CODEX))
    unused = next(t for t in tabs if t["id"] == "unused")
    assert unused["waiting"] and unused["title"] == "No recorded use in 90 days"
    assert next(t for t in tabs if t["id"] == "all")["count"] == 5


# --------------------------------------------------------------------------
# sections and groups
# --------------------------------------------------------------------------


def test_sections_by_source(ins):
    secs = views.sections(ins, ViewState(harness="all", show_project=True))
    assert [(s["id"], s["title"], s["count"]) for s in secs] == [
        ("sec:personal", "Your skills", "14"),
        ("sec:plugins", "Plugins", "3"),
        ("sec:project", "Project skills", "2"),
    ]
    groups = secs[0]["groups"]
    assert [g["id"] for g in groups] == [
        "src:acme/tools",
        "src:fresh/repo",
        "src:kit-py-*",
        "src:quiet/repo",
        "src:zed/pack",
        f"src:{views.NO_SOURCE}",
    ]
    acme = groups[0]
    assert names(acme["skills"]) == ["alpha", "beta"]
    assert acme["meta"] == "2 of 2 on · 3 available"
    assert acme["repo_url"] == "https://github.com/acme/tools"
    assert acme["checked"] == "true" and not acme["switch"]
    assert names(acme["available"]) == ["acme-new", "old-one", "gamma"]
    assert acme["available_open"] and acme["fresh"] == 1
    assert (acme["installable"], acme["fresh_installable"]) == (2, 1)
    fresh, kit, quiet = groups[1], groups[2], groups[3]
    assert fresh["meta"] == "watching · 1 available" and fresh["skills"] == []
    assert kit["meta"] == "no source · 3 of 3 on" and kit["local"] and kit["repo"] is None
    assert quiet["available_note"].startswith("You have every skill")
    assert set(secs[0]["group_ids"]) == {g["id"] for g in groups}
    assert [g["id"] for g in secs[1]["groups"]] == [
        "plg:off@market",
        "plg:tools@market",
        "plg:unset@market",
    ]
    assert [g["id"] for g in secs[2]["groups"]] == ["prj:api", "prj:webapp"]


def test_source_group_counts_and_switch(ins):
    st = ViewState(harness=CLAUDE, query="beta")
    acme = views.groups(ins, st)[0]
    assert acme["id"] == "src:acme/tools"
    assert acme["meta"] == "1 of 2 on · 1 shown · 3 available"
    assert acme["checked"] == "mixed" and acme["switch"]
    assert acme["open"]


def test_plugin_groups(ins):
    secs = views.sections(ins, ViewState(harness=CLAUDE, show_stale=True))
    plugins = next(s for s in secs if s["id"] == "sec:plugins")
    tools = next(g for g in plugins["groups"] if g["key"] == "tools@market")
    assert tools["label"] == "tools" and tools["repo"] == "acme/market"
    assert tools["meta"] == "market · 2 skills" and tools["switch"] and tools["checked"] == "true"
    unset = next(g for g in plugins["groups"] if g["key"] == "unset@market")
    assert unset["meta"] == "market · 1 skill · not in enabledPlugins"


def test_group_by_type_keeps_rows_flat(ins):
    sec = views.sections(ins, ViewState(harness=CODEX, group_by="type"))[0]
    assert sec["groups"] == [] and sec["group_ids"] == []
    assert names(sec["rows"]) == ["alpha", "beta", "kit-py-fmt", "kit-py-lint", "kit-py-test"]


def test_new_view_lists_new_skills_by_source(ins):
    secs = views.sections(ins, ViewState(harness=CODEX, view="new"))
    assert [(s["id"], s["count"]) for s in secs] == [("sec:new", "2")]
    assert [(g["id"], names(g["available"])) for g in secs[0]["groups"]] == [
        ("src:acme/tools", ["acme-new"]),
        ("src:fresh/repo", ["shiny"]),
    ]
    assert all(g["open"] for g in secs[0]["groups"])


def test_no_installs_where_the_harness_skips_the_store(ins):
    groups = views.groups(ins, ViewState(harness=CLAUDE))
    assert "src:fresh/repo" not in [g["id"] for g in groups]
    assert next(g for g in groups if g["id"] == "src:acme/tools")["available"] == []


def test_collapsed_groups_and_sections(ins):
    st = ViewState(harness="all")
    secs = views.sections(ins, st, {"sec:plugins", "src:kit-py-*"})
    assert not next(s for s in secs if s["id"] == "sec:plugins")["open"]
    assert not next(g for g in secs[0]["groups"] if g["key"] == "kit-py-*")["open"]
    st = ViewState(harness="all", query="kit")
    assert all(g["open"] for g in views.groups(ins, st, {"src:kit-py-*"}))


def test_groups_sort_by_uses_keeps_no_source_last(ins):
    ids = [g["id"] for g in views.groups(ins, ViewState(harness="all", sort="uses"))]
    assert ids[:3] == ["src:acme/tools", "src:kit-py-*", "src:fresh/repo"]
    assert ids[5:] == [
        f"src:{views.NO_SOURCE}",
        "plg:tools@market",
        "plg:off@market",
        "plg:unset@market",
    ]


@pytest.mark.parametrize(
    ("state", "title", "actions"),
    [
        ({"query": "zzz"}, "No skills match “zzz”", ["clear"]),
        ({"query": "proj", "view": "on"}, "No skills match “proj”", ["clear", "show_project"]),
        ({"view": "updates"}, "Everything is up to date", ["recheck"]),
        ({"view": "new"}, "No new skills", ["recheck"]),
        ({"view": "issues"}, "No problems found", ["view_all"]),
        ({"view": "similar"}, "No similar skills", ["view_all"]),
        ({"view": "diverged"}, "No diverged copies", ["view_all"]),
        ({"view": "review"}, "Nothing to review", ["view_all"]),
        ({"view": "unused"}, "Every skill is in use", []),
        ({"view": "costly"}, "No costly skills sit unused", ["view_all"]),
        ({"view": "off"}, "Nothing is off", []),
        ({}, "No skills here", []),
    ],
)
def test_empty_state(ins, state, title, actions):
    empty = views.empty_state(ins, ViewState(**state))
    assert (empty["title"], empty["actions"]) == (title, actions)


def test_empty_state_bodies(ins):
    body = views.empty_state(ins, ViewState(query="proj", view="on"))["body"]
    assert body == "The on filter is on. 2 hidden skills match."
    assert views.empty_state(ins, ViewState(view="updates"))["body"] == "Checked 5m ago."
    never = insights(updates=None)
    assert views.empty_state(never, ViewState(view="updates"))["body"] == "No check has run yet."


# --------------------------------------------------------------------------
# usage
# --------------------------------------------------------------------------


def test_usage_index(ins):
    alpha = views.use_of(ins, by(ins, "alpha"))
    assert alpha is not None
    assert (alpha["counted"], alpha["seen"], alpha["count"]) == (10, 6, 10)
    assert alpha["projects"] == {"webapp": 5, "api": 1}
    assert views.uses(ins, by(ins, "kit-py-lint")) == 1
    assert views.uses(ins, by(ins, "fmt", "plugin", "enabled")) == 3
    assert views.uses(ins, by(ins, "fmt", "plugin", "stale")) == 0
    assert views.last_used(ins, by(ins, "gamma")) == 0


def test_suffix_match_needs_one_skill():
    data = make_data()
    data["scan"]["skills"].append(rec("other-lint"))
    data["usage"]["skills"]["lint"] = {"days": {day(1): 1}, "projects": {}, "last": ts(1)}
    ins = Insights(data["scan"], usage=data["usage"], now=NOW)
    assert views.uses(ins, by(ins, "other-lint")) == 0
    assert views.uses(ins, by(ins, "kit-py-lint")) == 1


@pytest.mark.parametrize(
    ("name", "scope", "status", "unused"),
    [
        ("alpha", "personal", "", False),
        ("gamma", "personal", "", True),
        ("delta", "personal", "", True),
        ("fmt", "plugin", "enabled", True),
        ("fmt", "plugin", "stale", False),
        ("proj-a", "project", "", False),
    ],
)
def test_is_unused(ins, name, scope, status, unused):
    assert views.is_unused(ins, by(ins, name, scope, status)) is unused


def test_spark_series(ins):
    assert views.spark_series(ins, by(ins, "alpha")) == [0] * 10 + [2, 4]
    assert views.spark_series(ins, by(ins, "gamma")) is None
    acme = [by(ins, "alpha"), by(ins, "beta")]
    assert views.group_spark(ins, acme) == [0] * 10 + [2, 4]
    assert views.group_spark(ins, [by(ins, "gamma")]) is None
    assert views.group_spark(insights(usage=None), acme) is None


def test_weekly_drops_days_outside_the_window():
    days = {day(0): 1, day(6): 2, day(7): 3, day(83): 4, day(84): 5, day(-3): 6, "junk": 7}
    assert views.weekly(days, 12, NOW) == [4] + [0] * 9 + [3, 3]


@pytest.mark.parametrize(
    ("days_ago", "text"),
    [(0, "today"), (1, "yesterday"), (5, "5 days ago"), (20, "3 weeks ago"), (200, "7 months ago")],
)
def test_ago(days_ago, text):
    ms = (NOW - timedelta(days=days_ago)).timestamp() * 1000
    assert views.ago(ms, NOW) == text


@pytest.mark.parametrize(
    ("n", "text"),
    [(0, "0"), (999, "999"), (1000, "1.0k"), (1250, "1.3k"), (12500, "13k"), (9999, "10.0k")],
)
def test_short(n, text):
    assert views.short(n) == text
    assert views.approx(n) == "≈" + text


def test_heatmap():
    hm = views.heatmap({day(0): 1, day(1): 7}, NOW)
    cells = hm["cells"]
    assert cells[0]["dow"] == 0 and cells[-1]["day"] == day(0)
    assert 175 <= len(cells) <= 182
    assert [c["level"] for c in cells[-2:]] == [4, 2]
    assert hm["summary"] == "8 uses on 2 days in saved sessions"


# --------------------------------------------------------------------------
# cost, security, overlap
# --------------------------------------------------------------------------


def test_context_cost(ins):
    one = views.context_cost(ins, CLAUDE)
    assert (one["count"], one["total"], one["summary"]) == (10, 1165, "≈1.2k tokens")
    assert names(one["top"]) == ["gamma", "alpha", "omega", "delta", "fmt"]
    every = views.context_cost(ins, "all")
    per = [(p["id"], p["total"], p["count"]) for p in every["per_harness"]]
    assert per == [(CLAUDE, 1165, 10), (CURSOR, 720, 5), (CODEX, 450, 4)]
    assert every["summary"] == "Up to ≈1.2k tokens"


def test_costly_unused_is_the_top_quarter(ins):
    assert views.costly_unused(ins, CLAUDE) == {by(ins, "gamma")["path"], by(ins, "omega")["path"]}


def test_security(ins):
    assert views.is_risky(by(ins, "omega")) and not views.is_risky(by(ins, "delta"))
    st = ViewState(harness="all")
    assert views.security_counts(ins, st) == {"high": 1, "medium": 1, "code": 1}


def test_similar_of_needs_a_copy_that_loads(ins):
    alpha = by(ins, "alpha")
    assert names(x["skill"] for x in views.similar_of(ins, CLAUDE, alpha)) == ["delta"]
    assert views.similar_of(ins, CODEX, alpha) == []
    lv = [s for s in ins.skills if s["scope"] == "personal"]
    assert views.overlap_counts(ins, "all", lv) == {"similar": 1, "diverged": 1}


# --------------------------------------------------------------------------
# rows and panels
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("harness", "name", "scope", "status", "texts"),
    [
        (CLAUDE, "omega", "personal", "", ["1 problem", "review", "not upstream"]),
        (CLAUDE, "beta", "personal", "", ["edited", "diverged"]),
        (CLAUDE, "gamma", "personal", "", ["agent only", "user-invocable-only", "same as delta"]),
        (CLAUDE, "delta", "personal", "", ["you only", "same as gamma", "similar"]),
        (CODEX, "kit-py-fmt", "personal", "", ["runs code"]),
        (CLAUDE, "fmt", "plugin", "stale", ["old version", "v1.1.0"]),
        (CLAUDE, "alpha", "personal", "", ["similar"]),
    ],
)
def test_tags(ins, harness, name, scope, status, texts):
    assert [t["text"] for t in views.tags(ins, harness, by(ins, name, scope, status))] == texts


def test_update_tag_only_when_read_only():
    ins = insights(writable=False)
    assert "update" in [t["text"] for t in views.tags(ins, CLAUDE, by(ins, "alpha"))]


@pytest.mark.parametrize(
    ("harness", "name", "scope", "job", "state"),
    [
        (CLAUDE, "alpha", "personal", None, "outdated"),
        (CLAUDE, "alpha", "personal", "downloading", "busy"),
        (CLAUDE, "alpha", "personal", "done", "done"),
        (CLAUDE, "beta", "personal", None, "off"),
        (CODEX, "beta", "personal", None, "edited"),
        (CLAUDE, "gamma", "personal", None, "on"),
        (CLAUDE, "proj-a", "project", None, "project"),
    ],
)
def test_row_state(ins, harness, name, scope, job, state):
    assert views.row_state(ins, harness, by(ins, name, scope), job) == state


def test_inventory(ins):
    assert views.inventory(ins, CLAUDE) == {
        "on": 10,
        "off": 4,
        "updates": 1,
        "untracked": 8,
        "duplicates": 2,
        "edited": 1,
        "uses": 14,
        "unused": 13,
    }


def test_attention(ins):
    items = views.attention(ins, ViewState(harness=CLAUDE))
    assert [(i["key"], i["tone"], i["action"]) for i in items] == [
        ("a-sec", "danger", "review"),
        ("a-prob", "danger", "issues"),
        ("a-store", "warn", ""),
        ("a-div", "warn", "diverged"),
        ("a-cost", "warn", "costly"),
    ]
    assert items[2]["detail"] == "1 lock entry with no folder"
    assert items[3]["text"] == "1 diverged name"
    assert views.attention_cue(items) == {"tone": "danger", "text": "5 things to check"}
    assert views.attention_cue([]) is None


def test_attention_missing_skills():
    items = views.attention(insights(missing=2), ViewState(harness=CODEX))
    miss = next(i for i in items if i["key"] == "a-miss")
    assert miss["detail"] == "2 skills in the lock file have no folder."
    assert miss["action"] == "restore"


def test_group_detail(ins):
    g = views.group_for(ins, "plg:tools@market")
    assert (g["label"], g["repo"], g["key"]) == ("tools", "acme/market", "g:plg:tools@market")
    assert views.group_for(ins, "src:kit-py-*")["repo"] is None
    assert names(views.members_of(ins, CLAUDE, "plg:tools@market")) == ["fmt"]
    assert views.members_of(ins, "all", "plg:tools@market") == []
    acme = views.members_of(ins, CLAUDE, "src:acme/tools")
    assert names(acme) == ["alpha", "beta"]
    assert views.group_stats(ins, CLAUDE, acme) == {
        "on": 1,
        "off": 1,
        "updates": 1,
        "edited": 1,
        "you_only": 0,
        "unused": 1,
    }
    assert names(views.members_of(ins, "all", "prj:webapp")) == ["proj-a"]


def test_group_keys_and_labels(ins):
    assert views.group_key(ins, by(ins, "kit-py-lint")) == "src:kit-py-*"
    assert views.group_key(ins, by(ins, "nap", "plugin")) == "plg:off@market"
    assert views.group_label(ins, by(ins, "nap", "plugin")) == "off"
    assert views.group_label(ins, {"kind": "avail", "repo": "o/r"}) == "o/r"
    assert views.hue_of(ins, by(ins, "alpha")) == views.hue("acme/tools")


def test_bulk_plan(ins):
    marked = [by(ins, "alpha"), by(ins, "beta"), by(ins, "gamma"), by(ins, "nap", "plugin")]
    plan = views.bulk_plan(ins, CLAUDE, marked)
    assert names(plan["on"]["skills"]) == ["beta"]
    assert plan["on"]["plugins"] == ["off@market"]
    assert names(plan["off"]["skills"]) == ["alpha", "gamma"]
    assert names(plan["update"]) == ["alpha"]
    assert names(plan["link"]) == ["gamma"]
    assert views.bulk_plan(ins, CURSOR, marked)["off"]["skills"] == []


@pytest.mark.parametrize(
    ("key", "value"),
    [("acme/tools", views.hue("acme/tools")), ("", views.HUES[5381 % 11])],
)
def test_hue_is_stable(key, value):
    assert views.hue(key) == value and value in views.HUES


@pytest.mark.parametrize(
    ("func", "arg", "out"),
    [
        (views.monogram, "@acme", "a"),
        (views.monogram, "--", "?"),
        (views.gh_repo, "https://github.com/acme/tools.git", "acme/tools"),
        (views.gh_repo, "git@github.com:acme/tools", "acme/tools"),
        (views.gh_repo, "acme/tools", "acme/tools"),
        (views.gh_repo, "not a repo", None),
        (views.tilde, "/Users/x/skills", "~/skills"),
    ],
)
def test_small_helpers(func, arg, out):
    assert func(arg) == out
