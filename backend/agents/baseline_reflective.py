"""The reflective baseline: a single agent given an equivalent compute
budget to the negotiated pipeline, spent on self-critique and revision
instead of multi-agent debate.

This exists to answer a specific fairness question the original baseline
(backend/agents/baseline.py) cannot: is Stratum's efficiency-gain claim a
categorical capability of structured multi-agent negotiation, or just an
artifact of spending ~13x more compute than a single call? See
stratum-baseline-fairness-experiment.md for the experiment this supports.

Deliberately does NOT touch backend/negotiation.py or any specialist/judge/
arbiter machinery — this is one agent talking to itself in a loop, not a
disguised second multi-agent system. Same "arbiter" role (qwen3.7-max),
same BASELINE_PROMPT, same premise, and the identical initial call as
generate_baseline — the only difference is what happens after the first
draft.

This is a one-off research variant, not part of any live run. Nothing in
backend/orchestrator.py imports or calls this module.
"""

from __future__ import annotations

from backend.agents.baseline import generate_baseline
from backend.agents.prompts import REFLECTIVE_REVISION_PROMPT
from backend.models_client import chat
from backend.runs import Run

_REVISION_MARKER = "REVISED DRAFT:"


def _initial_draft(premise: str) -> str:
    # Delegates to generate_baseline's identical call (backend/agents/
    # baseline.py) — the only fair way to isolate "what does self-review
    # add" is to start both baselines from the exact same first draft.
    return generate_baseline(premise)


def _revise_once(premise: str, draft: str) -> str:
    user_message = (
        f"WORLD PREMISE:\n{premise}\n\n"
        f"YOUR CURRENT DRAFT:\n{draft}\n\n"
        "Critique your own draft, then produce the complete revised draft, "
        f"in exactly the format given.\n\n{_REVISION_MARKER} must be "
        "followed by the full revised text, not a diff or a summary of "
        "changes."
    )
    # thinking=True: extra reasoning compute per call, the same lever the
    # real pipeline's seed/arbiter steps use — a fair single-agent way to
    # spend more compute per round, not just more rounds.
    response = chat(
        role="arbiter",
        messages=[
            {"role": "system", "content": REFLECTIVE_REVISION_PROMPT},
            {"role": "user", "content": user_message},
        ],
        thinking=True,
    )
    marker_index = response.upper().find(_REVISION_MARKER)
    if marker_index == -1:
        # Defensive: if the model ignores the format, keep the whole
        # response as the new draft rather than discarding the round.
        return response.strip()
    return response[marker_index + len(_REVISION_MARKER) :].strip()


def generate_reflective_baseline(
    premise: str,
    run: Run,
    token_budget: int,
    max_rounds: int = 10,
) -> str:
    """Generate a single-agent world from `premise`, self-reviewed until
    its tracked token spend reaches `token_budget` (or `max_rounds` fires
    first, as a runaway-cost safety cap).

    Args:
        premise: the same world premise given to generate_baseline and to
            the negotiated pipeline.
        run: a backend.runs.Run used purely as a token/call counter — the
            caller must wrap this call in
            `backend.models_client.track_run(run)` so every chat() call
            inside actually increments run.total_tokens. This can be any
            Run, including a scratch one created just for this experiment;
            it does not need to be the "real" Stratum run being compared
            against.
        token_budget: stop revising once run.total_tokens reaches this —
            in practice, the real Stratum run's own total_tokens for the
            same premise, so the two variants get a comparable compute
            budget (see scripts/reflective_baseline_experiment.py).
        max_rounds: hard cap on self-critique/revise rounds regardless of
            token_budget, so a miscalibrated or huge budget can't spiral
            into unbounded API spend.

    Returns:
        The final revised draft (flat, unstructured prose — no world-bible
        entries, same shape as generate_baseline's output).
    """
    draft = _initial_draft(premise)
    for _ in range(max_rounds):
        if run.total_tokens >= token_budget:
            break
        draft = _revise_once(premise, draft)
    return draft
