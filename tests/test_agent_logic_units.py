"""Direct unit tests for the core agent-logic functions that previously had
no unit tests of their own — specialists.propose/critique, judges.score_all,
arbiter.synthesize, and seed.generate_seed were only exercised indirectly,
via monkeypatched stubs in test_resilience.py/test_traceability_fixes.py
that replace these functions entirely rather than testing their actual
internals.

Following the mocking pattern already established in
tests/test_mcp_admission_gate.py and tests/test_models_client.py: each
function's own `chat_json` import is monkeypatched directly (no real
network/LLM calls, no real DashScope client involved), fed realistic-but-
malformed LLM JSON output for each function's specific failure mode, and
asserted to degrade safely (default values, single bounded retry) rather
than crash the negotiation pipeline.
"""

from __future__ import annotations

import pytest

from backend.agents import arbiter, judges, seed, specialists
from backend.schemas import AgentRole, WorldBibleEntry
from backend.world_bible import WorldBible


# --------------------------------------------------------------------------
# specialists.critique — invalid cited_entry_id triggers exactly one retry
# --------------------------------------------------------------------------


def test_critique_retries_exactly_once_on_invalid_citation(monkeypatch):
    world_bible = WorldBible()
    world_bible.add(
        WorldBibleEntry(
            id="seed-1", summary="s", full_text="f", status="canon",
            provenance_agent="SEED", provenance_round=0,
        )
    )
    target_proposal = {"role": "PROVOCATEUR", "summary": "a proposal"}

    calls = {"count": 0}

    def fake_chat_json(role, messages, thinking=False):
        calls["count"] += 1
        if calls["count"] == 1:
            # A citation that doesn't exist in the world bible — must
            # trigger the retry-once mechanism.
            return {"critic_role": "LOREKEEPER", "target_role": "PROVOCATEUR", "cited_entry_id": "bogus-id", "objection": "o", "hard_flag": False}
        return {"critic_role": "LOREKEEPER", "target_role": "PROVOCATEUR", "cited_entry_id": "seed-1", "objection": "o", "hard_flag": False}

    monkeypatch.setattr(specialists, "chat_json", fake_chat_json)
    monkeypatch.setattr(specialists.time, "sleep", lambda seconds: None)  # skip the real backoff delay

    result = specialists.critique(AgentRole.LOREKEEPER, target_proposal, world_bible)

    assert calls["count"] == 2, "an invalid citation must trigger exactly one retry, not more, not zero"
    assert result["cited_entry_id"] == "seed-1"


def test_critique_does_not_retry_when_citation_is_valid(monkeypatch):
    world_bible = WorldBible()
    world_bible.add(
        WorldBibleEntry(
            id="seed-1", summary="s", full_text="f", status="canon",
            provenance_agent="SEED", provenance_round=0,
        )
    )
    calls = {"count": 0}

    def fake_chat_json(role, messages, thinking=False):
        calls["count"] += 1
        return {"critic_role": "LOREKEEPER", "target_role": "PROVOCATEUR", "cited_entry_id": "seed-1", "objection": "o", "hard_flag": False}

    monkeypatch.setattr(specialists, "chat_json", fake_chat_json)
    monkeypatch.setattr(specialists.time, "sleep", lambda seconds: (_ for _ in ()).throw(AssertionError("should not back off when there's no retry")))

    specialists.critique(AgentRole.LOREKEEPER, {"role": "PROVOCATEUR"}, world_bible)

    assert calls["count"] == 1


def test_propose_normalizes_role_and_defaults_missing_role(monkeypatch):
    """propose() should tolerate a model that mangles or omits the `role`
    field in its own JSON echo, normalizing/defaulting rather than
    crashing."""

    def fake_chat_json(role, messages, thinking=False):
        return {"scene_title": "t", "summary": "s", "full_text": "f", "role": "The Lorekeeper"}

    monkeypatch.setattr(specialists, "chat_json", fake_chat_json)

    result = specialists.propose(AgentRole.LOREKEEPER, WorldBible())

    assert result["role"] == "LOREKEEPER"


# --------------------------------------------------------------------------
# judges.score_all — a missing role in the model's response defaults to 5
# --------------------------------------------------------------------------


def test_score_all_defaults_missing_role_to_score_five(monkeypatch):
    proposals = [
        {"role": "LOREKEEPER", "summary": "a"},
        {"role": "PROVOCATEUR", "summary": "b"},
    ]

    def fake_chat_json(role, messages, thinking=False):
        # The model only scored LOREKEEPER, silently dropping PROVOCATEUR
        # from the batch — a real failure mode noted in judges.py's own
        # comments ("can drop a proposal from the batch entirely").
        return {"scores": [{"role_scored": "LOREKEEPER", "score": 9, "rationale": "great"}]}

    monkeypatch.setattr(judges, "chat_json", fake_chat_json)

    scored = judges.score_all("coherence", proposals, WorldBible())

    by_role = {entry["role_scored"]: entry for entry in scored}
    assert by_role["LOREKEEPER"]["score"] == 9
    assert by_role["PROVOCATEUR"]["score"] == 5
    assert by_role["PROVOCATEUR"]["rationale"] == "(model omitted a rationale for this score)"
    assert len(scored) == 2


