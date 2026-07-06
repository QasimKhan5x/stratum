"""The four dimension-specific judges (coherence, playability, surprise, tone).

Per stratum-architecture-plan.md, judges run on the "judge" model role
(qwen3.6-flash, thinking off) — cheapest tier, since scoring against a
single stated dimension is low-complexity and highest-volume relative to
value. Escalate to "specialist" (qwen3.7-plus) if judge output proves
inconsistent in testing.
"""

from __future__ import annotations

import json

from backend.agents.prompts import (
    JUDGE_COHERENCE_PROMPT,
    JUDGE_PLAYABILITY_PROMPT,
    JUDGE_SURPRISE_PROMPT,
    JUDGE_TONE_PROMPT,
)
from backend.models_client import chat_json
from backend.world_bible import WorldBible

_DIMENSION_PROMPTS = {
    "coherence": JUDGE_COHERENCE_PROMPT,
    "playability": JUDGE_PLAYABILITY_PROMPT,
    "surprise": JUDGE_SURPRISE_PROMPT,
    "tone": JUDGE_TONE_PROMPT,
}

_SCORE_SCHEMA = """Respond with JSON only, matching exactly this schema:
{
  "scores": [
    {
      "role_scored": "<role name of the proposal being scored>",
      "score": <integer 1-10>,
      "rationale": "<one or two sentence justification, specific to your one dimension>"
    },
    ... one entry per proposal listed below, same order ...
  ]
}"""


def score_all(dimension: str, proposals: list[dict], world_bible: WorldBible) -> list[dict]:
    """Score every proposal along one judging dimension, in a single call.

    Part of the pluralistic judge panel (adapted from Debate2Create) that
    feeds the Arbiter's synthesis — each judge focuses on exactly one
    criterion so no single narrow optimum dominates the ruling. Batched by
    dimension (one call scores all proposals) rather than one call per
    (dimension, proposal) pair: this is the same 4 independent
    dimension-focused judges the design calls for, just each making one API
    call instead of four — cuts the panel from 16 calls to 4 per attempt
    without changing what's actually being judged or by whom.

    Args:
        dimension: one of "coherence", "playability", "surprise", "tone".
        proposals: every proposal payload being scored this round (as
            returned by backend.agents.specialists.propose).
        world_bible: the current world state, used as grounding context
            for the score (e.g. coherence is scored against existing canon).

    Returns:
        One score payload dict per proposal, in the same order, each
        matching the shape {"dimension", "role_scored", "score", "rationale"}.
    """
    if dimension not in _DIMENSION_PROMPTS:
        raise ValueError(f"Unknown judge dimension '{dimension}'. Expected one of {list(_DIMENSION_PROMPTS)}.")

    system_prompt = _DIMENSION_PROMPTS[dimension]
    numbered_proposals = "\n\n".join(
        f"PROPOSAL {i + 1} (from {proposal.get('role', 'unknown')}):\n{json.dumps(proposal, indent=2)}"
        for i, proposal in enumerate(proposals)
    )
    user_message = (
        f"CURRENT CANON:\n{world_bible.canon_context()}\n\n"
        f"PROPOSALS TO SCORE:\n{numbered_proposals}\n\n"
        f"{_SCORE_SCHEMA}"
    )
    result = chat_json(
        role="judge",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    raw_scores = result.get("scores") or []
    # Index by role so a model that reorders, drops, or duplicates entries
    # doesn't silently misalign scores with the wrong proposal.
    by_role = {entry.get("role_scored"): entry for entry in raw_scores if isinstance(entry, dict)}

    scored = []
    for proposal in proposals:
        role = proposal.get("role", "unknown")
        entry = by_role.get(role, {})
        # Observed in testing (single-proposal version): the judge model
        # occasionally omits fields despite the schema instruction, or here,
        # can drop a proposal from the batch entirely. Low-stakes advisory
        # signal (informs the Arbiter's synthesis, not gate-critical), so a
        # safe neutral default is cheaper and more robust than a retry
        # round-trip — unlike specialists.critique's citation retry, which
        # guards a mechanism that must hold.
        scored.append(
            {
                "dimension": dimension,
                "role_scored": role,
                "score": entry.get("score", 5),
                "rationale": entry.get("rationale", "(model omitted a rationale for this score)"),
            }
        )
    return scored
