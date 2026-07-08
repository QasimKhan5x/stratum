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


def safe_grid_position(raw: object) -> tuple[int, int] | None:
    """Coerce a model-supplied grid_position into the (int, int) tuple
    WorldBibleEntry.grid_position expects, or None if it isn't a usable
    shape. Used by backend.agents.arbiter.synthesize and
    backend.agents.seed.generate_seed, both of which read grid_position
    straight out of model JSON output.

    ponytail: models occasionally return a malformed grid_position (wrong
    length, non-numeric elements, or a bare scalar instead of a pair) —
    without this, a plain `tuple(raw)` could raise TypeError (non-iterable
    input) or pass a bad value through to WorldBibleEntry's pydantic
    validation, which raises instead of degrading. Silently dropping to
    None (no position assigned) is an acceptable default here: the
    frontend already treats a missing grid_position as "unplaced," which
    is the honest outcome when the model didn't actually give a usable one.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    try:
        return (int(raw[0]), int(raw[1]))
    except (TypeError, ValueError):
        return None
