"""Regression tests for the technical-audit fix batch (see
stratum-audit-fix-plan.md's Part B): attempt numbering, role normalization,
judge_score grouping, synthesis summary, phase tagging, and the SSE
double-yield bug in backend.main._stream_run.

Mocked at the agent-call boundary (same pattern as test_resilience.py) —
no real DashScope calls, no real API cost.
"""

from __future__ import annotations

import asyncio

import pytest

from backend import negotiation
from backend.agent_roles import normalize_role
from backend.main import _stream_run
from backend.metrics import _stratum_provenance_depth
from backend.runs import Run
from backend.schemas import DebateEvent, WorldBibleEntry
from backend.world_bible import WorldBible


def _stub_proposal(role) -> dict:
    return {"role": role.value, "scene_title": "t", "summary": "s", "full_text": "f", "tags": [], "grid_position": [0, 0]}


def _stub_critique(critic_role, target_proposal, world_bible) -> dict:
    return {"critic_role": critic_role.value, "target_role": target_proposal["role"], "objection": "none", "cited_entry_id": "n/a", "hard_flag": False}


def _stub_score_all(dimension, proposals, world_bible) -> list[dict]:
    return [{"dimension": dimension, "role_scored": p["role"], "score": 5, "rationale": "ok"} for p in proposals]


def _make_stub_synthesize(entry_id="scene-test", summary="candidate summary"):
    def _stub(proposals, critiques, judge_scores, world_bible, revision_note=None):
        from backend.schemas import WorldBibleEntry

        entry = WorldBibleEntry(
            id=entry_id, summary=summary, full_text="f", status="contested",
            provenance_agent="ARBITER", provenance_round=0,
        )
        return entry, {"favored_role": "LOREKEEPER", "overruled_role": None, "synthesis_notes": "n"}

    return _stub


def test_attempt_number_increments_across_retries(monkeypatch):
    """Every event from a scene's first pass must carry attempt=1; every
    event from a retry after rejection must carry attempt=2. This is the
    concrete fix for the audit's core traceability gap: a rejected-then-
    retried scene must be distinguishable from a clean one-pass admission
    without inferring it from counting duplicate events."""
    admission_calls = {"count": 0}

    def flaky_admission(candidate, world_bible):
        admission_calls["count"] += 1
        if admission_calls["count"] == 1:
            return {"admitted": False, "reason": "contradiction", "conflicting_entry_id": "seed-1"}
        return {"admitted": True, "reason": "ok", "conflicting_entry_id": None}

    monkeypatch.setattr(negotiation.specialists, "propose", lambda role, wb, revision_note=None: _stub_proposal(role))
    monkeypatch.setattr(negotiation.specialists, "critique", _stub_critique)
    monkeypatch.setattr(negotiation.judges, "score_all", _stub_score_all)
    monkeypatch.setattr(negotiation.arbiter, "synthesize", _make_stub_synthesize())
    monkeypatch.setattr(negotiation, "check_admission", flaky_admission)

    events: list[DebateEvent] = []
    asyncio.run(negotiation.run_scene(WorldBible(), round_number=1, on_event=events.append))

    attempt_1_events = [e for e in events if e.attempt == 1]
    attempt_2_events = [e for e in events if e.attempt == 2]
    assert attempt_1_events, "attempt 1 should have emitted events before rejection"
    assert attempt_2_events, "attempt 2 (the retry) should have emitted its own events"
    # The rejected attempt's admission_result must itself be tagged attempt=1,
    # not silently absorbed into attempt 2.
    rejected = [e for e in attempt_1_events if e.event_type == "admission_result"]
    assert rejected and rejected[0].payload["admitted"] is False


def test_judge_score_collapsed_into_one_event_per_attempt(monkeypatch):
    """16 individual scores (4 dimensions x 4 proposals) must collapse into
    a single judge_score DebateEvent per attempt, carrying all 16 as a
    structured list — not 16 separate top-level stream events."""
    monkeypatch.setattr(negotiation.specialists, "propose", lambda role, wb, revision_note=None: _stub_proposal(role))
    monkeypatch.setattr(negotiation.specialists, "critique", _stub_critique)
    monkeypatch.setattr(negotiation.judges, "score_all", _stub_score_all)
    monkeypatch.setattr(negotiation.arbiter, "synthesize", _make_stub_synthesize())
    monkeypatch.setattr(negotiation, "check_admission", lambda candidate, wb: {"admitted": True, "reason": "ok", "conflicting_entry_id": None})

    events: list[DebateEvent] = []
    asyncio.run(negotiation.run_scene(WorldBible(), round_number=1, on_event=events.append))

    judge_events = [e for e in events if e.event_type == "judge_score"]
    assert len(judge_events) == 1, f"expected exactly 1 judge_score event, got {len(judge_events)}"
    assert len(judge_events[0].payload["scores"]) == 16  # 4 dimensions x 4 proposals, data preserved


