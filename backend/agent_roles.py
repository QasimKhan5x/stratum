"""Normalizes free-text agent-role strings the models sometimes mangle.

Confirmed via real saved-run data: model outputs occasionally return role
names in inconsistent casing/wording (e.g. "The Harmonist", "HARMONIST")
instead of the canonical "Harmonist" in free-text JSON fields like `role`,
`favored_role`, `overruled_role`, `critic_role`, `target_role`. Those fields
aren't validated against AgentRole at the schema level (they're plain
strings inside DebateEvent.payload dicts), so a small shared normalizer is
the cheapest fix that doesn't require a bigger schema change.
"""

from __future__ import annotations

from backend.schemas import AgentRole

_CANONICAL_BY_UPPER = {role.value.upper(): role.value for role in AgentRole}


def normalize_role(raw: str | None) -> str | None:
    """Map a free-text role string back to its canonical AgentRole value.

    Case-insensitive, strips an optional leading "the ". Falls back to
    returning the original string unchanged (never raises) if it doesn't
    match any known role — this is advisory data for a debate log, not a
    gate-critical check, so a safe fallback beats crashing the pipeline.
    """
    if not raw or not isinstance(raw, str):
        return raw
    cleaned = raw.strip()
    upper = cleaned.upper()
    if upper.startswith("THE "):
        upper = upper[4:].strip()
    return _CANONICAL_BY_UPPER.get(upper, raw)
