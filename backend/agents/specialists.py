"""The four specialist agents: thesis (propose) and antithesis (critique).

Per stratum-architecture-plan.md, each specialist runs on the
"specialist" model role (qwen3.7-plus, thinking off) and reads the
current world bible before acting.
"""

from __future__ import annotations

import json

from backend.agent_roles import normalize_role
from backend.agents.prompts import (
    ARCHITECT_PROMPT,
    HARMONIST_PROMPT,
    LOREKEEPER_PROMPT,
    PROVOCATEUR_PROMPT,
)
from backend.models_client import chat_json
from backend.schemas import AgentRole
from backend.world_bible import WorldBible

_ROLE_PROMPTS = {
    AgentRole.LOREKEEPER: LOREKEEPER_PROMPT,
    AgentRole.PROVOCATEUR: PROVOCATEUR_PROMPT,
    AgentRole.HARMONIST: HARMONIST_PROMPT,
    AgentRole.ARCHITECT: ARCHITECT_PROMPT,
}

_PROPOSAL_SCHEMA = """Respond with JSON only, matching exactly this schema:
{
  "role": "<your role name, exactly as given above>",
  "scene_title": "<short title>",
  "summary": "<1-2 sentence gist other agents will read by default>",
  "full_text": "<the full playable scene prose, 2-4 paragraphs>",
  "tags": ["<tag>", ...],
  "grid_position": [<x, 0-5>, <y, 0-4>],
  "outbound_links": ["<name of a passage this scene could link to>", ...],
  "rationale": "<why this proposal serves your mandate>"
}
Spread grid_position across the full 0-5 by 0-4 range as the map fills in — do not cluster near [0, 0]."""

_CRITIQUE_SCHEMA = """Respond with JSON only, matching exactly this schema:
{
  "critic_role": "<your role name, exactly as given above>",
  "target_role": "<role name of the proposal you are critiquing>",
  "cited_entry_id": "<an existing world-bible entry ID from CURRENT CANON above, REQUIRED>",
  "objection": "<your specific objection, referencing the cited entry>",
  "hard_flag": false
}
Only the Harmonist may ever set "hard_flag" to true, and only for a severe \
tonal violation."""


def propose(role: AgentRole, world_bible: WorldBible, revision_note: str | None = None) -> dict:
    """Thesis step: one specialist proposes a scene for the current round.

    The specialist reads the current world bible (canon so far) and produces
    a candidate scene proposal consistent with its own mandate:
    Lorekeeper defends established canon, Provocateur pushes against the
    safest available option, Harmonist enforces tonal consistency, Architect
    owns spatial/playability logic and assigns a grid position.

    Args:
        role: which specialist is proposing (LOREKEEPER, PROVOCATEUR,
            HARMONIST, or ARCHITECT).
        world_bible: the current, canon-only world state this proposal
            must be consistent with (or deliberately push against, for
            the Provocateur).
        revision_note: on a retry after the admission gate rejected the
            prior synthesis for this scene, the gate's rejection reason —
            so specialists steer away from the specific contradiction
            already found, instead of blindly re-proposing (see
            backend.negotiation.run_scene, where this is threaded through).

    Returns:
        A proposal payload dict matching _PROPOSAL_SCHEMA, admissible into a
        DebateEvent's payload field.
    """
    system_prompt = _ROLE_PROMPTS[role]
    revision_block = (
        f"NOTE: a previous synthesis attempt for this scene was REJECTED by "
        f"the admission gate for this reason: {revision_note}\nYour proposal "
        "must not repeat this specific contradiction.\n\n"
        if revision_note
        else ""
    )
    user_message = (
        f"CURRENT CANON:\n{world_bible.canon_context()}\n\n"
        f"{revision_block}"
        f"Propose the next scene, consistent with your mandate as {role.value}.\n\n"
        f"{_PROPOSAL_SCHEMA}"
    )
    result = chat_json(
        role="specialist",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    result.setdefault("role", role.value)
    result["role"] = normalize_role(result["role"])
    return result


def critique(role: AgentRole, target_proposal: dict, world_bible: WorldBible) -> dict:
    """Antithesis step: one specialist critiques another's proposal.

    Per the architecture plan, critiques must cite a specific prior
    world-bible entry ID as evidence, or they are rejected and re-requested
    — this is the direct mitigation for the MAST failure-taxonomy finding
    that unstructured coordination causes most multi-agent failures.
    Structural pairing: Lorekeeper and Provocateur always critique each
    other; Harmonist and Architect are routed dynamically to whichever
    proposal is most tonally divergent or spatially weak.

    Args:
        role: which specialist is critiquing.
        target_proposal: the proposal payload (as returned by `propose`)
            being critiqued.
        world_bible: the current world state, used to find a citable entry.

    Returns:
        A critique payload dict matching _CRITIQUE_SCHEMA, including the
        cited entry ID and the objection text.
    """
    system_prompt = _ROLE_PROMPTS[role]
    valid_ids = {e.id for e in world_bible.list() if e.status != "rejected"}
    base_user_message = (
        f"CURRENT CANON:\n{world_bible.canon_context()}\n\n"
        f"PROPOSAL TO CRITIQUE (from {target_proposal.get('role', 'unknown')}):\n"
        f"{json.dumps(target_proposal, indent=2)}\n\n"
        f"Critique this proposal from your mandate as {role.value}. Your "
        "objection MUST cite a specific entry ID from CURRENT CANON above "
        "as evidence.\n\n"
        f"{_CRITIQUE_SCHEMA}"
    )

    result = chat_json(
        role="specialist",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": base_user_message},
        ],
    )

    # Citation enforcement: per the architecture plan, a critique with no
    # (or an invalid) citation is rejected and re-requested once, rather
    # than silently accepted — this is the direct mitigation for the MAST
    # finding that unstructured coordination causes most multi-agent
    # failures. `valid_ids` is only empty in the degenerate case of a
    # scene running against an empty world bible, which shouldn't happen
    # in practice since the seed step always runs first.
    if valid_ids and result.get("cited_entry_id") not in valid_ids:
        retry_message = base_user_message + (
            f"\n\nYour previous response cited '{result.get('cited_entry_id')}', "
            f"which is not a real entry ID. Valid entry IDs are: {sorted(valid_ids)}. "
            "You must cite one of these exactly."
        )
        result = chat_json(
            role="specialist",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": retry_message},
            ],
        )

    result.setdefault("critic_role", role.value)
    result["critic_role"] = normalize_role(result["critic_role"])
    if "target_role" in result:
        result["target_role"] = normalize_role(result["target_role"])
    return result
