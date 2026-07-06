"""The negotiation engine's per-scene control flow.

See stratum-architecture-plan.md's "Data flow, end to end" (steps 2-5) and
stratum-demo-and-verification.md's state-machine-check description for the
lifecycle this implements: thesis -> antithesis -> judging -> synthesis ->
admission-check -> (targeted re-negotiation on rejection).
"""

from __future__ import annotations

import asyncio
from typing import Callable

from backend.agents import arbiter, judges, specialists
from backend.admission_gate import check_admission
from backend.schemas import AgentRole, DebateEvent, WorldBibleEntry
from backend.world_bible import WorldBible

EventSink = Callable[[DebateEvent], None]

_SPECIALIST_ROLES = [
    AgentRole.LOREKEEPER,
    AgentRole.PROVOCATEUR,
    AgentRole.HARMONIST,
    AgentRole.ARCHITECT,
]
_JUDGE_DIMENSIONS = ["coherence", "playability", "surprise", "tone"]

# Bound on rejection -> targeted re-negotiation cycles before giving up on
# this scene for the round, so a persistently-contradictory synthesis can't
# stall the pipeline forever.
_MAX_REVISION_ATTEMPTS = 3


async def run_scene(
    world_bible: WorldBible,
    round_number: int,
    on_event: EventSink | None = None,
) -> WorldBibleEntry:
    """Run one full scene negotiation: thesis through verified admission.

    Args:
        world_bible: the current canon. Read at the start of every step
            that needs it; NOT mutated until the final entry is admitted.
        round_number: which round this scene belongs to (for provenance
            and DebateEvent logging).
        on_event: optional callback invoked with a DebateEvent after each
            step, so a live caller (backend.orchestrator, SSE) can stream
            the negotiation as it happens. Not required for correctness —
            omitting it just means the caller only gets the final entry.

    Returns:
        The WorldBibleEntry that was ultimately admitted for this scene.
    """

    def emit(event_type: str, agent: str | None, payload: dict) -> None:
        if on_event is not None:
            on_event(
                DebateEvent(
                    round=round_number,
                    scene=round_number,
                    agent=agent,
                    event_type=event_type,  # type: ignore[arg-type]
                    payload=payload,
                )
            )

    revision_target: dict | None = None
    last_error: Exception | None = None

    for attempt in range(_MAX_REVISION_ATTEMPTS):
        revision_note = revision_target.get("reason") if revision_target else None

        try:
            # --- Step 1: thesis — all four specialists propose in parallel,
            # each reading current canon first. `specialists.propose` is
            # synchronous (a blocking network call), so run all four
            # concurrently via worker threads rather than serially.
            proposals = await asyncio.gather(
                *(
                    asyncio.to_thread(specialists.propose, role, world_bible, revision_note)
                    for role in _SPECIALIST_ROLES
                )
            )
            for proposal in proposals:
                emit("proposal", proposal.get("role"), proposal)

            # --- Step 2: antithesis — structured cross-critiques. Fixed
            # pairing (Lorekeeper <-> Provocateur) plus dynamic routing
            # (Harmonist, Architect) is an agent-logic decision; here every
            # specialist critiques the specialist "opposite" it in the list
            # as a structurally-valid placeholder pairing.
            critiques = await asyncio.gather(
                *(
                    asyncio.to_thread(
                        specialists.critique,
                        role,
                        proposals[(i + 1) % len(proposals)],
                        world_bible,
                    )
                    for i, role in enumerate(_SPECIALIST_ROLES)
                )
            )
            for critique in critiques:
                emit("critique", critique.get("critic_role"), critique)

            # --- Step 3: judging — four dimension-specific judges each score
            # every proposal in one batched call (16 calls -> 4 per attempt;
            # see judges.score_all's docstring), run in parallel across dimensions.
            judge_score_batches = await asyncio.gather(
                *(
                    asyncio.to_thread(judges.score_all, dimension, proposals, world_bible)
                    for dimension in _JUDGE_DIMENSIONS
                )
            )
            judge_scores = [score for batch in judge_score_batches for score in batch]
            for judge_score in judge_scores:
                emit("judge_score", None, judge_score)

            # --- Step 4: synthesis — the Arbiter rules, informed by the
            # judge panel, producing one final candidate scene plus the
            # favored/overruled reasoning that streams to the debate panel
            # (not yet wired to SSE — see backend/main.py's /api/stream TODO
            # — but captured here so that wiring is a pure plumbing change
            # later).
            candidate, synthesis_meta = await asyncio.to_thread(
                arbiter.synthesize, proposals, critiques, judge_scores, world_bible, revision_note
            )
            # arbiter.synthesize doesn't know which round it's running in;
            # finalize that here rather than threading round_number through
            # every agent-logic call.
            candidate = candidate.model_copy(update={"provenance_round": round_number})
            emit("synthesis", "ARBITER", {"entry_id": candidate.id, **synthesis_meta})

            # --- Step 5: verified admission — check the candidate against
            # existing canon before committing it.
            admission_result = await asyncio.to_thread(check_admission, candidate, world_bible)
            emit("admission_result", None, {"entry_id": candidate.id, **admission_result})
        except Exception as exc:  # noqa: BLE001 - a transient failure anywhere
            # in this attempt (most commonly a slow-DashScope APITimeoutError,
            # observed in testing) shouldn't burn the whole scene — retry the
            # attempt like an admission rejection, keeping revision_target
            # (if any) from a prior attempt rather than discarding it.
            last_error = exc
            continue

        if admission_result.get("admitted"):
            # The Arbiter always synthesizes as "contested" (see
            # arbiter.synthesize's docstring); admission is what confirms
            # canon status.
            candidate = candidate.model_copy(update={"status": "canon"})
            world_bible.add(candidate)
            return candidate

        # --- Rejection path: targeted re-negotiation of only the
        # conflicting field, not a full restart. The next loop iteration
        # re-runs thesis/antithesis/judging/synthesis with the conflict
        # surfaced, rather than discarding everything already argued.
        revision_target = admission_result

    raise RuntimeError(
        f"Scene for round {round_number} failed admission after "
        f"{_MAX_REVISION_ATTEMPTS} revision attempts. Last conflict: {revision_target}. "
        f"Last transient error (if any): {last_error}"
    )