def test_score_all_rejects_unknown_dimension():
    with pytest.raises(ValueError):
        judges.score_all("nonexistent-dimension", [], WorldBible())


def test_score_all_handles_empty_or_missing_scores_key(monkeypatch):
    proposals = [{"role": "ARCHITECT", "summary": "a"}]
    monkeypatch.setattr(judges, "chat_json", lambda role, messages, thinking=False: {})

    scored = judges.score_all("playability", proposals, WorldBible())

    assert scored == [{"dimension": "playability", "role_scored": "ARCHITECT", "score": 5, "rationale": "(model omitted a rationale for this score)"}]


# --------------------------------------------------------------------------
# arbiter.synthesize — a non-list/missing grid_position must not crash
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_grid_position",
    [
        None,  # missing entirely
        "not-a-list",  # bare string
        42,  # bare scalar, not iterable the way tuple() expects
        [1, 2, 3],  # wrong length
        ["x", "y"],  # non-numeric elements
    ],
)
def test_synthesize_handles_malformed_grid_position_without_crashing(monkeypatch, raw_grid_position):
    def fake_chat_json(role, messages, thinking=False):
        return {
            "summary": "s",
            "full_text": "f",
            "tags": [],
            "grid_position": raw_grid_position,
            "links": [],
            "favored_role": "LOREKEEPER",
            "overruled_role": None,
            "synthesis_notes": "n",
        }

    monkeypatch.setattr(arbiter, "chat_json", fake_chat_json)
    monkeypatch.setattr(arbiter, "embed", lambda text: [0.1, 0.2])

    entry, meta = arbiter.synthesize([], [], [], WorldBible())

    assert entry.grid_position is None
    assert entry.status == "contested"


def test_synthesize_preserves_a_well_formed_grid_position(monkeypatch):
    def fake_chat_json(role, messages, thinking=False):
        return {
            "summary": "s",
            "full_text": "f",
            "tags": [],
            "grid_position": [3, 4],
            "links": [],
            "favored_role": "LOREKEEPER",
            "overruled_role": None,
            "synthesis_notes": "n",
        }

    monkeypatch.setattr(arbiter, "chat_json", fake_chat_json)
    monkeypatch.setattr(arbiter, "embed", lambda text: [0.1, 0.2])

    entry, _ = arbiter.synthesize([], [], [], WorldBible())

    assert entry.grid_position == (3, 4)


# --------------------------------------------------------------------------
# seed.generate_seed — missing/null status defaults sensibly; other
# malformed shapes don't crash
# --------------------------------------------------------------------------


def test_generate_seed_defaults_missing_or_invalid_status_to_canon(monkeypatch):
    def fake_chat_json(role, messages, thinking=False):
        return {
            "entries": [
                {"summary": "a", "full_text": "fa", "grid_position": [0, 0]},  # status missing entirely
                {"summary": "b", "full_text": "fb", "status": None, "grid_position": [1, 1]},  # explicit null
                {"summary": "c", "full_text": "fc", "status": "not-a-real-status", "grid_position": [2, 2]},  # garbage value
                {"summary": "d", "full_text": "fd", "status": "contested", "grid_position": [3, 3]},  # valid, untouched
            ]
        }

    monkeypatch.setattr(seed, "chat_json", fake_chat_json)
    monkeypatch.setattr(seed, "embed", lambda text: [0.1, 0.2])

    entries = seed.generate_seed("a premise")

    assert [e.status for e in entries] == ["canon", "canon", "canon", "contested"]


def test_generate_seed_does_not_crash_on_other_malformed_shapes(monkeypatch):
    """Missing full_text/tags and malformed grid_position are all realistic
    ways a model can under-deliver on the requested JSON schema; none of
    them should raise."""

    def fake_chat_json(role, messages, thinking=False):
        return {
            "entries": [
                {"summary": "no full_text or tags at all"},
                {"summary": "bad grid position", "full_text": "f", "grid_position": "nonsense"},
                {"summary": "wrong-length grid position", "full_text": "f", "grid_position": [1, 2, 3]},
            ]
        }

    monkeypatch.setattr(seed, "chat_json", fake_chat_json)
    monkeypatch.setattr(seed, "embed", lambda text: [0.1, 0.2])

    entries = seed.generate_seed("a premise")

    assert len(entries) == 3
    assert entries[0].full_text == ""
    assert entries[0].tags == []
    assert entries[1].grid_position is None
    assert entries[2].grid_position is None


def test_generate_seed_handles_missing_entries_key(monkeypatch):
    monkeypatch.setattr(seed, "chat_json", lambda role, messages, thinking=False: {})

    entries = seed.generate_seed("a premise")

    assert entries == []
