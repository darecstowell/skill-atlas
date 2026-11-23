"""The web page's five palettes, light and dark, as Textual themes.

The OKLCH formulas are ported from the `:root` tokens in `web/index.html`.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from functools import cache, lru_cache
from typing import TYPE_CHECKING, Any, NamedTuple

from rich.color import Color as RichColor
from rich.color import ColorSystem
from textual.theme import Theme

if TYPE_CHECKING:
    from textual.app import App

Lab = tuple[float, float, float]
RGB = tuple[float, float, float]

# Neutral hue, neutral chroma scale, accent hue, accent chroma scale: `--nh --nk --ah --ak`.
_PARAMS: dict[str, tuple[float, float, float, float]] = {
    "atlas": (250, 1, 242, 1),
    "stone": (75, 1.6, 255, 0.9),
    "sage": (160, 1.4, 195, 0.85),
    "heather": (315, 1.3, 290, 0.9),
    "graphite": (250, 0, 250, 0),
}
PALETTES: tuple[str, ...] = tuple(_PARAMS)
SHADES = ("dark", "light")
MODES = ("system", *SHADES)
SPARK_HUE = 320
# Marks are the one tinted row background, so they differ from hover, focus, and press.
# Graphite, whose accent is grey, gets a near-grey mark in dark mode.
MARK_CHROMA = 0.03
# A card tint above this chroma in 256 colors reads as a block, so it takes a grey instead.
TINT_CHROMA = 0.08
CARD_TINTS = frozenset({"atlas-accent-tint", "atlas-warn-tint", "atlas-danger-tint"})

TOKENS: tuple[str, ...] = (
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
)


def _lch(lightness: float, chroma: float, hue: float) -> Lab:
    h = math.radians(hue)
    return (lightness, chroma * math.cos(h), chroma * math.sin(h))


@lru_cache(maxsize=128)
def identity(hue: float, dark: bool) -> tuple[str, str]:
    """A source's badge colors for its hue, as the web's `--id-bg` and `--id-fg`: (bg, fg)."""
    bg, fg = ((0.33, 0.07), (0.87, 0.1)) if dark else ((0.93, 0.045), (0.44, 0.12))
    return _hex(_lch(*bg, hue)), _hex(_lch(*fg, hue))


def _linear(lab: Lab) -> RGB:
    L, a, b = lab
    lc = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    mc = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    sc = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc,
        -1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc,
        -0.0041960863 * lc - 0.7034186147 * mc + 1.7076147010 * sc,
    )


def _in_gamut(rgb: RGB, eps: float = 1e-6) -> bool:
    return all(-eps <= x <= 1 + eps for x in rgb)


def _encode(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055


def _srgb(lab: Lab) -> RGB:
    """Gamut-map to sRGB by lowering chroma at fixed L and H; return encoded channels."""
    L, a, b = lab
    if L >= 1:
        return (1.0, 1.0, 1.0)
    if L <= 0:
        return (0.0, 0.0, 0.0)
    rgb = _linear(lab)
    if not _in_gamut(rgb):
        lo, hi = 0.0, 1.0
        for _ in range(30):
            mid = (lo + hi) / 2
            if _in_gamut(_linear((L, a * mid, b * mid))):
                lo = mid
            else:
                hi = mid
        rgb = _linear((L, a * lo, b * lo))
    r, g, bl = (_encode(x) for x in rgb)
    return (r, g, bl)


def _hex_rgb(rgb: RGB, alpha: float = 1.0) -> str:
    out = "#" + "".join(f"{round(x * 255):02x}" for x in rgb)
    return out if alpha >= 1 else out + f"{round(alpha * 255):02x}"


def _hex(lab: Lab, alpha: float = 1.0) -> str:
    return _hex_rgb(_srgb(lab), alpha)


def _mix(a: Lab, b: Lab, p: float) -> Lab:
    """`color-mix(in oklab, a p, b)`."""
    return (a[0] * p + b[0] * (1 - p), a[1] * p + b[1] * (1 - p), a[2] * p + b[2] * (1 - p))


def _over(fg: Lab, alpha: float, bg: Lab) -> str:
    """`fg` at `alpha` composited on `bg` in sRGB, as a browser paints it."""
    f, b = _srgb(fg), _srgb(bg)
    r, g, bl = (alpha * x + (1 - alpha) * y for x, y in zip(f, b, strict=True))
    return _hex_rgb((r, g, bl))


def _heat(empty: Lab, accent: Lab) -> list[Lab]:
    """Even L steps from the empty cell to the accent; chroma rises early to keep the hue."""
    c0, c4 = math.hypot(empty[1], empty[2]), math.hypot(accent[1], accent[2])
    hue = math.atan2(accent[2], accent[1])
    ramp = [empty]
    for k in range(1, 5):
        t = k / 4
        c = c0 + (c4 - c0) * t**0.6
        ramp.append((empty[0] + (accent[0] - empty[0]) * t, c * math.cos(hue), c * math.sin(hue)))
    return ramp


def _web(palette: str, dark: bool) -> dict[str, Lab]:
    nh, nk, ah, ak = _PARAMS[palette]

    def n(lightness: float, chroma: float) -> Lab:
        return _lch(lightness, chroma * nk, nh)

    def a(lightness: float, chroma: float) -> Lab:
        return _lch(lightness, chroma * ak, ah)

    if dark:
        return {
            "bg": n(0.165, 0.008),
            "surface-1": n(0.195, 0.009),
            "surface-2": n(0.235, 0.011),
            "surface-3": n(0.275, 0.012),
            "selection": n(0.315, 0.013),
            "mark": _lch(0.21, MARK_CHROMA * min(1.0, ak + 0.3), ah),
            "border": n(0.27, 0.01),
            "border-strong": n(0.34, 0.012),
            "text": n(0.95, 0.004),
            "text-2": n(0.80, 0.01),
            "text-3": n(0.66, 0.012),
            "text-disabled": n(0.48, 0.01),
            "off": n(0.52, 0.01),  # text-disabled with L raised to reach 3:1
            "accent": a(0.76, 0.11),
            "on-accent": a(0.17, 0.02),
            "on": _lch(0.76, 0.15, 155),
            "warn": _lch(0.82, 0.12, 75),
            "danger": _lch(0.76, 0.14, 25),
            "spark": _lch(0.68, 0.13, SPARK_HUE),
        }
    return {
        "bg": n(0.985, 0.003),
        "surface-1": (1.0, 0.0, 0.0),
        "surface-2": n(0.955, 0.005),
        "surface-3": n(0.925, 0.006),
        "selection": n(0.895, 0.007),
        "mark": _lch(0.94, MARK_CHROMA * min(1.0, ak + 0.7), ah),  # no room for a grey mark
        "text": n(0.23, 0.012),
        "text-2": n(0.43, 0.014),
        "text-3": n(0.52, 0.014),
        "text-disabled": n(0.68, 0.01),
        "off": n(0.64, 0.01),  # text-disabled with L lowered to reach 3:1
        "accent": a(0.50, 0.115),
        "on-accent": (1.0, 0.0, 0.0),
        "on": _lch(0.50, 0.115, 155),
        "warn": _lch(0.52, 0.11, 65),
        "danger": _lch(0.52, 0.17, 25),
        "spark": _lch(0.6, 0.14, SPARK_HUE),
    }


def _build(palette: str, mode: str) -> Theme:
    dark = mode == "dark"
    w = _web(palette, dark)
    s1, bg = w["surface-1"], w["bg"]
    if dark:
        border, border_strong = _hex(w["border"]), _hex(w["border-strong"])
    else:
        black = (0.0, 0.0, 0.0)
        border, border_strong = _over(black, 0.09, bg), _over(black, 0.16, bg)
    heat = _heat(w["surface-3"], w["accent"])
    h = {
        "background": _hex(bg),
        "atlas-surface-1": _hex(s1),
        "atlas-surface-2": _hex(w["surface-2"]),
        "atlas-surface-3": _hex(w["surface-3"]),
        "atlas-text": _hex(w["text"]),
        "atlas-muted": _hex(w["text-2"]),
        "atlas-faint": _hex(w["text-3"]),
        "atlas-accent": _hex(w["accent"]),
        "atlas-accent-tint": _hex(_mix(w["accent"], s1, 0.14)),
        "atlas-on-accent": _hex(w["on-accent"]),
        "atlas-border": border,
        "atlas-border-strong": border_strong,
        "atlas-selection": _hex(w["selection"]),
        "atlas-mark": _hex(w["mark"]),
        "atlas-on": _hex(w["on"]),
        "atlas-off": _hex(w["off"]),
        "atlas-spark": _hex(w["spark"]),
        **{f"atlas-heat-{k}": _hex(c) for k, c in enumerate(heat)},
        "atlas-add": _hex(w["on"]),
        "atlas-add-bg": _over(w["on"], 0.16, s1),
        "atlas-del": _hex(w["danger"]),
        "atlas-del-bg": _over(w["danger"], 0.16, s1),
        "atlas-warn": _hex(w["warn"]),
        "atlas-warn-tint": _hex(_mix(w["warn"], s1, 0.12)),
        "atlas-danger": _hex(w["danger"]),
        "atlas-danger-tint": _hex(_mix(w["danger"], s1, 0.12)),
        "foreground-disabled": _hex(w["text-disabled"]),
        "success-muted": _hex(_mix(w["on"], s1, 0.12)),
    }
    return _theme(name(palette, mode), h, dark, opaque=False)


def _alpha(hex_: str, alpha: float) -> str:
    return f"{hex_}{round(alpha * 255):02x}"


def _theme(theme_name: str, h: dict[str, str], dark: bool, opaque: bool) -> Theme:
    if opaque:
        boost = h["atlas-surface-2"]
        wash = shade = h["atlas-accent-tint"]
    else:
        boost = _alpha("#ffffff", 0.09) if dark else _alpha("#000000", 0.05)
        wash, shade = _alpha(h["atlas-accent"], 0.14), _alpha(h["atlas-accent"], 0.28)
    bg = h["background"]
    stock = {
        "text": h["atlas-text"],
        "text-muted": h["atlas-muted"],
        "text-disabled": h["atlas-faint"],
        "foreground-muted": h["atlas-muted"],
        "foreground-disabled": h["foreground-disabled"],
        "text-primary": h["atlas-accent"],
        "text-accent": h["atlas-accent"],
        "text-secondary": h["atlas-muted"],
        "text-success": h["atlas-on"],
        "text-warning": h["atlas-warn"],
        "text-error": h["atlas-danger"],
        "primary-muted": h["atlas-accent-tint"],
        "accent-muted": h["atlas-accent-tint"],
        "success-muted": h["success-muted"],
        "warning-muted": h["atlas-warn-tint"],
        "error-muted": h["atlas-danger-tint"],
        "border": h["atlas-accent"],
        "border-blurred": h["atlas-border"],
        "block-cursor-foreground": h["atlas-text"],
        "block-cursor-background": h["atlas-selection"],
        "block-cursor-text-style": "none",
        "block-cursor-blurred-foreground": h["atlas-text"],
        "block-cursor-blurred-background": h["atlas-surface-2"],
        "block-cursor-blurred-text-style": "none",
        "block-hover-background": h["atlas-surface-2"],
        "scrollbar": h["atlas-border-strong"],
        "scrollbar-hover": h["atlas-muted"],
        "scrollbar-active": h["atlas-text"],
        "scrollbar-background": bg,
        "scrollbar-background-hover": bg,
        "scrollbar-background-active": bg,
        "scrollbar-corner-color": bg,
        "link-color": h["atlas-accent"],
        "link-color-hover": h["atlas-text"],
        "link-background-hover": wash,
        "link-style-hover": "underline",
        "footer-foreground": h["atlas-muted"],
        "footer-background": h["atlas-surface-1"],
        "footer-key-foreground": h["atlas-accent"],
        "footer-description-foreground": h["atlas-muted"],
        "input-cursor-background": h["atlas-text"],
        "input-cursor-foreground": bg,
        "input-selection-background": shade,
        "input-selection-foreground": h["atlas-text"],
        "screen-selection-background": shade,
        "markdown-h1-color": h["atlas-text"],
        "markdown-h2-color": h["atlas-text"],
        "markdown-h2-text-style": "bold underline",
        "markdown-h3-color": h["atlas-text"],
        "markdown-h4-color": h["atlas-text"],
        "markdown-h4-text-style": "bold",
        "markdown-h5-color": h["atlas-muted"],
        "markdown-h6-color": h["atlas-muted"],
    }
    if dark:
        stock["panel-darken-1"] = h["atlas-surface-1"]
    return Theme(
        name=theme_name,
        primary=h["atlas-accent"],
        secondary=h["atlas-border-strong"],
        accent=h["atlas-accent"],
        foreground=h["atlas-text"],
        background=bg,
        surface=h["atlas-surface-1"],
        panel=h["atlas-surface-2"],
        boost=boost,
        success=h["atlas-on"],
        warning=h["atlas-warn"],
        error=h["atlas-danger"],
        dark=dark,
        variables={**stock, **{k: h[k] for k in TOKENS}},
    )


@cache
def system_shade() -> str:
    """The shade for mode "system": COLORFGBG, else the macOS look on a local session, else dark."""
    bg = os.environ.get("COLORFGBG", "").rsplit(";", 1)[-1]
    if bg.isdigit():
        return "light" if int(bg) in (7, 15) else "dark"
    if sys.platform != "darwin" or os.environ.get("SSH_TTY"):
        return "dark"
    try:
        out = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return "dark"
    return "dark" if out.stdout.strip() == "Dark" else "light"


def name(palette: str, mode: str) -> str:
    """The theme name for a palette and a mode, such as `stone-light`."""
    if palette not in _PARAMS or mode not in MODES:
        raise ValueError(f"unknown palette or mode: {palette!r}, {mode!r}")
    return f"{palette}-{system_shade() if mode == 'system' else mode}"


THEMES: dict[str, Theme] = {name(p, m): _build(p, m) for p in PALETTES for m in SHADES}

# ---- 256 colors: SSH often drops COLORTERM, so Rich falls back to the xterm palette.

LIMITED = ("256", "standard", "windows")
_LEVELS = (0, 95, 135, 175, 215, 255)
_LADDER = (
    "background",
    "atlas-surface-1",
    "atlas-surface-2",
    "atlas-surface-3",
    "atlas-selection",
    "atlas-mark",
)


class _Swatch(NamedTuple):
    number: int
    hex: str
    lab: Lab
    lum: float


Pool = list[tuple[_Swatch, float]]


def _decode(x: float) -> float:
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def _oklab(rgb: RGB) -> Lab:
    r, g, b = (_decode(x) for x in rgb)
    lc = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    mc = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    sc = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc,
        1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc,
        0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc,
    )


def _rgb(hex_: str) -> RGB:
    r, g, b = (int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return (r, g, b)


def _lum(rgb: RGB) -> float:
    r, g, b = (_decode(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a: float, b: float) -> float:
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _chroma(lab: Lab) -> float:
    return math.hypot(lab[1], lab[2])


def _hue_gap(a: Lab, b: Lab) -> float:
    d = abs(math.degrees(math.atan2(a[2], a[1]) - math.atan2(b[2], b[1]))) % 360
    return min(d, 360 - d)


def _cost(a: Lab, b: Lab) -> float:
    """Distance that counts lightness twice, since contrast lives in L."""
    return math.hypot(2 * (a[0] - b[0]), a[1] - b[1], a[2] - b[2])


@cache
def _xterm() -> tuple[_Swatch, ...]:
    """Palette colors 16-255, each with a hex value that Rich maps back to that index."""
    out = []
    for i in range(16, 256):
        if i < 232:
            n = i - 16
            rgb = (_LEVELS[n // 36], _LEVELS[n // 6 % 6], _LEVELS[n % 6])
            tries = [rgb]
        else:
            v = 8 + 10 * (i - 232)
            rgb = (v, v, v)
            tries = [(x, x, x) for x in sorted(range(256), key=lambda x: abs(x - v))[:12]]
        rich = (RichColor.from_rgb(*t).downgrade(ColorSystem.EIGHT_BIT).number for t in tries)
        rep = next((t for t, n in zip(tries, rich, strict=False) if n == i), None)
        if rep is None:
            continue
        shown = (rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
        out.append(_Swatch(i, "#{:02x}{:02x}{:02x}".format(*rep), _oklab(shown), _lum(shown)))
    return tuple(out)


def _greys() -> Pool:
    return [(s, 0.0) for s in _xterm() if _chroma(s.lab) < 0.005]


def _hued(target: Lab, window: float, grey: float | None = None) -> Pool:
    """Tinted swatches near the target's hue, plus greys at a cost when `grey` is set."""
    if _chroma(target) < 0.02:
        return _greys()
    tinted = [
        (s, 0.0) for s in _xterm() if _chroma(s.lab) >= 0.02 and _hue_gap(s.lab, target) <= window
    ]
    return tinted + ([] if grey is None else [(s, grey) for s, _ in _greys()])


