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
from backend.models_client import chat_json, embed
from backend.runs import Run
from backend.schemas import WorldBibleEntry
from backend.world_bible import WorldBible

# A small, fixed corpus of generic interactive-fiction genre synopses, used
# only as a "how generic is this" yardstick for the creative-divergence
# score — never read by any agent, never part of any real world bible.
# ponytail: 20 hand-written blurbs spanning several common IF tropes (not
# just flooded-city/nautical-mystery, which is Stratum's own demo premise —
# a corpus that narrow would make the divergence score meaningless for any
# other premise, since it would really just be measuring "distance from our
# own demo" rather than "distance from generic IF"). Still not a real
# precomputed corpus per the architecture plan's original mention of one.
# Upgrade path: swap for an actual precomputed embedding set (e.g. sampled
# from a genre-fiction dataset) if this hand-written set proves too small a
# sample to be a stable centroid.
_GENERIC_GENRE_CORPUS = [
    "A sunken city rises from the sea, and treasure hunters race to loot its ruins before a mysterious curse awakens.",
    "Rival guilds fight over a rare magical resource hidden beneath the waves in a flooded coastal town.",
    "An ancient bell tolls in a drowned cathedral, warning of a monster that sleeps beneath the city.",
    "A secretive religious order guards forbidden knowledge in the ruins of a city swallowed by the ocean.",
    "Scavengers and pirates clash over salvage rights in the wreckage of a once-great harbor city.",
    "A family inherits an old Victorian house and slowly discovers it is haunted by a tragedy from generations past.",
    "A groundskeeper investigates strange noises in a mansion's west wing, uncovering a ghost bound to unfinished business.",
    "A group of friends spend the night in an abandoned asylum and are picked off one by one by something unseen.",
    "A new tenant realizes their apartment building conceals a portal to a nightmare version of itself.",
    "A remote research outpost loses contact with the mainland after a strange signal begins repeating from deep space.",
    "The last surviving crew of a damaged space station must figure out which of them isn't human anymore.",
    "A colony ship's AI begins making decisions the crew never authorized, and no one knows how long it's been happening.",
    "A deep-space mining team drills into something that was never meant to be found, and it starts drilling back.",
    "Survivors of a collapsed civilization scavenge a ruined city for supplies while a militia enforces its own brutal order.",
    "A wanderer arrives at a walled settlement that seems peaceful, until they learn what keeps it safe from the wasteland outside.",
    "A courier crosses irradiated badlands carrying a message that three separate factions are willing to kill for.",
    "A detective is called back to their hometown to solve a murder that mirrors an unsolved case from decades earlier.",
    "An heir returns to claim a family estate and finds the will's conditions are stranger, and more dangerous, than expected.",
    "A small town's yearly festival hides a decades-old ritual that the newest arrival is unknowingly about to complete.",
    "A group of strangers wake up in a locked building with no memory of how they got there, or of each other.",
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


def _baseline_contradiction_details(baseline_text: str) -> list[dict]:
    """Reuses the real admission gate to check how many of the baseline's
    own paragraphs would have been rejected had a gate been applied — the
    most apples-to-apples way to show what Stratum's verification step
    catches that a single-agent pipeline has no mechanism to catch at all.

    Returns one dict per paragraph after the first (a lone opening
    paragraph has nothing yet to contradict): {"index", "text" (truncated),
    "contradicts", "reason", "conflicts_with_index"}. This is the evidence
    behind contradiction_rate's baseline number, not just the aggregate
    rate — per stratum-critical-review-checklist.md, an abstract percentage
    doesn't land with a reader the way pointing at the actual sentence that
    contradicts an actual earlier sentence does; the frontend's baseline
    comparison panel highlights exactly these paragraphs.
    """
    paragraphs = _paragraphs(baseline_text)
    if len(paragraphs) < 2:
        return []

    shadow_bible = WorldBible()
    index_by_entry_id: dict[str, int] = {}
    details: list[dict] = []
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
            result = check_admission(candidate, shadow_bible)
            conflicting_id = result.get("conflicting_entry_id")
            details.append({
                "index": i,
                "text": paragraph[:300],
                "contradicts": not result.get("admitted", True),
                "reason": result.get("reason", ""),
                "conflicts_with_index": index_by_entry_id.get(conflicting_id),
            })
        index_by_entry_id[candidate.id] = i
        shadow_bible.add(candidate)

    return details


def _baseline_contradiction_rate(baseline_text: str) -> float:
    """Aggregate rate derived from _baseline_contradiction_details — kept as
    a separate function since every existing caller (contradiction_rate's
    "baseline" and "reflective_baseline" columns) only wants the single
    number, not the per-paragraph evidence.
    """
    details = _baseline_contradiction_details(baseline_text)
    if not details:
        return 0.0
    return sum(1 for d in details if d["contradicts"]) / len(details)


def _stratum_provenance_depth(run: Run) -> float:
    """Fraction of admitted, negotiated (non-seed) canon entries whose
    *winning* attempt actually cited a real prior world-bible entry in its
    critique stage — a concrete, per-entry signal of "is this grounded in
    specific prior canon," not the flat 1.0/0.0 "did any canon get
    admitted at all" this used to return regardless of content.

    Seed entries are excluded from the denominator: they're generated
    directly with no critique/citation stage, so citation-grounding isn't
    a meaningful question to ask of them.
    """
    canon_entries = [
        e for e in run.world_bible.list()
        if e.status == "canon" and e.provenance_agent == "ARBITER"
    ]
    if not canon_entries:
        return 0.0

    known_ids = {e.id for e in run.world_bible.list()}
    grounded = 0
    for entry in canon_entries:
        admissions = [
            ev for ev in run.events
            if ev.event_type == "admission_result"
            and ev.scene == entry.provenance_round
            and ev.payload.get("admitted")
            and ev.payload.get("entry_id") == entry.id
        ]
        winning_attempt = admissions[0].attempt if admissions else None
        critiques = [
            ev for ev in run.events
            if ev.event_type == "critique"
            and ev.scene == entry.provenance_round
            and (winning_attempt is None or ev.attempt == winning_attempt)
        ]
        if any(c.payload.get("cited_entry_id") in known_ids for c in critiques):
            grounded += 1
    return round(grounded / len(canon_entries), 4)


def _divergence_score(text: str, generic_centroid: list[float]) -> float:
    similarity = cosine_similarity(embed(text[:4000]), generic_centroid)
    return round(1.0 - similarity, 4)


_PREMATURE_RESOLUTION_PROMPT = (
    "You are a strict literary judge checking whether a piece of interactive-"
    "fiction text collapses a DELIBERATELY unresolved, contested question "
    "into one single confident answer. The question was seeded as genuinely "
    "ambiguous on purpose — multiple factions/characters are meant to "
    "disagree, and no one interpretation should be confirmed as simply true. "
    "Read the text and decide: does it state or clearly imply one single, "
    "confirmed answer to the contested question (premature resolution), or "
    "does it preserve the ambiguity (competing theories, unresolved, "
    "disputed)? Respond with JSON only: "
    '{"resolved": true or false, "reason": "<one sentence>"}'
)


def extract_contested_description(run: Run) -> str | None:
    """The seed step deliberately marks at least one world-bible entry
    "contested" (backend/agents/seed.py) — a genuine unresolved tension the
    rest of the run is supposed to keep alive, not settle by fiat. Returns
    that entry's text, or None if this run's seed produced no contested
    entry (defensive: seed prompts ask for at least one, but nothing
    enforces it at the schema level).
    """
    contested = [e for e in run.world_bible.list() if e.provenance_agent == "SEED" and e.status == "contested"]
    if not contested:
        return None
    return "\n".join(e.full_text or e.summary for e in contested)


def _resolves_contested_fact(text: str, contested_description: str) -> bool:
    """Per stratum-baseline-fairness-experiment.md's disclosed gap: does
    `text` prematurely resolve `contested_description` into one confident
    answer? Uses the same LLM-judge pattern as the admission gate's
    contradiction check (backend.admission_gate.check_admission) rather than
    an embedding heuristic, since "did this preserve ambiguity" is a reading-
    comprehension judgment, not a similarity measure.
    """
    result = chat_json(
        role="arbiter",
        messages=[
            {"role": "system", "content": _PREMATURE_RESOLUTION_PROMPT},
            {
                "role": "user",
                "content": (
                    f"CONTESTED QUESTION (deliberately meant to stay unresolved):\n{contested_description}\n\n"
                    f"TEXT TO CHECK:\n{text[:6000]}"
                ),
            },
        ],
    )
    return bool(result.get("resolved"))


def compute_comparison(
    run: Run,
    reflective_baseline_text: str | None = None,
    reflective_baseline_tokens: int = 0,
) -> dict:
    """Compute the efficiency-gain numbers for a completed Run.

    Returns a dict of {"stratum": float, "baseline": float} per metric:
      - contradiction_rate: lower is better (0-1).
      - divergence_score: higher is better (0-1; distance from a generic
        genre corpus centroid).
      - provenance_depth: higher is better (0-1; fraction of admitted,
        negotiated canon entries whose winning attempt's critique stage
        actually cited a real prior world-bible entry — not a flat
        1.0/0.0 "did any canon get admitted" flag).
      - token_usage: total tokens consumed across all chat()/chat_json()
        calls (backend.models_client.track_run). Unlike the other three,
        higher is *expected*, not better — Stratum trades materially more
        tokens/calls per scene for the quality gains the other three
        metrics measure. See README.md / stratum-project-overview.md for
        why that tradeoff is the actual "efficiency gain" claim, not a
        contradiction of it.
      - contradiction_detail (top-level key, only present when the baseline
        has 2+ paragraphs): {"baseline": [...]}, the actual per-paragraph
        evidence behind contradiction_rate's baseline number — which
        specific paragraph contradicted which earlier one, and why. Exists
        because an abstract rate doesn't land with a reader the way
        pointing at the real contradicting sentence does (see
        stratum-critical-review-checklist.md); the frontend's baseline
        comparison panel renders this to highlight the actual paragraphs.
      - premature_resolution: 1.0 if the variant's own text collapses the
        run's seed-marked "contested" fact into one confident answer, 0.0 if
        it preserves the ambiguity; None (key omitted from the affected
        column) if this run's seed produced no contested entry to check
        against. Lower is better. This is the fourth metric
        stratum-baseline-fairness-experiment.md flagged as missing — the
        prior three numbers could not distinguish "negotiation has a
        categorical creative advantage" from "more compute helps any
        approach"; this one targets the *specific* failure mode Stratum's
        Lorekeeper/admission-gate mechanism claims to prevent that a flat
        single-agent process has no structural way to avoid.

    Args:
        run: a completed Run (status "done", baseline_text populated).
        reflective_baseline_text: optional raw text from a SEPARATE,
            equal-compute-budget single-agent baseline — self-critique and
            revision rather than multi-agent debate (see
            backend.agents.baseline_reflective.generate_reflective_baseline
            and scripts/reflective_baseline_experiment.py). This is a
            one-off research variant, never generated as part of a normal
            run, so it defaults to None and every existing caller of this
            function (e.g. backend.main's /api/metrics) is unaffected. When
            provided, adds a third "reflective_baseline" column to each
            metric dict below, computed by the identical methodology as
            the "baseline" column (same admission-gate reuse for
            contradiction_rate, same generic-corpus centroid for
            divergence_score).
        reflective_baseline_tokens: total tokens spent generating
            reflective_baseline_text (from whichever scratch Run tracked
            it via backend.models_client.track_run) — only used for the
            token_usage row, and only if reflective_baseline_text is given.
    """
    if run.baseline_text is None:
        raise ValueError("Run has no baseline text yet; wait for status 'done'.")

    canon_entries = [e for e in run.world_bible.list() if e.status == "canon"]
    generic_centroid = _mean_embedding(_GENERIC_GENRE_CORPUS)
    stratum_text = "\n\n".join(e.full_text or e.summary for e in canon_entries)

    baseline_contradiction_details = _baseline_contradiction_details(run.baseline_text)

    result = {
        "contradiction_rate": {
            "stratum": round(_stratum_contradiction_rate(run), 4),
            "baseline": round(
                sum(1 for d in baseline_contradiction_details if d["contradicts"]) / len(baseline_contradiction_details)
                if baseline_contradiction_details
                else 0.0,
                4,
            ),
        },
        "divergence_score": {
            "stratum": _divergence_score(stratum_text, generic_centroid),
            "baseline": _divergence_score(run.baseline_text, generic_centroid),
        },
        "provenance_depth": {
            "stratum": _stratum_provenance_depth(run),
            "baseline": 0.0,
        },
        "token_usage": {
            "stratum": run.total_tokens,
            "baseline": run.baseline_tokens,
        },
    }

    if reflective_baseline_text is not None:
        result["contradiction_rate"]["reflective_baseline"] = round(
            _baseline_contradiction_rate(reflective_baseline_text), 4
        )
        result["divergence_score"]["reflective_baseline"] = _divergence_score(
            reflective_baseline_text, generic_centroid
        )
        # Same as the naive baseline: flat, unstructured prose with no
        # world-bible entries or attribution chain, regardless of how many
        # self-review rounds produced it.
        result["provenance_depth"]["reflective_baseline"] = 0.0
        result["token_usage"]["reflective_baseline"] = reflective_baseline_tokens

    if baseline_contradiction_details:
        result["contradiction_detail"] = {"baseline": baseline_contradiction_details}

    contested_description = extract_contested_description(run)
    if contested_description:
        result["premature_resolution"] = {
            "stratum": float(_resolves_contested_fact(stratum_text, contested_description)),
            "baseline": float(_resolves_contested_fact(run.baseline_text, contested_description)),
        }
        if reflective_baseline_text is not None:
            result["premature_resolution"]["reflective_baseline"] = float(
                _resolves_contested_fact(reflective_baseline_text, contested_description)
            )

    return result
