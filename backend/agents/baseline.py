"""The baseline agent: single-agent comparison, no debate loop.

The baseline deliberately gets no seed step and no world-bible structure —
a single sequential "arbiter"-role (qwen3.7-max) call with the same
premise, no scaffolding — to isolate the effect of structured, negotiated
generation for the efficiency-gain comparison.
"""

from __future__ import annotations

from backend.agents.prompts import BASELINE_PROMPT
from backend.models_client import chat


def generate_baseline(premise: str) -> str:
    """Generate a world from the same premise with no debate loop.

    A single sequential qwen3.7-max call, no seed step, no world-bible
    structure, no admission gate — the leanest fair comparison against
    Stratum's negotiated generation, used to measure contradiction rate,
    creative-divergence score, and provenance depth deltas.

    Args:
        premise: the same user-submitted world premise given to the
            negotiated pipeline.

    Returns:
        Raw generated text (flat, unstructured — no world-bible entries).
    """
    user_message = (
        f"WORLD PREMISE:\n{premise}\n\n"
        "Write the opening of this interactive fiction world in a single "
        "continuous pass: the setting, its central tension, and at least "
        "3-5 connected scenes."
    )
    # Deliberately thinking=False (default) and the "arbiter" model role
    # with no extra reasoning boost — the comparison needs to isolate the
    # effect of structured negotiation itself, not give the baseline a
    # quality advantage the real pipeline doesn't also get.
    return chat(
        role="arbiter",
        messages=[
            {"role": "system", "content": BASELINE_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
