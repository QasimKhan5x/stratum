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

    def emit(event_type: str, agent: str | None, payload: dict, *, attempt: int = 1) -> None:
        if on_event is not None:
            on_event(
                DebateEvent(
                    round=round_number,
                    scene=round_number,
                    agent=agent,
                    event_type=event_type,  # type: ignore[arg-type]
                    payload=payload,
                    attempt=attempt,
                )
            )

    revision_target: dict | None = None
    last_error: Exception | None = None

    for attempt_index in range(_MAX_REVISION_ATTEMPTS):
        # 1-indexed for anything user/log-facing — "attempt 1" reads better
        # than "attempt 0" and matches _MAX_REVISION_ATTEMPTS's own framing.
        attempt = attempt_index + 1
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
                emit("proposal", proposal.get("role"), proposal, attempt=attempt)

            # --- Step 2: antithesis — structured cross-critiques. Every
            # specialist critiques whichever proposal is next in
            # _SPECIALIST_ROLES order (a fixed round-robin: role i critiques
            # proposal i+1, wrapping around) — the same mechanism for all
            # four roles, not just a Lorekeeper<->Provocateur pairing.
            #
            # ponytail: this round-robin is a structurally-valid pairing
            # (every proposal gets exactly one critique) but not a targeted
            # one — it doesn't know or care which proposal is actually most
            # tonally divergent or spatially weak, so Harmonist/Architect
            # can end up critiquing an already-safe proposal purely by list
            # position. The ceiling is "arbitrary but valid pairing," not
            # "no critique happens." Upgrade path: route Harmonist to
            # whichever proposal's embedding is furthest from the tonal-
            # consistency canon entries, and Architect to whichever
            # grid_position is most isolated/colliding with existing
            # entries — both signals (embeddings, grid positions) already
            # exist on each proposal/entry, so this is an aggregation
            # change here, not new data collection.
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
                emit("critique", critique.get("critic_role"), critique, attempt=attempt)

            # --- Step 3: judging — four dimension-specific judges each score
            # every proposal in one batched call (16 calls -> 4 per attempt;
            # see judges.score_all's docstring), run in parallel across dimensions.
            judge_score_batches = await asyncio.gather(
                *(
                    asyncio.to_thread(judges.score_all, dimension, proposals, world_bible)
                    for dimension in _JUDGE_DIMENSIONS
                )
            )
            # Collapse the 4 batched calls' worth of scores (4 dimensions x 4
            # proposals = 16 individual scores) into a single stream event.
            # This is a legibility fix at the emission source, not a
            # frontend patch: real per-call cardinality is 4 (one batched
            # call per dimension), so 16 discrete top-level events was never
            # a deliberate signal, just an artifact of flattening the list
            # before emitting. No score data is dropped — all 16 still
            # travel in the payload, just grouped.
            judge_scores = [score for batch in judge_score_batches for score in batch]
            emit("judge_score", None, {"scores": judge_scores}, attempt=attempt)

            # --- Step 4: synthesis — the Arbiter rules, informed by the
            # judge panel, producing one final candidate scene plus the
            # favored/overruled reasoning that streams live to the debate
            # panel via the "synthesis" DebateEvent emitted below (SSE
            # carries the full event, synthesis_meta included).
            candidate, synthesis_meta = await asyncio.to_thread(
                arbiter.synthesize, proposals, critiques, judge_scores, world_bible, revision_note
            )
            # arbiter.synthesize doesn't know which round it's running in;
            # finalize that here rather than threading round_number through
            # every agent-logic call.
            candidate = candidate.model_copy(update={"provenance_round": round_number})
            # `summary` is included here (not just `entry_id`) so a rejected
            # candidate's content survives in the event stream even though
            # it never joins the world bible — without this, a rejected
            # synthesis was only ever recoverable as an opaque id hash.
            emit(
                "synthesis",
                "ARBITER",
                {"entry_id": candidate.id, "summary": candidate.summary, **synthesis_meta},
                attempt=attempt,
            )

            # --- Step 5: verified admission — check the candidate against
            # existing canon before committing it.
            admission_result = await asyncio.to_thread(check_admission, candidate, world_bible)
            emit(
                "admission_result",
                None,
                {"entry_id": candidate.id, **admission_result},
                attempt=attempt,
            )
        except Exception as exc:  # noqa: BLE001 - a transient failure anywhere
            # in this attempt (most commonly a slow-DashScope APITimeoutError,
            # observed in testing) shouldn't burn the whole scene — retry the
            # attempt like an admission rejection, keeping revision_target
            # (if any) from a prior attempt rather than discarding it.
            last_error = exc
            # Short exponential backoff before retrying: an immediate retry
            # defeats the point of retrying a 429/rate-limit error, which is
            # the most likely real cause of a transient failure here. Capped
            # at _MAX_REVISION_ATTEMPTS - 1 backoffs total (small either way),
            # so this never meaningfully delays the happy path.
            await asyncio.sleep(min(2**attempt_index, 8))
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