Need = tuple[_Swatch, float]


def _pick(target: Lab, pool: Pool, *needs: Need, avoid: tuple[_Swatch, ...] = ()) -> _Swatch:
    """The nearest swatch that meets each (ground, floor) contrast need, else the closest miss."""
    taken = {s.number for s in avoid}
    pool = [(s, p) for s, p in pool if s.number not in taken]

    def margin(s: _Swatch) -> float:
        return min((_ratio(s.lum, g.lum) / f for g, f in needs), default=1.0)

    fits = [(s, p) for s, p in pool if margin(s) >= 1]
    if fits:
        return min(fits, key=lambda sp: _cost(sp[0].lab, target) + sp[1])[0]
    return max(pool, key=lambda sp: margin(sp[0]))[0]


def _ladder(targets: list[Lab], pools: list[Pool]) -> list[_Swatch]:
    """One swatch per target with L rising in target-L order, at the least total cost."""
    order = sorted(range(len(targets)), key=lambda i: targets[i][0])
    paths: list[tuple[float, list[_Swatch]]] = [(0.0, [])]
    for i in order:
        step = []
        for s, p in pools[i]:
            prior = [
                (c, path) for c, path in paths if not path or path[-1].lab[0] < s.lab[0] - 1e-3
            ]
            if prior:
                c, path = min(prior, key=lambda cp: cp[0])
                step.append((c + _cost(s.lab, targets[i]) + p, [*path, s]))
        paths = step
    _, best = min(paths, key=lambda cp: cp[0])
    out: list[_Swatch] = [best[0]] * len(targets)
    for i, s in zip(order, best, strict=True):
        out[i] = s
    return out