def test_synthesis_event_carries_candidate_summary(monkeypatch):
    """A rejected candidate's content must survive in the event stream via
    `summary` — previously only the opaque `entry_id` hash was captured."""
    monkeypatch.setattr(negotiation.specialists, "propose", lambda role, wb, revision_note=None: _stub_proposal(role))
    monkeypatch.setattr(negotiation.specialists, "critique", _stub_critique)
    monkeypatch.setattr(negotiation.judges, "score_all", _stub_score_all)
    monkeypatch.setattr(negotiation.arbiter, "synthesize", _make_stub_synthesize(summary="a very specific candidate summary"))
    monkeypatch.setattr(negotiation, "check_admission", lambda candidate, wb: {"admitted": True, "reason": "ok", "conflicting_entry_id": None})

    events: list[DebateEvent] = []
    asyncio.run(negotiation.run_scene(WorldBible(), round_number=1, on_event=events.append))

    synthesis_events = [e for e in events if e.event_type == "synthesis"]
    assert synthesis_events[0].payload["summary"] == "a very specific candidate summary"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("The Harmonist", "HARMONIST"),
        ("HARMONIST", "HARMONIST"),
        ("Harmonist", "HARMONIST"),
        ("harmonist", "HARMONIST"),
        ("  the Lorekeeper  ", "LOREKEEPER"),
        ("Not A Real Role", "Not A Real Role"),  # safe fallback, never raises
        (None, None),
    ],
)
def test_normalize_role(raw, expected):
    assert normalize_role(raw) == expected


def test_stream_run_does_not_double_yield_events_for_unwatched_finished_run():
    """Regression test for the confirmed root cause of demo_recordings/
    a3a1318598eb's ~50% duplicate events: a subscriber connecting to an
    already-"done" run that nobody watched live must see each event exactly
    once, not once from history replay plus once more from a leftover
    queue."""
    run = Run(id="test-run", premise="p")
    for i in range(5):
        run.emit(DebateEvent(round=1, scene=1, agent="LOREKEEPER", event_type="proposal", payload={"i": i}))
    run.status = "done"

    async def _collect():
        return [chunk async for chunk in _stream_run(run, grace_seconds=0.0)]

    chunks = asyncio.run(_collect())
    proposal_chunks = [c for c in chunks if "event: proposal" in c]
    assert len(proposal_chunks) == 5, f"expected exactly 5 proposal events, got {len(proposal_chunks)} (duplication bug regressed)"
    assert any("run_complete" in c for c in chunks)


def test_provenance_depth_is_graduated_not_a_flat_flag():
    """A canon entry whose winning attempt's critique cited a real prior
    entry counts as grounded; one whose critiques cited nothing real (or
    "n/a") does not — so the metric is a real per-entry fraction, not a
    flat 1.0 the moment any canon exists at all."""
    run = Run(id="test-run", premise="p")
    seed = WorldBibleEntry(id="seed-1", summary="s", full_text="f", status="canon", provenance_agent="SEED", provenance_round=0)
    grounded_entry = WorldBibleEntry(id="scene-1", summary="s", full_text="f", status="canon", provenance_agent="ARBITER", provenance_round=1)
    ungrounded_entry = WorldBibleEntry(id="scene-2", summary="s", full_text="f", status="canon", provenance_agent="ARBITER", provenance_round=2)
    for e in (seed, grounded_entry, ungrounded_entry):
        run.world_bible.add(e)

    run.events = [
        DebateEvent(round=1, scene=1, agent="LOREKEEPER", event_type="critique", attempt=1, payload={"cited_entry_id": "seed-1"}),
        DebateEvent(round=1, scene=1, agent="ARBITER", event_type="admission_result", attempt=1, payload={"entry_id": "scene-1", "admitted": True}),
        DebateEvent(round=2, scene=2, agent="LOREKEEPER", event_type="critique", attempt=1, payload={"cited_entry_id": "n/a"}),
        DebateEvent(round=2, scene=2, agent="ARBITER", event_type="admission_result", attempt=1, payload={"entry_id": "scene-2", "admitted": True}),
    ]

    assert _stratum_provenance_depth(run) == 0.5  # 1 of 2 negotiated entries grounded; seed excluded


def test_old_saved_event_json_without_new_fields_still_parses():
    """Backward compatibility: demo_recordings/*/event_log.json saved before
    this fix predates `attempt`/`phase` — DebateEvent must still parse it
    via the new fields' defaults, so old saved runs don't need regenerating."""
    old_style_payload = {
        "round": 1,
        "scene": 1,
        "agent": "LOREKEEPER",
        "event_type": "proposal",
        "payload": {"role": "LOREKEEPER"},
        # no "attempt", no "phase" — exactly what a pre-fix saved run has
    }
    event = DebateEvent(**old_style_payload)
    assert event.attempt == 1
    assert event.phase == "negotiation"
