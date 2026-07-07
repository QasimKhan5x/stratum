"""The SeedAgent: produces the initial world-bible entries from a premise.

Per stratum-architecture-plan.md, the SeedAgent runs on the "seed" model
role (qwen3.7-max) and is the only step that runs before any negotiation.
Its response is structured JSON, so backend.models_client.chat_json
intentionally disables DashScope thinking mode for this call.
"""

from __future__ import annotations

import uuid

from backend.agents.prompts import SEED_PROMPT
from backend.models_client import chat_json, embed
from backend.schemas import WorldBibleEntry

_SEED_SCHEMA = """Respond with JSON only, matching exactly this schema:
{
  "entries": [
    {
      "summary": "<1-2 sentence gist>",
      "full_text": "<full entry text, a paragraph or two>",
      "status": "canon" or "contested",
      "tags": ["<tag>", ...],
      "grid_position": [<x 0-5>, <y 0-4>]
    },
    ...
  ]
}
Produce 6 to 8 entries. At least one must have "status": "contested". \
Spread grid_position values across the full 0-5 by 0-4 range instead of \
clustering them near [0, 0]."""

_VALID_STATUS = {"canon", "contested", "rejected"}


def generate_seed(premise: str) -> list[WorldBibleEntry]:
    """Generate the foundational world-bible entries for a new world.

    Per the architecture plan, this should produce 6-8 foundational
    entries — enough concrete facts and at least one deliberately
    unresolved tension (an entry seeded with status "contested") for the
    specialists to have something real to argue about from round one. Each
    entry should get a position on the map grid.

    Args:
        premise: the user-submitted world premise.

    Returns:
        A list of new WorldBibleEntry objects (not yet added to any
        WorldBible instance — the caller is responsible for that).
    """
    user_message = (
        f"WORLD PREMISE:\n{premise}\n\n"
        "Generate the foundational world-bible entries for this world. "
        "Include concrete, specific facts (named factions, locations, the "
        "scarce resource driving conflict) and one deliberately unresolved, "
        "contested fact the specialists will have real grounds to argue "
        "about later — do not resolve it yourself.\n\n"
        f"{_SEED_SCHEMA}"
    )
    result = chat_json(
        role="seed",
        messages=[
            {"role": "system", "content": SEED_PROMPT},
            {"role": "user", "content": user_message},
        ],
        thinking=True,
    )

    entries: list[WorldBibleEntry] = []
    for i, raw in enumerate(result.get("entries", [])):
        full_text = raw.get("full_text", "")
        status = raw.get("status") if raw.get("status") in _VALID_STATUS else "canon"
        grid_position = raw.get("grid_position")
        entries.append(
            WorldBibleEntry(
                id=f"seed-{i:02d}-{uuid.uuid4().hex[:6]}",
                summary=raw.get("summary", ""),
                full_text=full_text,
                status=status,
                provenance_agent="SEED",
                provenance_round=0,
                grid_position=tuple(grid_position) if grid_position else None,
                embedding=embed(full_text) if full_text else None,
                tags=raw.get("tags", []),
                links=[],
            )
        )
    return entries
