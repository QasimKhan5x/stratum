"""The Arbiter: synthesizes one final scene from the round's debate.

Per stratum-architecture-plan.md, the Arbiter runs on the "arbiter" model
role (qwen3.7-max) for the final multi-objective synthesis step. The call
uses structured JSON, so DashScope thinking mode is intentionally disabled
by backend.models_client.chat_json.
"""

from __future__ import annotations

import json
import uuid

from backend.agent_roles import normalize_role, safe_grid_position
from backend.agents.prompts import ARBITER_PROMPT
from backend.models_client import chat_json, embed
from backend.schemas import WorldBibleEntry
from backend.world_bible import WorldBible

_SYNTHESIS_SCHEMA = """Respond with JSON only, matching exactly this schema:
{
  "summary": "<1-2 sentence gist>",
  "full_text": "<the full synthesized scene prose, 2-4 paragraphs>",
  "tags": ["<tag>", ...],
  "grid_position": [<x, 0-5>, <y, 0-4>],
  "links": ["<outbound link/passage name>", ...],
  "favored_role": "<role name whose proposal most shaped this synthesis>",
  "overruled_role": "<role name most overruled, or null if none was>",
  "synthesis_notes": "<your stated reasoning: what you favored, what you overruled, and why — this streams live to observers>"
}
Keep the favored proposal's grid_position unless it conflicts with an occupied cell; spread across the full 0-5 by 0-4 range rather than clustering near [0, 0]."""


def synthesize(
    proposals: list[dict],
    critiques: list[dict],
    judge_scores: list[dict],
    world_bible: WorldBible,
    revision_note: str | None = None,
) -> tuple[WorldBibleEntry, dict]:
    """Synthesis step: rule on one final scene for the current round.

    Informed by all four specialist proposals, their cross-critiques, and
    the judge panel's scores, the Arbiter must produce one final scene and
    state which proposal it favored and which it overruled. That stated
    reasoning is required output in its own right (it is what streams to
    the debate panel) — which is why this returns it alongside the entry
    rather than folding it into WorldBibleEntry's schema, which has no
    field for it.

    Args:
        proposals: the round's thesis proposals, one per specialist
            (see backend.agents.specialists.propose).
        critiques: the round's antithesis critiques
            (see backend.agents.specialists.critique).
        judge_scores: the round's judge panel scores
            (see backend.agents.judges.score_all).
        world_bible: the current world state the new entry must fit into.
        revision_note: on a retry after the admission gate rejected the
            prior synthesis for this scene, the gate's rejection reason —
            this is the actual "targeted re-negotiation" mechanism: without
            it, a retry is just a blind do-over with no memory of what was
            wrong, and specialists/arbiter tend to invent a *different*
            contradiction each time instead of converging.

    Returns:
        A tuple of (new WorldBibleEntry, synthesis_meta dict). The entry's
        status is "contested" — not yet "canon" — until the admission gate
        confirms it (see backend.negotiation.run_scene, which also fills in
        the real provenance_round; this function doesn't know which round
        it's running in). synthesis_meta carries favored_role,
        overruled_role, and synthesis_notes for the debate log.
    """
    hard_flags = [c for c in critiques if c.get("hard_flag")]
    user_message = (
        f"CURRENT CANON:\n{world_bible.canon_context()}\n\n"
        f"PROPOSALS:\n{json.dumps(proposals, indent=2)}\n\n"
        f"CRITIQUES:\n{json.dumps(critiques, indent=2)}\n\n"
        f"JUDGE SCORES:\n{json.dumps(judge_scores, indent=2)}\n\n"
        + (
            f"NOTE: {len(hard_flags)} critique(s) in this round carry "
            "\"hard_flag\": true. You must directly address each in "
            "synthesis_notes and let it materially constrain the final "
            "scene.\n\n"
            if hard_flags
            else ""
        )
        + (
            f"NOTE: your previous synthesis attempt for this exact scene was "
            f"REJECTED by the admission gate for this specific reason: "
            f"{revision_note}\nYou MUST resolve this exact contradiction "
            "this time — change only what is necessary to fix it, keeping "
            "everything else about your prior approach that wasn't the "
            "problem.\n\n"
            if revision_note
            else ""
        )
        + "Synthesize ONE final scene informed by all of the above. State "
        "which proposal you favored and which you overruled.\n\n"
        f"{_SYNTHESIS_SCHEMA}"
    )

    result = chat_json(
        role="arbiter",
        messages=[
            {"role": "system", "content": ARBITER_PROMPT},
            {"role": "user", "content": user_message},
        ],
        thinking=True,
    )

    full_text = result.get("full_text", "")
    grid_position = result.get("grid_position")
    entry = WorldBibleEntry(
        id=f"scene-{uuid.uuid4().hex[:8]}",
        summary=result.get("summary", ""),
        full_text=full_text,
        status="contested",
        provenance_agent="ARBITER",
        # Placeholder — backend.negotiation.run_scene overwrites this with
        # the real round number once the entry is returned; synthesize()
        # itself isn't given one (see the historical signature this
        # implements).
        provenance_round=0,
        grid_position=safe_grid_position(grid_position),
        embedding=embed(full_text) if full_text else None,
        tags=result.get("tags", []),
        links=result.get("links", []),
    )

    synthesis_meta = {
        "favored_role": normalize_role(result.get("favored_role")),
        "overruled_role": normalize_role(result.get("overruled_role")),
        "synthesis_notes": result.get("synthesis_notes", ""),
    }
    return entry, synthesis_meta
