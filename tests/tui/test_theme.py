import itertools
import math
import re

import pytest
from rich.color import Color as RichColor
from rich.color import ColorSystem
from textual.app import App, ComposeResult
from textual.color import Color
from textual.widgets import Static

from skill_atlas.tui import theme

CONTRACT = [
    "atlas-surface-1",
    "atlas-surface-2",
    "atlas-surface-3",
    "atlas-text",
    "atlas-muted",
    "atlas-faint",
    "atlas-accent",
    "atlas-accent-tint",
    "atlas-on-accent",
    "atlas-border",
    "atlas-border-strong",
    "atlas-selection",
    "atlas-mark",
    "atlas-on",
    "atlas-off",
    "atlas-spark",
    "atlas-heat-0",
    "atlas-heat-1",
    "atlas-heat-2",
    "atlas-heat-3",
    "atlas-heat-4",
    "atlas-add",
    "atlas-add-bg",
    "atlas-del",
    "atlas-del-bg",
    "atlas-warn",
    "atlas-warn-tint",
    "atlas-danger",
    "atlas-danger-tint",
]
THEMES = sorted(theme.THEMES)
LADDER = [
    "background",
    "atlas-surface-1",
    "atlas-surface-2",
    "atlas-surface-3",
    "atlas-selection",
    "atlas-mark",
]
LEVELS = (0, 95, 135, 175, 215, 255)


def channels(hex_: str) -> list[float]:
    return [int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5)]


def linear(x: float) -> float:
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def contrast(a: str, b: str) -> float:
    def lum(h: str) -> float:
        r, g, bl = (linear(x) for x in channels(h))
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def oklab(hex_: str) -> tuple[float, float, float]:
    """Hex to OKLab through XYZ with the CSS Color 4 matrices, apart from the module's path."""
    r, g, b = (linear(x) for x in channels(hex_))
    x = 0.41239079926595934 * r + 0.357584339383878 * g + 0.1804807884018343 * b
    y = 0.21263900587151027 * r + 0.715168678767756 * g + 0.07219231536073371 * b
    z = 0.01933081871559182 * r + 0.11919477979462598 * g + 0.9505321522496607 * b
    lms = [
        0.8190224379967030 * x + 0.3619062600528904 * y - 0.1288737815209879 * z,
        0.0329836539323885 * x + 0.9292868615863434 * y + 0.0361446663506424 * z,
        0.0481771893596242 * x + 0.2642395317527308 * y + 0.6335478284694309 * z,
    ]
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in lms)
    return (
        0.2104542683093140 * l_ + 0.7936177747023054 * m_ - 0.0040720430116193 * s_,
        1.9779985324311684 * l_ - 2.4285922420485799 * m_ + 0.4505937096174110 * s_,
        0.0259040424655478 * l_ + 0.7827717124575296 * m_ - 0.8086757549230774 * s_,
    )


def lch(L: float, c: float, h: float) -> tuple[float, float, float]:
    return (L, c * math.cos(math.radians(h)), c * math.sin(math.radians(h)))


def mix(a, b, p):
    return tuple(x * p + y * (1 - p) for x, y in zip(a, b, strict=True))


def tokens(name: str) -> dict[str, str]:
    t = theme.THEMES[name]
    return {**t.variables, "background": t.background or ""}


def index(hex_: str) -> int:
    """The xterm index that Rich sends for this color on a 256-color terminal."""
    n = RichColor.parse(hex_).downgrade(ColorSystem.EIGHT_BIT).number
    assert n is not None
    return n


