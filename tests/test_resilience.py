"""Regression tests for two real failure modes hit during live testing
(see stratum-demo-and-verification.md's verification loop, step 2 —
state-machine checks with mocked agent responses):

1. A transient error mid-attempt (observed in practice: DashScope request
   timeouts under load) used to burn the whole scene instead of retrying.
2. An unhandled exception escaping backend.orchestrator.run_generation
   used to propagate out of the FastAPI BackgroundTasks callable with no
   caller left to catch it — which, in testing, took the entire uvicorn
   process down, not just the one failing run.

Both are mocked at the agent-call boundary rather than hitting DashScope,
per the "state-machine checks" layer of the verification loop: cheap, no
real API cost, and they fail immediately if the retry/no-reraise logic
regresses, without needing a human to notice a hung or crashed server.
"""

from __future__ import annotations

import pytest

from backend import negotiation, orchestrator
from backend.runs import Run
from backend.schemas import WorldBibleEntry
from backend.world_bible import WorldBible


def _stub_proposal(role) -> dict:
    return {"role": role.value, "scene_title": "t", "summary": "s", "full_text": "f", "tags": [], "grid_position": [0, 0]}


def _stub_critique(critic_role, target_proposal, world_bible) -> dict:
    return {"critic_role": critic_role.value, "target_role": target_proposal["role"], "objection": "none", "cited_entry_id": "n/a", "hard_flag": False}


def _stub_score_all(dimension, proposals, world_bible) -> list[dict]:
    return [{"dimension": dimension, "role_scored": p["role"], "score": 5, "rationale": "ok"} for p in proposals]


def _stub_synthesize(proposals, critiques, judge_scores, world_bible, revision_note=None):
    entry = WorldBibleEntry(
        id="scene-test", summary="s", full_text="f", status="contested",
        provenance_agent="ARBITER", provenance_round=0,
    )
    return entry, {"favored_role": "LOREKEEPER", "overruled_role": None, "synthesis_notes": "n"}


def test_transient_error_mid_attempt_is_retried_not_fatal(monkeypatch):
    """A raised exception on attempt 1's proposal step must not abort the
    scene — negotiation.run_scene should retry the whole attempt and still
    admit successfully once the transient failure clears."""
    calls = {"count": 0}

    def flaky_propose(role, world_bible, revision_note=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("simulated transient DashScope timeout")
        return _stub_proposal(role)

    monkeypatch.setattr(negotiation.specialists, "propose", flaky_propose)
    monkeypatch.setattr(negotiation.specialists, "critique", _stub_critique)
    monkeypatch.setattr(negotiation.judges, "score_all", _stub_score_all)
    monkeypatch.setattr(negotiation.arbiter, "synthesize", _stub_synthesize)
    monkeypatch.setattr(negotiation, "check_admission", lambda candidate, wb: {"admitted": True, "reason": "ok", "conflicting_entry_id": None})

    import asyncio

    result = asyncio.run(negotiation.run_scene(WorldBible(), round_number=1))
    assert result.status == "canon"
    # 4 specialists attempted on the failed pass (one raised, but
    # asyncio.gather still schedules all four) plus 4 on the retry.
    assert calls["count"] >= 5


def test_run_generation_never_reraises_on_failure(monkeypatch):
    """orchestrator.run_generation must set run.status = "failed" and
    return normally on an unrecoverable error, never propagate it — this
    is what previously crashed the whole uvicorn process (see
    orchestrator.py's run_generation docstring/comment on this)."""

    def boom(premise):
        raise RuntimeError("simulated unrecoverable seed-generation failure")

    monkeypatch.setattr(orchestrator, "generate_seed", boom)
    # Also stub the baseline call: it's kicked off concurrently before the
    # (mocked) seed step raises, and a real network call left running in
    # asyncio.to_thread's executor would make asyncio.run() hang on
    # shutdown waiting for that thread, not because the fix under test is
    # broken.
    monkeypatch.setattr(orchestrator, "generate_baseline", lambda premise: "stub baseline")

    import asyncio

    run = Run(id="test-run", premise="a premise")
    asyncio.run(orchestrator.run_generation(run, scene_count=1))  # must not raise

    assert run.status == "failed"
    assert "simulated unrecoverable seed-generation failure" in run.error
