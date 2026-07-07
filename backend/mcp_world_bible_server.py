"""Local MCP server exposing the world bible's embedding-similarity lookup
as tools: `check_contradiction` and `search_world_bible`.

Runs as a stdio subprocess, spawned fresh per call by
backend.mcp_world_bible_client (see that module's docstring for why). Per
stratum-architecture-plan.md's "Technical Depth" goals, this is the one
genuinely load-bearing MCP integration in the project: admission_gate.py's
stage-1 embedding screen calls `check_contradiction` through this server
instead of computing cosine similarity in-process directly.

Deliberately dependency-free from the rest of backend/: this process takes
already-computed embedding vectors as input rather than calling DashScope
itself, so it needs no API key, no `backend.models_client` import, and no
network access at all — just numpy. That keeps the new operational surface
area this MCP integration adds to a minimum: one extra local subprocess,
no credentials, no network service.
"""

from __future__ import annotations

import numpy as np
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

# WARNING, not the default INFO: this server is spawned fresh on every
# admission-gate check during a negotiation run, so INFO-level per-request
# logging would spam stderr continuously without adding useful signal.
mcp = FastMCP("stratum-world-bible", log_level="WARNING")


class CanonEntry(BaseModel):
    """One existing world-bible entry, as much as the similarity tools need."""

    id: str
    summary: str
    status: str
    embedding: list[float]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a, vec_b = np.array(a), np.array(b)
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    return float(np.dot(vec_a, vec_b) / denom) if denom else 0.0


@mcp.tool()
def check_contradiction(
    candidate_embedding: list[float],
    entries: list[CanonEntry],
    threshold: float = 0.75,
) -> list[dict]:
    """Return existing canon entries plausibly related to a candidate.

    This is the admission gate's stage-1 "embedding screen": the cheap
    pre-filter that narrows every existing entry down to only the ones
    worth the expensive LLM contradiction check in stage 2. An entry is
    "plausibly related" if its cosine similarity to `candidate_embedding`
    clears `threshold`.

    Returns entries sorted most-similar first, each as
    {"id", "summary", "status", "similarity"}.
    """
    scored = sorted(
        ((_cosine_similarity(candidate_embedding, e.embedding), e) for e in entries),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return [
        {"id": e.id, "summary": e.summary, "status": e.status, "similarity": similarity}
        for similarity, e in scored
        if similarity >= threshold
    ]


@mcp.tool()
def search_world_bible(
    query_embedding: list[float],
    entries: list[CanonEntry],
    top_k: int = 5,
) -> list[dict]:
    """Return the `top_k` canon entries most semantically similar to
    `query_embedding`, regardless of similarity threshold — general
    semantic lookup over the world bible, as opposed to
    `check_contradiction`'s strict "is this plausibly related" screen.

    Returns entries sorted most-similar first, each as
    {"id", "summary", "status", "similarity"}.
    """
    scored = sorted(
        ((_cosine_similarity(query_embedding, e.embedding), e) for e in entries),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return [
        {"id": e.id, "summary": e.summary, "status": e.status, "similarity": similarity}
        for similarity, e in scored[:top_k]
    ]


if __name__ == "__main__":
    mcp.run(transport="stdio")
