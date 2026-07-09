"""Tests for backend/metrics.py's premature_resolution metric: does a
variant's own text collapse a run's seed-marked "contested" fact into one
confident answer?

Mocks embed()/chat_json() throughout (no real DashScope calls) since only
the wiring/logic is under test here — the real-API version of this question
is answered by scripts/reflective_baseline_experiment.py against actual
model output, not by this file.
"""

from __future__ import annotations

from backend import metrics
from backend.runs import Run, create_run
from backend.schemas import WorldBibleEntry


def _seed_contested_entry(run: Run, text: str) -> None:
    run.world_bible.add(
        WorldBibleEntry(
            id="seed-contested",
            summary=text,
            full_text=text,
            status="contested",
            provenance_agent="SEED",
            provenance_round=0,
        )
    )


def test_extract_contested_description_returns_none_when_seed_has_no_contested_entry():
    run = create_run("A premise with no contested seed entry.")
    run.world_bible.add(
        WorldBibleEntry(
            id="seed-canon",
            summary="An uncontested fact.",
            full_text="An uncontested fact.",
            status="canon",
            provenance_agent="SEED",
            provenance_round=0,
        )
    )
    assert metrics.extract_contested_description(run) is None


def test_extract_contested_description_returns_the_seeded_text():
    run = create_run("premise")
    _seed_contested_entry(run, "Nobody agrees whether the bell tone is a hazard, a hoax, or a warning.")
    assert "hazard, a hoax, or a warning" in metrics.extract_contested_description(run)


def test_compute_comparison_flags_a_variant_that_collapses_the_contested_fact(monkeypatch):
    run = create_run("premise")
    run.status = "done"
    run.baseline_text = "Paragraph one.\n\nParagraph two, unrelated."
    run.total_tokens = 100
    run.baseline_tokens = 10
    _seed_contested_entry(run, "Nobody agrees whether the signal is a beacon or a warning.")
    run.world_bible.add(
        WorldBibleEntry(
            id="canon-1",
            summary="Stratum's own canon leaves the signal's nature disputed.",
            full_text="Stratum's own canon leaves the signal's nature disputed.",
            status="canon",
            provenance_agent="ARBITER",
            provenance_round=1,
        )
    )

    monkeypatch.setattr(metrics, "embed", lambda text: [1.0, 0.0])
    monkeypatch.setattr(metrics, "cosine_similarity", lambda a, b: 0.5)
    monkeypatch.setattr(metrics, "check_admission", lambda candidate, wb: {"admitted": True})

    def fake_chat_json(role, messages, thinking=False):
        # The baseline text is the one made to look like it collapses the
        # ambiguity; everything else preserves it.
        user_content = messages[-1]["content"]
        collapses = "Paragraph one." in user_content
        return {"resolved": collapses, "reason": "stub"}

    monkeypatch.setattr(metrics, "chat_json", fake_chat_json)

    comparison = metrics.compute_comparison(run)

    assert comparison["premature_resolution"] == {"stratum": 0.0, "baseline": 1.0}


def test_compute_comparison_surfaces_per_paragraph_contradiction_evidence(monkeypatch):
    """contradiction_detail must name the actual contradicting paragraph and
    which earlier paragraph it conflicts with — not just an aggregate rate."""
    run = create_run("premise")
    run.status = "done"
    run.baseline_text = "The bridge is intact.\n\nThe bridge collapsed years ago.\n\nA calm evening follows."
    run.total_tokens = 100
    run.baseline_tokens = 10

    monkeypatch.setattr(metrics, "embed", lambda text: [1.0, 0.0])
    monkeypatch.setattr(metrics, "cosine_similarity", lambda a, b: 0.5)

    # check_admission is called with a fresh uuid-suffixed candidate id each
    # time, so match on paragraph content instead of a fixed id, and prove
    # the real conflicting_entry_id -> paragraph-index lookup by returning
    # an actual id already added to the shadow world bible.
    monkeypatch.setattr(metrics, "check_admission", lambda candidate, wb: (
        {"admitted": False, "reason": "Contradicts the bridge being intact.", "conflicting_entry_id": next(iter(wb.list())).id}
        if "collapsed" in (candidate.full_text or "")
        else {"admitted": True, "reason": "ok", "conflicting_entry_id": None}
    ))

    comparison = metrics.compute_comparison(run)

    detail = comparison["contradiction_detail"]["baseline"]
    assert len(detail) == 2  # paragraphs 1 and 2 (paragraph 0 has nothing yet to contradict)
    assert detail[0]["contradicts"] is True
    assert detail[0]["conflicts_with_index"] == 0
    assert "collapsed" in detail[0]["text"]
    assert detail[1]["contradicts"] is False


def test_compute_comparison_omits_premature_resolution_when_no_contested_seed_entry(monkeypatch):
    run = create_run("premise")
    run.status = "done"
    run.baseline_text = "Some text."
    run.total_tokens = 100
    run.baseline_tokens = 10

    monkeypatch.setattr(metrics, "embed", lambda text: [1.0, 0.0])
    monkeypatch.setattr(metrics, "cosine_similarity", lambda a, b: 0.5)
    monkeypatch.setattr(metrics, "check_admission", lambda candidate, wb: {"admitted": True})

    comparison = metrics.compute_comparison(run)

    assert "premature_resolution" not in comparison
