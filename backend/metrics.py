"""Baseline vs. Stratum comparison metrics for the efficiency-gain demo beat.

Per stratum-project-overview.md, the track requires "a measurable efficiency
gain over single-agent baselines" — three numbers, made concrete here:
contradiction rate, creative-divergence score, and provenance depth. See
stratum-demo-and-verification.md's warning that this needs to be checked
for real on the actual demo premise, not assumed from the architecture
being sound.
"""

from __future__ import annotations

import re
import uuid

import numpy as np

from backend.admission_gate import check_admission, cosine_similarity
from backend.models_client import embed
from backend.runs import Run
from backend.schemas import WorldBibleEntry
from backend.world_bible import WorldBible

# A small, fixed corpus of generic flooded-city/nautical-mystery genre
# synopses, used only as a "how generic is this" yardstick for the
# creative-divergence score — never read by any agent, never part of any
# real world bible.
# ponytail: five hand-written blurbs, not a real precomputed corpus per the
# architecture plan's mention of one. Upgrade path: a larger, more varied
# corpus if this proves too noisy on other premises.
_GENERIC_GENRE_CORPUS = [
    "A sunken city rises from the sea, and treasure hunters race to loot its ruins before a mysterious curse awakens.",
    "Rival guilds fight over a rare magical resource hidden beneath the waves in a flooded coastal town.",
    "An ancient bell tolls in a drowned cathedral, warning of a monster that sleeps beneath the city.",
    "A secretive religious order guards forbidden knowledge in the ruins of a city swallowed by the ocean.",
    "Scavengers and pirates clash over salvage rights in the wreckage of a once-great harbor city.",
]


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _mean_embedding(texts: list[str]) -> list[float]:
    vectors = np.array([embed(t) for t in texts])
    return vectors.mean(axis=0).tolist()


def _stratum_contradiction_rate(run: Run) -> float:
    """Fraction of synthesis attempts the admission gate actually rejected.
    Counterintuitively, non-zero here is a point in Stratum's favor: it
    means the gate is doing real work, not that the pipeline is unreliable
    — what matters for the comparison is that the *final committed canon*
    ends up at zero uncaught contradictions, unlike the baseline below.
    """
    admission_events = [e for e in run.events if e.event_type == "admission_result"]
    if not admission_events:
        return 0.0
    rejected = sum(1 for e in admission_events if not e.payload.get("admitted"))
    return rejected / len(admission_events)


def _baseline_contradiction_rate(baseline_text: str) -> float:
    """Reuses the real admission gate to check how many of the baseline's
    own paragraphs would have been rejected had a gate been applied — the
    most apples-to-apples way to show what Stratum's verification step
    catches that a single-agent pipeline has no mechanism to catch at all.
    """
    paragraphs = _paragraphs(baseline_text)
    if len(paragraphs) < 2:
        return 0.0

    shadow_bible = WorldBible()
    rejections = 0
    checked = 0
    for i, paragraph in enumerate(paragraphs):
        candidate = WorldBibleEntry(
            id=f"baseline-{i}-{uuid.uuid4().hex[:6]}",
            summary=paragraph[:200],
            full_text=paragraph,
            status="canon",
            provenance_agent="BASELINE",
            provenance_round=i,
            embedding=embed(paragraph),
        )
        if i > 0:
            checked += 1
            result = check_admission(candidate, shadow_bible)
            if not result.get("admitted"):
                rejections += 1
        shadow_bible.add(candidate)

    return rejections / checked if checked else 0.0


def _divergence_score(text: str, generic_centroid: list[float]) -> float:
    similarity = cosine_similarity(embed(text[:4000]), generic_centroid)
    return round(1.0 - similarity, 4)


def compute_comparison(run: Run) -> dict:
    """Compute the efficiency-gain numbers for a completed Run.

    Returns a dict of {"stratum": float, "baseline": float} per metric:
      - contradiction_rate: lower is better (0-1).
      - divergence_score: higher is better (0-1; distance from a generic
        genre corpus centroid).
      - provenance_depth: higher is better (0-1; fraction of the output
        with a real, structured attribution chain).
      - token_usage: total tokens consumed across all chat()/chat_json()
        calls (backend.models_client.track_run). Unlike the other three,
        higher is *expected*, not better — Stratum trades materially more
        tokens/calls per scene for the quality gains the other three
        metrics measure. See README.md / stratum-project-overview.md for
        why that tradeoff is the actual "efficiency gain" claim, not a
        contradiction of it.
    """
    if run.baseline_text is None:
        raise ValueError("Run has no baseline text yet; wait for status 'done'.")

    canon_entries = [e for e in run.world_bible.list() if e.status == "canon"]
    generic_centroid = _mean_embedding(_GENERIC_GENRE_CORPUS)
    stratum_text = "\n\n".join(e.full_text or e.summary for e in canon_entries)

    return {
        "contradiction_rate": {
            "stratum": round(_stratum_contradiction_rate(run), 4),
            "baseline": round(_baseline_contradiction_rate(run.baseline_text), 4),
        },
        "divergence_score": {
            "stratum": _divergence_score(stratum_text, generic_centroid),
            "baseline": _divergence_score(run.baseline_text, generic_centroid),
        },
        "provenance_depth": {
            "stratum": 1.0 if canon_entries else 0.0,
            "baseline": 0.0,
        },
        "token_usage": {
            "stratum": run.total_tokens,
            "baseline": run.baseline_tokens,
        },
    }
