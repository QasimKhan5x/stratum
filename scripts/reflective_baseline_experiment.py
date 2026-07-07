#!/usr/bin/env python3
"""Reflective-baseline fairness experiment.

Runs the real negotiated pipeline once against Stratum's locked demo
premise ("Tideglass Reach", see stratum-demo-premise.md), reads its real
total_tokens to calibrate an equal-compute-budget reflective baseline (see
backend/agents/baseline_reflective.py), then computes all three variants —
stratum / naive baseline / reflective baseline — via
backend.metrics.compute_comparison, and saves the raw text plus a JSON
report. See stratum-baseline-fairness-experiment.md for the writeup this
produced.

Deliberately standalone: does not modify or wrap
backend.orchestrator.run_generation's behavior, does not run on every live
user-facing run, and costs real DashScope API calls — this is a one-off
research validation, not a demo feature.

Usage:
    .venv/bin/python scripts/reflective_baseline_experiment.py
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

# Copied verbatim from stratum-demo-premise.md's locked "one-paragraph
# premise" field, so this experiment runs against the exact demo premise.
PREMISE = (
    'Tideglass Reach: a coastal city, drowned for two generations, has just '
    'resurfaced after an unexplained "long ebb." The Tideglass Guild and the '
    'Hush Choir are racing to claim it before the other does — and nobody '
    'agrees on whether the bell tone divers keep hearing near the Cathedral '
    'Spire is a hazard, a hoax, or a warning.'
)

# Reduced from the demo's live default of 4 (backend.orchestrator.
# DEFAULT_SCENE_COUNT) purely to bound real API spend/wall-clock time for
# this one-off research run. Disclosed in the writeup, not hidden — see
# stratum-baseline-fairness-experiment.md's methodology section.
SCENE_COUNT = 2
MAX_REFLECTIVE_ROUNDS = 10

OUT_DIR = Path(__file__).resolve().parent.parent / "experiments" / "reflective_baseline_experiment"


async def _run_stratum(premise: str) -> Run:
    run = create_run(premise)
    await run_generation(run, scene_count=SCENE_COUNT)
    if run.status != "done":
        raise RuntimeError(f"Stratum run did not complete: status={run.status} error={run.error}")
    return run


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Running the real negotiated pipeline ({SCENE_COUNT} scenes) against the demo premise...")
    stratum_run = asyncio.run(_run_stratum(PREMISE))
    print(
        f"stratum done: total_tokens={stratum_run.total_tokens} total_calls={stratum_run.total_calls} "
        f"baseline_tokens={stratum_run.baseline_tokens} baseline_calls={stratum_run.baseline_calls}"
    )

    token_budget = stratum_run.total_tokens
    print(f"Generating reflective baseline, calibrated to a {token_budget}-token budget...")
    reflective_run = create_run(PREMISE)
    with track_run(reflective_run):
        reflective_text = generate_reflective_baseline(
            PREMISE, reflective_run, token_budget=token_budget, max_rounds=MAX_REFLECTIVE_ROUNDS
        )
    rounds_used = max(reflective_run.total_calls - 1, 0)
    print(
        f"reflective baseline done: total_tokens={reflective_run.total_tokens} "
        f"total_calls={reflective_run.total_calls} (rounds_used={rounds_used})"
    )

    comparison = compute_comparison(
        stratum_run,
        reflective_baseline_text=reflective_text,
        reflective_baseline_tokens=reflective_run.total_tokens,
    )
    comparison["_meta"] = {
        "premise": PREMISE,
        "scene_count": SCENE_COUNT,
        "stratum_total_calls": stratum_run.total_calls,
        "naive_baseline_calls": stratum_run.baseline_calls,
        "reflective_baseline_calls": reflective_run.total_calls,
        "reflective_baseline_rounds_used": rounds_used,
        "reflective_baseline_max_rounds": MAX_REFLECTIVE_ROUNDS,
    }

    canon_entries = [e for e in stratum_run.world_bible.list() if e.status == "canon"]
    stratum_text = "\n\n".join(e.full_text or e.summary for e in canon_entries)

    (OUT_DIR / "stratum_canon.txt").write_text(stratum_text)
    (OUT_DIR / "naive_baseline.txt").write_text(stratum_run.baseline_text or "")
    (OUT_DIR / "reflective_baseline.txt").write_text(reflective_text)
    (OUT_DIR / "comparison.json").write_text(json.dumps(comparison, indent=2))

    print(json.dumps(comparison, indent=2))
    print(f"\nSaved raw output + comparison.json to {OUT_DIR}/")


if __name__ == "__main__":
    main()
