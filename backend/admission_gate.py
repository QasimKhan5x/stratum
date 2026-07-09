"""Verified admission gate: checks a candidate scene against canon before
it is committed to the world bible.

This is a direct adaptation of DELM's corpus-grounded verification into
consistency-grounded verification against a living, agent-authored world
model: not "is this true" but "does this contradict what we've already
agreed."

Two-stage design:
  1. Cheap embedding-similarity screen (using the "embedding" model role,
     text-embedding-v4) against every existing canon entry. Checking every
     new proposal against every existing entry with an expensive LLM call
     does not scale as the world bible grows, so this stage cheaply
     narrows the field to only the entries plausibly related to the
     candidate. The similarity ranking itself is delegated to a local MCP
     server's `check_contradiction` tool (see backend/mcp_world_bible_server.py
     and _embedding_screen below), falling back to the identical in-process
     computation if that call fails for any reason.
  2. Expensive LLM contradiction check, fired only on the rare pairs that
     clear the similarity threshold from stage 1 — does the candidate
     actually contradict that specific prior entry.

In the Twine-targeted design, this stage also rejects passages linking to
a target passage that will never exist. Rejected scenes should trigger a
targeted re-negotiation of only the conflicting field, not a full restart
(see negotiation.run_scene).
"""

from __future__ import annotations

import logging

import numpy as np

from backend import mcp_world_bible_client
from backend.agents.prompts import ADMISSION_GATE_PROMPT
from backend.models_client import chat_json, embed
from backend.schemas import WorldBibleEntry
from backend.world_bible import WorldBible

logger = logging.getLogger(__name__)

# Cosine similarity above which two entries are plausibly related enough to
# be worth the expensive LLM contradiction check. text-embedding-v4
# similarities between genuinely unrelated passages of prose typically sit
# well below this; tune down if the demo premise's real embeddings show
# false negatives (missed contradictions) in testing.
_SIMILARITY_THRESHOLD = 0.75

_CONTRADICTION_SCHEMA = """Respond with JSON only, matching exactly this schema:
{
  "contradicts": true or false,
  "reason": "<brief explanation either way>"
}"""


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors, 0.0 if either is a
    zero vector (avoids a division-by-zero instead of raising)."""
    vec_a, vec_b = np.array(a), np.array(b)
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    return float(np.dot(vec_a, vec_b) / denom) if denom else 0.0


def _embedding_screen(
    candidate_embedding: list[float], existing: list[WorldBibleEntry]
) -> list[tuple[float, WorldBibleEntry]]:
    """Stage 1: narrow `existing` down to entries plausibly related to the
    candidate (cosine similarity >= _SIMILARITY_THRESHOLD), sorted
    most-similar first.

    Tries the MCP-hosted `check_contradiction` tool first (see
    backend/mcp_world_bible_server.py) — this is the project's one
    genuinely load-bearing MCP integration, so a real admission decision
    genuinely round-trips through MCP on the common path. Falls back to
    the identical computation in-process on ANY failure (server didn't
    start, timed out, malformed response): this runs on the critical path
    of every scene's admission decision, so an MCP hiccup must degrade
    gracefully, never crash a negotiation run.
    """
    try:
        entries_payload = [
            {"id": e.id, "summary": e.summary, "status": e.status, "embedding": e.embedding} for e in existing
        ]
        matches = mcp_world_bible_client.call_tool(
            "check_contradiction",
            {
                "candidate_embedding": candidate_embedding,
                "entries": entries_payload,
                "threshold": _SIMILARITY_THRESHOLD,
            },
        )
        by_id = {e.id: e for e in existing}
        return sorted(
            ((match["similarity"], by_id[match["id"]]) for match in matches if match["id"] in by_id),
            key=lambda pair: pair[0],
            reverse=True,
        )
    except Exception as exc:  # noqa: BLE001 - any MCP failure falls back rather than propagating
        logger.warning("MCP check_contradiction call failed (%s); falling back to in-process embedding screen.", exc)
        return sorted(
            (
                (similarity, entry)
                for entry in existing
                if (similarity := cosine_similarity(candidate_embedding, entry.embedding)) >= _SIMILARITY_THRESHOLD
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )


def check_admission(candidate: WorldBibleEntry, world_bible: WorldBible) -> dict:
    """Check whether a candidate entry may be admitted into the world bible.

    Args:
        candidate: the entry being considered for admission — usually an
            Arbiter-synthesized entry (see backend.agents.arbiter.synthesize),
            but also used by backend.metrics's baseline-contradiction check
            against synthetic "BASELINE"-provenance entries.
        world_bible: the current canon the candidate must not contradict.

    Returns:
        A result dict: {"admitted": bool, "reason": str,
        "conflicting_entry_id": str | None}.

    ponytail: the Twine-specific dangling-link check (rejecting passages
    that link to a target that will never exist) is deliberately NOT done
    here. During negotiation, a scene legitimately links forward to
    passages that don't exist yet but will be created in later rounds —
    "will never exist" is only knowable once generation is finished, so
    that check belongs in backend/twee_export.py at export time, not here
    per-scene. If dangling links prove to be a real problem in practice,
    the upgrade path is a final export-time validation pass, not retrofitting
    it into this per-scene gate.
    """
    candidate_embedding = candidate.embedding or embed(candidate.full_text or candidate.summary)

    existing = [e for e in world_bible.list() if e.status != "rejected" and e.id != candidate.id and e.embedding]

    # --- Stage 1: cheap embedding-similarity screen (via MCP; see
    # _embedding_screen). Only entries that clear this bar are worth the
    # expensive LLM call in stage 2 — this is what keeps the gate fast as
    # the world bible grows.
    similar = _embedding_screen(candidate_embedding, existing)

    if not similar:
        return {
            "admitted": True,
            "reason": "No sufficiently similar prior entries to check for contradiction.",
            "conflicting_entry_id": None,
        }

    # --- Stage 2: expensive LLM contradiction check, fired only on the
    # rare high-similarity pairs from stage 1. Deliberately uses the
    # "arbiter" model role rather than "judge": this call is rare and is
    # the one check the entire verified-admission mechanism depends on, so
    # correctness matters more than the cost savings a cheaper model would
    # offer here.
    for similarity, entry in similar:
        user_message = (
            f"EXISTING CANON ENTRY [{entry.id}] (status: {entry.status}):\n"
            f"{entry.full_text or entry.summary}\n\n"
            f"CANDIDATE NEW SCENE:\n{candidate.full_text or candidate.summary}\n\n"
            f"{_CONTRADICTION_SCHEMA}"
        )
        result = chat_json(
            role="arbiter",
            messages=[
                {"role": "system", "content": ADMISSION_GATE_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        if result.get("contradicts"):
            return {
                "admitted": False,
                "reason": result.get("reason", "Contradiction detected."),
                "conflicting_entry_id": entry.id,
            }

    return {
        "admitted": True,
        "reason": "Similar prior entries found but none contradicted the candidate.",
        "conflicting_entry_id": None,
    }
