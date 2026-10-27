"""Rough context cost of a skill, in tokens.

A harness lists each enabled skill's name and description in every session, and loads the
SKILL.md body only when the skill runs. Counts are estimates: about 4 characters per token.
"""

from __future__ import annotations

CHARS_PER_TOKEN = 4
# The list entry's markup around the name and description: tags, separators, the path.
LIST_OVERHEAD = 12


def estimate(text: str) -> int:
    """Tokens for a text, rounded up."""
    return -(-len(text) // CHARS_PER_TOKEN)


def costs(name: str, description: str, body: str) -> dict[str, int]:
    """The always-on cost (listed) and the on-use cost (body) of one skill."""
    return {
        "tokens_listed": estimate(name) + estimate(description) + LIST_OVERHEAD,
        "tokens_body": estimate(body.strip()),
    }