def shown(hex_: str) -> str:
    """The color a 256-color terminal paints for this hex value."""
    i = index(hex_)
    if i < 232:
        n = i - 16
        rgb = (LEVELS[n // 36], LEVELS[n // 6 % 6], LEVELS[n % 6])
    else:
        rgb = (8 + 10 * (i - 232),) * 3
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def tokens_256(name: str) -> dict[str, str]:
    t = theme.themes_256()[name]
    return {
        k: shown(v)
        for k, v in {**t.variables, "background": t.background or ""}.items()
        if v.startswith("#")
    }


def hue_gap(a: str, b: str) -> float:
    (_, a1, b1), (_, a2, b2) = oklab(a), oklab(b)
    d = abs(math.degrees(math.atan2(b1, a1) - math.atan2(b2, a2))) % 360
    return min(d, 360 - d)


def test_ten_themes_with_the_contract_names():
    assert tuple(CONTRACT) == theme.TOKENS
    assert theme.PALETTES == ("atlas", "stone", "sage", "heather", "graphite")
    assert set(theme.THEMES) == {f"{p}-{m}" for p in theme.PALETTES for m in ("dark", "light")}
    assert theme.name("stone", "light") == "stone-light"
    for name, t in theme.THEMES.items():
        assert t.name == name
        assert t.dark is name.endswith("-dark")
    with pytest.raises(ValueError):
        theme.name("teal", "dark")
    with pytest.raises(ValueError):
        theme.name("atlas", "dim")


@pytest.mark.parametrize("name", THEMES)
def test_every_theme_has_every_token_as_hex(name):
    t = theme.THEMES[name]
    custom = {k for k in t.variables if k.startswith("atlas-")}
    assert custom == set(CONTRACT)
    for k in CONTRACT:
        assert re.fullmatch(r"#[0-9a-f]{6}", t.variables[k]), (k, t.variables[k])
    fields = (t.primary, t.secondary, t.accent, t.foreground, t.background, t.surface, t.panel)
    for value in (*fields, t.success, t.warning, t.error):
        assert value and re.fullmatch(r"#[0-9a-f]{6}", value)
    for value in t.variables.values():
        if value.startswith("#"):
            Color.parse(value)


@pytest.mark.parametrize("colors", ["truecolor", "256"])
@pytest.mark.parametrize("name", THEMES)
def test_contrast_floors_from_the_design_rules(name, colors):
    v = tokens(name) if colors == "truecolor" else tokens_256(name)
    grounds = ["background", "atlas-surface-1", "atlas-surface-2", "atlas-selection", "atlas-mark"]
    for g in [*grounds, "atlas-surface-3"]:
        assert contrast(v["atlas-text"], v[g]) >= 7, g
    for g in grounds:
        assert contrast(v["atlas-muted"], v[g]) >= 4.5, g
    tints = {"accent": "accent-tint", "on": "add-bg", "warn": "warn-tint", "danger": "danger-tint"}
    for fg, tint in tints.items():
        for g in ("background", "atlas-surface-1", f"atlas-{tint}"):
            assert contrast(v[f"atlas-{fg}"], v[g]) >= 4.5, (fg, g)
    assert contrast(v["atlas-on-accent"], v["atlas-accent"]) >= 4.5
    assert contrast(v["atlas-faint"], v["background"]) >= 4.5
    assert contrast(v["atlas-off"], v["background"]) >= 3
    assert contrast(v["atlas-off"], v["atlas-surface-1"]) >= 3
    for k in ("atlas-text", "atlas-add", "atlas-del"):
        assert contrast(v[k], v["atlas-add-bg"]) >= 3


MIN_STATE_DISTANCE = 0.025


@pytest.mark.parametrize("name", THEMES)
def test_hover_focus_press_and_mark_backgrounds_differ(name):
    v = theme.THEMES[name].variables
    states = ["atlas-surface-2", "atlas-selection", "atlas-surface-3", "atlas-mark"]
    for a, b in itertools.combinations(states, 2):
        assert math.dist(oklab(v[a]), oklab(v[b])) >= MIN_STATE_DISTANCE, (a, b)
    sel, mark = oklab(v["atlas-selection"]), oklab(v["atlas-mark"])
    assert math.hypot(sel[1], sel[2]) < 0.025
    if name != "graphite-dark":  # the neutral palette keeps a near-grey dark mark
        assert math.hypot(mark[1], mark[2]) > 0.02


def test_default_dark_matches_the_web_tokens():
    s1 = lch(0.195, 0.009, 250)
    accent, warn, danger = lch(0.76, 0.11, 242), lch(0.82, 0.12, 75), lch(0.76, 0.14, 25)
    web = {
        "background": lch(0.165, 0.008, 250),
        "atlas-surface-1": s1,
        "atlas-surface-2": lch(0.235, 0.011, 250),
        "atlas-surface-3": lch(0.275, 0.012, 250),
        "atlas-border": lch(0.27, 0.01, 250),
        "atlas-border-strong": lch(0.34, 0.012, 250),
        "atlas-text": lch(0.95, 0.004, 250),
        "atlas-muted": lch(0.80, 0.01, 250),
        "atlas-faint": lch(0.66, 0.012, 250),
        "atlas-accent": accent,
        "atlas-on-accent": lch(0.17, 0.02, 242),
        "atlas-on": lch(0.76, 0.15, 155),
        "atlas-warn": warn,
        "atlas-danger": danger,
        "atlas-spark": lch(0.68, 0.13, 320),
        "atlas-accent-tint": mix(accent, s1, 0.14),
        "atlas-warn-tint": mix(warn, s1, 0.12),
        "atlas-danger-tint": mix(danger, s1, 0.12),
    }
    v = tokens("atlas-dark")
    for k, want in web.items():
        assert math.dist(oklab(v[k]), want) < 0.004, k


def test_out_of_gamut_accent_keeps_lightness_and_hue():
    L, a, b = oklab(theme.THEMES["sage-light"].variables["atlas-accent"])
    assert abs(L - 0.50) < 0.005
    assert abs(math.degrees(math.atan2(b, a)) % 360 - 195) < 2
    assert math.hypot(a, b) < 0.115 * 0.85


@pytest.mark.parametrize("name", THEMES)
def test_heat_ramp_is_even_from_surface_to_accent(name):
    v = theme.THEMES[name].variables
    assert v["atlas-heat-0"] == v["atlas-surface-3"]
    assert v["atlas-heat-4"] == v["atlas-accent"]
    ls = [oklab(v[f"atlas-heat-{k}"])[0] for k in range(5)]
    steps = [b - a for a, b in itertools.pairwise(ls)]
    assert all(s > 0 for s in steps) or all(s < 0 for s in steps)
    assert max(steps) - min(steps) < 0.01


@pytest.mark.parametrize("name", THEMES)
def test_256_colors_keep_the_steps_apart_and_in_order(name):
    true, t = tokens(name), theme.themes_256()[name]
    raw = {**t.variables, "background": t.background or ""}
    v = tokens_256(name)
    for k, h in raw.items():
        if h.startswith("#"):
            assert len(h) == 7, k
            assert max(abs(a - b) for a, b in zip(channels(h), channels(v[k]), strict=True)) < 0.01
    assert len({index(raw[k]) for k in LADDER}) == len(LADDER)
    by_l = sorted(LADDER, key=lambda k: oklab(true[k])[0])
    assert sorted(LADDER, key=lambda k: oklab(v[k])[0]) == by_l
    heat = [oklab(v[f"atlas-heat-{i}"])[0] for i in range(5)]
    steps = [b - a for a, b in itertools.pairwise(heat)]
    assert all(s > 0 for s in steps) or all(s < 0 for s in steps)
    cards = ["atlas-accent-tint", "atlas-warn-tint", "atlas-danger-tint"]
    for k in cards:
        _, a, b = oklab(v[k])
        assert math.hypot(a, b) <= theme.TINT_CHROMA + 0.01, k
        assert index(raw[k]) not in {index(raw["atlas-surface-2"]), index(raw["atlas-add-bg"])}, k
    for k in ("atlas-accent", "atlas-on", "atlas-warn", "atlas-danger", "atlas-spark"):
        _, a, b = oklab(true[k])
        if math.hypot(a, b) >= 0.02:
            assert hue_gap(true[k], v[k]) <= 30, k


@pytest.mark.parametrize(
    ("term", "colorterm", "variant"),
    [
        ("xterm-256color", "truecolor", "truecolor"),
        ("xterm-256color", None, "256"),
        ("xterm", None, "256"),
    ],
)
def test_register_matches_the_terminal_colors(monkeypatch, term, colorterm, variant):
    monkeypatch.setenv("TERM", term)
    if colorterm:
        monkeypatch.setenv("COLORTERM", colorterm)
    else:
        monkeypatch.delenv("COLORTERM", raising=False)
    app = App()
    theme.register(app)
    want = theme.THEMES if variant == "truecolor" else theme.themes_256()
    assert all(app.get_theme(n) is t for n, t in want.items())
    app.theme = "stone-dark"
    assert theme.colors(app) == {k: want["stone-dark"].variables[k] for k in CONTRACT}


class Probe(Static):
    DEFAULT_CSS = "Probe { background: $atlas-surface-1; color: $atlas-text; }"


class ThemeApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        theme.register(self)
        self.theme = "sage-light"

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return theme.colors(self)

    def compose(self) -> ComposeResult:
        yield Probe("probe")


@pytest.mark.asyncio
async def test_register_on_a_minimal_app(monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    app = ThemeApp()
    async with app.run_test() as pilot:
        assert set(theme.THEMES) <= set(app.available_themes)
        want = theme.THEMES["sage-light"].variables
        probe = app.query_one(Probe)
        assert probe.styles.background.hex == want["atlas-surface-1"].upper()
        assert theme.colors(app) == {k: want[k] for k in CONTRACT}
        app.theme = "heather-dark"
        await pilot.pause()
        want = theme.THEMES["heather-dark"].variables
        assert probe.styles.background.hex == want["atlas-surface-1"].upper()
        app.theme = "textual-light"
        await pilot.pause()
        want = theme.THEMES["atlas-light"].variables
        assert theme.colors(app) == {k: want[k] for k in CONTRACT}
        assert probe.styles.background.hex == want["atlas-surface-1"].upper()


@pytest.fixture
def fresh_shade():
    theme.system_shade.cache_clear()
    yield
    theme.system_shade.cache_clear()


@pytest.mark.parametrize(
    ("env", "shade"),
    [
        ({"COLORFGBG": "0;15"}, "light"),
        ({"COLORFGBG": "15;0"}, "dark"),
        ({"COLORFGBG": "default;default", "SSH_TTY": "/dev/ttys001"}, "dark"),
    ],
)
def test_system_mode_follows_the_terminal(monkeypatch, fresh_shade, env, shade):
    monkeypatch.delenv("COLORFGBG", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert theme.name("stone", "system") == f"stone-{shade}"
    assert theme.name("stone", "light") == "stone-light"
