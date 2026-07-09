"""Runs one full generation for a Run: seed, then N scenes in sequence,
with the baseline comparison generated concurrently in the background.

This is a dependency-aware task queue (adapted from DELM): scene N cannot
begin until scene N-1 is admitted, so scenes run sequentially here, each
reading the world bible the previous one just committed to. The baseline
agent has no such dependency — it's a single call against the raw premise
— so it runs concurrently rather than blocking the negotiated pipeline.
"""

from __future__ import annotations

import asyncio

from backend.agents.baseline import generate_baseline
from backend.agents.illustrator import generate_scene_image
from backend.agents.seed import generate_seed
from backend.models_client import track_run
from backend.negotiation import run_scene
from backend.runs import Run
from backend.schemas import DebateEvent

DEFAULT_SCENE_COUNT = 4

# Matches negotiation.run_scene's revision-attempt bound: a few attempts is
# enough to ride out a transient failure without masking a persistently
# broken seed call.
_MAX_SEED_ATTEMPTS = 3


async def _generate_seed_with_retry(premise: str) -> list:
    """Runs generate_seed with the same retry-with-backoff pattern every
    scene after it already gets (see backend.negotiation.run_scene's
    except-block). Unlike every scene, the seed step previously ran once
    with no retry at all, so a single transient failure (e.g. a slow-
    DashScope timeout, observed for other calls in testing) killed the
    entire run before a single scene even started.
    """
    last_error: Exception | None = None
    for attempt_index in range(_MAX_SEED_ATTEMPTS):
        try:
            return await asyncio.to_thread(generate_seed, premise)
        except Exception as exc:  # noqa: BLE001 - same transient-failure rationale as run_scene's retry loop
            last_error = exc
            if attempt_index < _MAX_SEED_ATTEMPTS - 1:
                await asyncio.sleep(min(2**attempt_index, 8))
    raise RuntimeError(f"Seed generation failed after {_MAX_SEED_ATTEMPTS} attempts. Last error: {last_error}")


async def _illustrate_scene(run: Run, entry_id: str, summary: str, round_number: int) -> None:
    """Fire-and-forget image generation for one admitted scene.

    Deliberately not awaited by the main scene loop (see call site) — image
    generation is slow enough that gating scene N+1 on scene N's
    illustration would add real wall-clock time to the negotiation for a
    purely supplementary artifact. Runs concurrently instead, same pattern
    as the baseline comparison task below.
    """
    image_url = await asyncio.to_thread(generate_scene_image, summary)
    if image_url is None:
        return
    entry = run.world_bible.get(entry_id)
    if entry is None:  # defensive: shouldn't happen, entry was just admitted
        return
    run.world_bible.update(entry.model_copy(update={"image_url": image_url}))
    run.emit(
        DebateEvent(
            round=round_number,
            scene=round_number,
            agent=None,
            event_type="image_ready",
            payload={"entry_id": entry_id, "image_url": image_url},
        )
    )


async def run_generation(run: Run, scene_count: int = DEFAULT_SCENE_COUNT) -> None:
    """Drive a Run from "pending" to "done" (or "failed"), emitting
    DebateEvents to run.events as each step happens so a live SSE subscriber
    (backend.main's polling _stream_run) sees the negotiation unfold in
    real time.
    """
    run.status = "running"
    illustration_tasks: list[asyncio.Task] = []
    try:
        # Bind the "baseline" bucket only for this task's creation — asyncio
        # copies the current context into the new task at this exact point,
        # so its chat() calls attribute to run.baseline_tokens/baseline_calls
        # even though everything below runs concurrently under the default
        # "stratum" bucket (see backend.models_client.track_run).
        with track_run(run, bucket="baseline"):
            baseline_task = asyncio.create_task(asyncio.to_thread(generate_baseline, run.premise))

        # Everything from here on is the negotiated pipeline proper, so it
        # attributes to run.total_tokens/total_calls (the default "stratum"
        # bucket) rather than run.baseline_tokens/baseline_calls.
        with track_run(run):
            seed_entries = await _generate_seed_with_retry(run.premise)
            for entry in seed_entries:
                run.world_bible.add(entry)
                run.emit(
                    DebateEvent(
                        round=0,
                        scene=0,
                        agent="SEED",
                        event_type="seed_entry",
                        phase="seed",
                        # Exclude the raw embedding vector — the frontend never
                        # needs it, and it would otherwise dominate every
                        # SSE payload with ~1024 floats of noise.
                        payload=entry.model_dump(mode="json", exclude={"embedding"}),
                    )
                )

            for scene_num in range(1, scene_count + 1):
                # run_scene emits its own granular (proposal/critique/judge_score/
                # synthesis/admission_result) events via this callback; nothing
                # further to do with its return value beyond letting it commit.
                #
                # A scene that can't converge after _MAX_REVISION_ATTEMPTS
                # (backend.negotiation) is a real, honest outcome — the gate
                # correctly refused to admit a contradiction — not a reason to
                # discard every scene already negotiated. Skip it and let later
                # scenes (which read whatever canon exists so far) keep going.
                try:
                    admitted = await run_scene(run.world_bible, scene_num, on_event=run.emit)
                    illustration_tasks.append(
                        asyncio.create_task(_illustrate_scene(run, admitted.id, admitted.summary, scene_num))
                    )
                except RuntimeError as exc:
                    run.emit(
                        DebateEvent(
                            round=scene_num,
                            scene=scene_num,
                            agent="ARBITER",
                            event_type="scene_failed",
                            payload={"reason": str(exc)},
                        )
                    )

        run.baseline_text = await baseline_task
        # Scenes run sequentially and each takes minutes, so by the time the
        # last scene admits, every earlier scene's illustration has almost
        # certainly already finished — this typically only waits on the
        # final scene's image, not stacking up wall-clock time. Without this,
        # asyncio.run() (backend.main._run_generation_sync) would cancel
        # whichever illustration tasks were still pending the moment this
        # coroutine returns.
        if illustration_tasks:
            await asyncio.gather(*illustration_tasks, return_exceptions=True)
        run.emit(
            DebateEvent(
                round=0,
                scene=0,
                agent="BASELINE",
                event_type="baseline_ready",
                phase="baseline",
                payload={"text": run.baseline_text},
            )
        )
        run.status = "done"
    except Exception as exc:  # noqa: BLE001 - surfaced to the run's status/error for the frontend to display
        # Deliberately not re-raised: this runs inside a FastAPI
        # BackgroundTasks callable (backend.main._run_generation_sync), with
        # no caller left to catch it — letting it propagate previously took
        # the entire uvicorn process down with it (observed in testing: an
        # unhandled APITimeoutError from a slow DashScope call here killed
        # the whole server, not just this one run). Setting status/error is
        # the actual contract with the frontend; raising past that serves no
        # purpose and is actively destructive to every other run in flight.
        run.status = "failed"
        run.error = str(exc)
