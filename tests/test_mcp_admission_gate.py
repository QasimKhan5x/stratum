"""Tests for the MCP-backed admission-gate embedding screen
(backend.admission_gate._embedding_screen).

Exercises two paths without hitting DashScope: a genuine MCP round trip
through the real mcp_world_bible_server.py subprocess (success case), and
the in-process fallback the gate must use if that MCP call fails (failure
case) — see stratum-demo-and-verification.md's "never let a component's
failure crash the whole run" philosophy, and admission_gate._embedding_screen's
docstring.

Uses tiny fabricated embedding vectors (not real text-embedding-v4 output)
since only the cosine-similarity math matters here, not embedding quality —
so, like test_resilience.py, this needs no real API calls or mocked
DashScope client, just the LLM contradiction check (stage 2) mocked.
"""

from __future__ import annotations

from backend import admission_gate, mcp_world_bible_client
from backend.schemas import WorldBibleEntry
from backend.world_bible import WorldBible


def _entry(entry_id: str, embedding: list[float], status: str = "canon") -> WorldBibleEntry:
    return WorldBibleEntry(
        id=entry_id,
        summary=f"summary for {entry_id}",
        full_text=f"full text for {entry_id}",
        status=status,
        provenance_agent="SEED",
        provenance_round=0,
        embedding=embedding,
    )


def test_admission_gate_screens_via_real_mcp_round_trip(monkeypatch):
    """check_admission's stage-1 screen must genuinely go through the MCP
    server, not silently rely on the fallback — proven here by making the
    in-process fallback (`cosine_similarity`) raise if it's ever called.
    This only passes if the real subprocess round trip found the similar
    prior entry and let stage 2 (mocked here) run against it."""

    def _forbidden_fallback(a, b):
        raise AssertionError("Should not reach the in-process fallback: the MCP round trip should have succeeded.")

    monkeypatch.setattr(admission_gate, "cosine_similarity", _forbidden_fallback)
    monkeypatch.setattr(admission_gate, "chat_json", lambda role, messages, thinking=False: {"contradicts": False})

    world_bible = WorldBible()
    world_bible.add(_entry("prior-scene", embedding=[1.0, 0.0, 0.0]))
    candidate = _entry("candidate-scene", embedding=[1.0, 0.0, 0.0])

    result = admission_gate.check_admission(candidate, world_bible)

    assert result == {
        "admitted": True,
        "reason": "Similar prior entries found but none contradicted the candidate.",
        "conflicting_entry_id": None,
    }


def test_admission_gate_falls_back_when_mcp_call_fails(monkeypatch):
    """If the MCP call fails for any reason (server crash, timeout,
    malformed response), the gate must fall back to the identical
    in-process computation rather than crash the negotiation run — and
    still correctly catch a real contradiction via the (mocked) LLM
    stage 2 afterward."""

    def _broken_mcp_call(tool_name, arguments):
        raise mcp_world_bible_client.McpToolError("simulated MCP server failure")

    monkeypatch.setattr(mcp_world_bible_client, "call_tool", _broken_mcp_call)
    monkeypatch.setattr(
        admission_gate,
        "chat_json",
        lambda role, messages, thinking=False: {"contradicts": True, "reason": "simulated contradiction"},
    )

    world_bible = WorldBible()
    world_bible.add(_entry("prior-scene", embedding=[1.0, 0.0, 0.0]))
    candidate = _entry("candidate-scene", embedding=[1.0, 0.0, 0.0])

    result = admission_gate.check_admission(candidate, world_bible)

    assert result == {
        "admitted": False,
        "reason": "simulated contradiction",
        "conflicting_entry_id": "prior-scene",
    }