def _snap(h: dict[str, str]) -> dict[str, str]:
    lab = {k: _oklab(_rgb(v)) for k, v in h.items()}
    greys = _greys()
    pools = [greys] * 6  # the mark too: a cube tint reads as a navy block; `◆` carries the state
    s = dict(zip(_LADDER, _ladder([lab[k] for k in _LADDER], pools), strict=True))
    bg, s1 = s["background"], s["atlas-surface-1"]

    def on(keys: tuple[str, ...], floor: float) -> tuple[Need, ...]:
        return tuple((s[k], floor) for k in keys)

    s["atlas-text"] = _pick(lab["atlas-text"], greys, *on(_LADDER, 7))
    reads = tuple(k for k in _LADDER if k != "atlas-surface-3")
    s["atlas-muted"] = _pick(lab["atlas-muted"], greys, *on(reads, 4.5))
    s["atlas-faint"] = _pick(lab["atlas-faint"], greys, (bg, 4.5))
    s["atlas-off"] = _pick(lab["atlas-off"], greys, (bg, 3), (s1, 3))
    s["foreground-disabled"] = _pick(lab["foreground-disabled"], greys)
    s["atlas-border"] = _pick(lab["atlas-border"], greys, avoid=(bg,))
    s["atlas-border-strong"] = _pick(
        lab["atlas-border-strong"], greys, avoid=(bg, s["atlas-border"])
    )
    base = (bg, s1, s["atlas-mark"], s["atlas-selection"])
    # Fixed hues pick first, so green stays green before the palette's accent tint picks.
    family = {
        "atlas-add-bg": "atlas-on",
        "success-muted": "atlas-on",
        "atlas-danger-tint": "atlas-danger",
        "atlas-del-bg": "atlas-danger",
        "atlas-warn-tint": "atlas-warn",
        "atlas-accent-tint": "atlas-accent",
    }

    def tint(k: str, *needs: Need) -> _Swatch:
        card = k in CARD_TINTS
        rivals = tuple(
            s[t]
            for t, ink in family.items()
            if t in s and ink != family[k] and not (card and t in CARD_TINTS)
        )
        pool = _hued(lab[family[k]], 45, grey=0.3)
        avoid = base + rivals
        if card:
            pool = [(sw, p) for sw, p in pool if _chroma(sw.lab) <= TINT_CHROMA]
            avoid += (s["atlas-surface-2"],)
        return _pick(lab[k], pool, (s["atlas-text"], 4.5), *needs, avoid=avoid)

    for k in family:
        s[k] = tint(k)
    # Each ink meets 4.5 on the page and on its own tint; the del glyph needs 3 on del-bg.
    inks = {
        "atlas-accent": (("atlas-accent-tint", 4.5),),
        "atlas-warn": (("atlas-warn-tint", 4.5),),
        "atlas-danger": (("atlas-danger-tint", 4.5), ("atlas-del-bg", 3)),
        "atlas-on": (("atlas-add-bg", 4.5), ("success-muted", 3)),
    }
    for k, tints in inks.items():
        needs = ((bg, 4.5), (s1, 4.5), *((s[t], f) for t, f in tints))
        s[k] = _pick(lab[k], _hued(lab[k], 30), *needs)
        for t, f in tints:
            if _ratio(s[k].lum, s[t].lum) < f:
                s[t] = tint(t, (s[k], f))
    s["atlas-spark"] = _pick(lab["atlas-spark"], _hued(lab["atlas-spark"], 30), (bg, 3))
    s["atlas-on-accent"] = _pick(lab["atlas-on-accent"], greys, (s["atlas-accent"], 4.5))
    s["atlas-add"], s["atlas-del"] = s["atlas-on"], s["atlas-danger"]
    heat = [f"atlas-heat-{i}" for i in range(5)]
    ends = {"atlas-heat-0": s["atlas-surface-3"], "atlas-heat-4": s["atlas-accent"]}
    heat_pools = [[(ends[k], 0.0)] if k in ends else _hued(lab[k], 40) for k in heat]
    s.update(zip(heat, _ladder([lab[k] for k in heat], heat_pools), strict=True))
    return {k: s[k].hex for k in h}


def to_256(theme: Theme) -> Theme:
    """The same theme snapped to the xterm 256-color palette, with every step kept apart."""
    v = theme.variables
    h = {k: v[k] for k in (*TOKENS, "foreground-disabled", "success-muted")}
    h["background"] = theme.background or v["atlas-surface-1"]
    return _theme(theme.name, _snap(h), theme.dark, opaque=True)


@cache
def themes_256() -> dict[str, Theme]:
    """All ten themes for terminals that show 256 colors or fewer."""
    return {n: to_256(t) for n, t in THEMES.items()}


def register(app: App[Any]) -> None:
    """Register all ten themes, in 256 colors when the terminal shows no more."""
    limited = app.console.color_system in LIMITED
    for theme in (themes_256() if limited else THEMES).values():
        app.register_theme(theme)


def colors(app: App[Any]) -> dict[str, str]:
    """The current theme's custom tokens as hex, for pure Rich renderers."""
    theme = app.current_theme
    if not set(TOKENS) <= theme.variables.keys():
        fallback = name("atlas", "dark" if theme.dark else "light")
        theme = app.get_theme(fallback) or THEMES[fallback]
    return {k: theme.variables[k] for k in TOKENS}
