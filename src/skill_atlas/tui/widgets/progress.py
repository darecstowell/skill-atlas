"""The row under the header: a rule, which fills as a progress bar while a job runs."""

from __future__ import annotations

from rich.console import RenderableType
from rich.style import Style
from rich.text import Text
from textual.color import Color
from textual.reactive import reactive
from textual.widget import Widget

from ...core import views
from .. import theme
from ..messages import JobChanged
from . import charts

STEP = 0.28
FADE = 0.18
VERBS = {"update": ("Updating", "Updated"), "install": ("Installing", "Installed")}


def fraction(view: dict) -> float:
    """The share of a job's items that are no longer queued or running."""
    items = list((view.get("items") or {}).values())
    if not items:
        return 1.0
    return sum(1 for i in items if i.get("state") not in views.RUNNING) / len(items)


def headline(view: dict) -> str:
    """`Updating 3 of 8…` while a job runs, `Updated 7 of 8` when it is done, as on the web."""
    items = list((view.get("items") or {}).values())
    ing, ed = VERBS["install" if view.get("kind") == "install" else "update"]
    if view.get("done"):
        return f"{ed} {sum(1 for i in items if i.get('state') == 'done')} of {len(items)}"
    finished = sum(1 for i in items if i.get("state") not in views.RUNNING)
    return f"{ing} {finished} of {len(items)}…"


class JobBar(Widget):
    """`─` in the border color; during a job, `━` in the accent fills with finished items."""

    ALLOW_SELECT = False
    DEFAULT_CSS = """
    JobBar { height: 1; width: 1fr; background: $background; }
    """

    fill: reactive[float] = reactive(0.0)
    fade: reactive[float] = reactive(0.0)

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.active = False
        self.fading = False
        self._colors: dict[str, str] | None = None

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self._on_theme)

    def _on_theme(self, _: object) -> None:
        self._colors = None
        self.refresh()

    def on_job_changed(self, event: JobChanged) -> None:
        if event.view is None:
            self._fade_out()
            return
        if not self.active or self.fading:
            self._stop()
            self.fill = 0.0
            self.fade = 0.0
        self.active = True
        self.fading = False
        self.tooltip = headline(event.view)
        self.animate("fill", fraction(event.view), duration=STEP, easing="out_quart", level="full")
        self.refresh()

    def _stop(self) -> None:
        for name in ("fill", "fade"):
            self.app.animator.force_stop_animation(self, name)

    def _fade_out(self) -> None:
        if not self.active or self.fading:
            return
        self.fading = True
        self.animate(
            "fade", 1.0, duration=FADE, easing="in_cubic", level="full", on_complete=self._rest
        )

    def _rest(self) -> None:
        if self.fading:
            self.active = self.fading = False
            self.fill = self.fade = 0.0
            self.tooltip = None
            self.refresh()

    def render(self) -> RenderableType:
        width = self.size.width
        if self._colors is None:
            self._colors = theme.colors(self.app)
        colors = self._colors
        if not self.active:
            return Text("─" * width, Style(color=colors["atlas-border"]), end="")
        fill = Color.parse(colors["atlas-accent"]).blend(
            Color.parse(colors["atlas-border"]), self.fade
        )
        return charts.progress(self.fill, width, {**colors, "atlas-accent": fill.hex})
