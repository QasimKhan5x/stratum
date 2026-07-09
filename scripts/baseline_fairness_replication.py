#!/usr/bin/env python3
"""Replication of the reflective-baseline fairness experiment across
multiple premises, at closer-to-full token-budget parity.

Answers two open questions about the original experiment:

- The original experiment was n=1, one premise, one run — this runs it
  across 3 distinct premises (the locked demo premise plus two new ones,
  each with its own seed-marked contested question) so the
  divergence_score finding can be checked for consistency rather than
  trusted from a single roll.
- The original reflective baseline hit its `max_rounds=10` safety cap at
  ~47% of the target token budget, never actually reaching parity. This
  run raises the cap to `MAX_REFLECTIVE_ROUNDS` (see below) specifically so
  it can get much closer to (or reach) full parity, and reports the actual
  budget-utilization percentage achieved per premise rather than assuming
  it.

Also computes the premature_resolution metric (backend/metrics.py) across
every premise/variant, since that's the actual test of the
categorical-advantage claim — not one of the original three numbers.

This is a one-off research script, real DashScope calls, real wall-clock
time (expect this to run for an extended period across 3 premises x 3
variants). Not part of any live run path.

Usage:
    .venv/bin/python scripts/baseline_fairness_replication.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.agents.baseline_reflective import generate_reflective_baseline
from backend.metrics import compute_comparison
from backend.models_client import track_run
from backend.orchestrator import run_generation
from backend.runs import Run, create_run

# Premise 1: the locked demo premise verbatim, included so this
# replication is directly comparable to the original n=1 result. Premises
# 2-3 are new, each genre-distinct from the demo premise
# and from each other (per backend/metrics.py's own _GENERIC_GENRE_CORPUS
# diversity rationale), each with its own explicit three-way disputed
# question so the seed step has a real contested fact to plant and the new
# premature_resolution metric has something concrete to check.
PREMISES = [
    (
        "tideglass_reach",
        'Tideglass Reach: a coastal city, drowned for two generations, has just '
        'resurfaced after an unexplained "long ebb." The Tideglass Guild and the '
        'Hush Choir are racing to claim it before the other does — and nobody '
        'agrees on whether the bell tone divers keep hearing near the Cathedral '
        'Spire is a hazard, a hoax, or a warning.',
    ),
    (
        "hollow_orbit",
        "Hollow Orbit: a generation ship's population has just voted to wake the "
        "founders from cryo-sleep decades early after picking up a repeating "
        "signal from a supposedly empty sector ahead. The ship's engineering "
        "guild and its elected council are racing to decide what to do before "
        "the founders wake — and nobody agrees on whether the signal is a "
        "beacon from another lost colony ship, a natural phenomenon being "
        "over-read by a nervous crew, or a warning left by whoever destroyed "
        "the last ship that answered a signal like it.",
    ),
    (
        "ashbind_hollow",
        "Ashbind Hollow: a walled farming settlement's grain crop has failed for "
        "the third year running, just as a wandering trade caravan arrives "
        "asking to shelter inside the walls for the winter. The settlement's "
        "elder council and its militia captain are racing to decide before the "
        "first frost — and nobody agrees on whether the failing crop is caused "
        "by blighted soil the elders have been quietly hiding for years, "
        "sabotage by a rival settlement downriver, or bad luck the militia is "
        "using as an excuse to seize more authority.",
    ),
]

# Reduced from the demo's live default of 4 (backend.orchestrator.
# DEFAULT_SCENE_COUNT), same disclosed cost/time tradeoff as the original
# experiment, applied identically across all 3 premises here.
SCENE_COUNT = 2

# Raised from the original experiment's 10 specifically to get much closer
# to real token-budget parity rather than stopping at ~47%. Still a
# hard cap, not unbounded, against runaway cost if a premise's Stratum run
# is unusually token-heavy.
MAX_REFLECTIVE_ROUNDS = 30

OUT_DIR = Path(__file__).resolve().parent.parent / "experiments" / "baseline_fairness_replication"


async def _run_stratum(premise: str) -> Run:
    run = create_run(premise)
    await run_generation(run, scene_count=SCENE_COUNT)
    if run.status != "done":
        raise RuntimeError(f"Stratum run did not complete: status={run.status} error={run.error}")
    return run


def _run_one_premise(slug: str, premise: str) -> dict:
    print(f"\n{'=' * 70}\n{slug}: running Stratum ({SCENE_COUNT} scenes)...\n{'=' * 70}")
    stratum_run = asyncio.run(_run_stratum(premise))
    print(
        f"{slug}: stratum done. total_tokens={stratum_run.total_tokens} "
        f"total_calls={stratum_run.total_calls} baseline_tokens={stratum_run.baseline_tokens}"
    )

    token_budget = stratum_run.total_tokens
    print(f"{slug}: generating reflective baseline, target budget={token_budget} tokens...")
    reflective_run = create_run(premise)
    with track_run(reflective_run):
        reflective_text = generate_reflective_baseline(
            premise, reflective_run, token_budget=token_budget, max_rounds=MAX_REFLECTIVE_ROUNDS
        )
    rounds_used = max(reflective_run.total_calls - 1, 0)
    budget_pct = round(100 * reflective_run.total_tokens / token_budget, 1) if token_budget else 0.0
    print(
        f"{slug}: reflective baseline done. total_tokens={reflective_run.total_tokens} "
        f"({budget_pct}% of target budget) rounds_used={rounds_used}"
    )

    comparison = compute_comparison(
        stratum_run,
        reflective_baseline_text=reflective_text,
        reflective_baseline_tokens=reflective_run.total_tokens,
    )
    comparison["_meta"] = {
        "slug": slug,
        "premise": premise,
        "scene_count": SCENE_COUNT,
        "stratum_total_calls": stratum_run.total_calls,
        "naive_baseline_calls": stratum_run.baseline_calls,
        "reflective_baseline_calls": reflective_run.total_calls,
        "reflective_baseline_rounds_used": rounds_used,
        "reflective_baseline_max_rounds": MAX_REFLECTIVE_ROUNDS,
        "reflective_baseline_budget_pct_achieved": budget_pct,
    }

    canon_entries = [e for e in stratum_run.world_bible.list() if e.status == "canon"]
    stratum_text = "\n\n".join(e.full_text or e.summary for e in canon_entries)

    premise_dir = OUT_DIR / slug
    premise_dir.mkdir(parents=True, exist_ok=True)
    (premise_dir / "stratum_canon.txt").write_text(stratum_text)
    (premise_dir / "naive_baseline.txt").write_text(stratum_run.baseline_text or "")
    (premise_dir / "reflective_baseline.txt").write_text(reflective_text)
    (premise_dir / "comparison.json").write_text(json.dumps(comparison, indent=2))
    print(f"{slug}: saved to {premise_dir}/")
    return comparison


def _aggregate(all_comparisons: list[dict]) -> dict:
    metrics_keys = [k for k in all_comparisons[0] if k != "_meta"]
    aggregate: dict = {}
    for metric in metrics_keys:
        aggregate[metric] = {}
        variants = all_comparisons[0][metric].keys()
        for variant in variants:
            values = [c[metric][variant] for c in all_comparisons if variant in c.get(metric, {})]
            if values:
                aggregate[metric][variant] = round(sum(values) / len(values), 4)
    return aggregate


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_comparisons = []
    for slug, premise in PREMISES:
        # ponytail: resume support — a prior run of this script was killed
        # mid-way (an unrelated backend restart), after tideglass_reach had
        # already finished and paid real DashScope cost for it. Re-running
        # a premise whose comparison.json already exists would silently
        # waste that and risk a second data point diverging from the first
        # for no reason; skip it and reuse the saved result instead.
        existing = OUT_DIR / slug / "comparison.json"
        if existing.exists():
            print(f"{slug}: comparison.json already exists, skipping (resume) — {existing}")
            all_comparisons.append(json.loads(existing.read_text()))
            continue
        comparison = _run_one_premise(slug, premise)
        all_comparisons.append(comparison)
        print(json.dumps(comparison, indent=2))

    aggregate = _aggregate(all_comparisons)
    report = {
        "n_premises": len(PREMISES),
        "premises": [slug for slug, _ in PREMISES],
        "per_premise": all_comparisons,
        "aggregate_mean": aggregate,
    }
    (OUT_DIR / "replication_report.json").write_text(json.dumps(report, indent=2))

    print(f"\n{'=' * 70}\nAGGREGATE ACROSS {len(PREMISES)} PREMISES\n{'=' * 70}")
    print(json.dumps(aggregate, indent=2))
    print(f"\nFull report saved to {OUT_DIR / 'replication_report.json'}")


if __name__ == "__main__":
    main()
