"""The regions of the main screen. Each module keeps its styles in DEFAULT_CSS."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from textual.dom import DOMNode

    from ..app import AtlasApp


def app_of(node: DOMNode) -> AtlasApp:
    """The running AtlasApp, typed, for widgets that read state and data."""
    return cast("AtlasApp", node.app)
