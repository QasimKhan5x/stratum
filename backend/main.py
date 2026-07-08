"""FastAPI orchestrator app.

Per stratum-architecture-plan.md, this process is intended to be a
persistent server (ECS in production) since SSE requires long-lived
connections that Function Compute is not designed for. For local
development it's run with `uvicorn`.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import sqlite_store
from backend.metrics import compute_comparison
from backend.models_client import embed, list_models
from backend.orchestrator import DEFAULT_SCENE_COUNT, run_generation
from backend.runs import Run, create_run, get_run
from backend.schemas import DebateEvent, WorldBibleEntry
from backend.cloud_storage import try_upload_export
from backend.twee_export import export_twee

app = FastAPI(title="Stratum")

# Open CORS for local dev only — the frontend is plain static files served
# from a different origin/port during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/models")
def api_models() -> dict:
    """Proves DashScope wiring end-to-end: lists models visible to the
    configured DASHSCOPE_API_KEY via models_client."""
    return {"models": list_models()}


class GenerateRequest(BaseModel):
    premise: str
    # Bounded to keep a public POST endpoint from being used to kick off an
    # arbitrarily expensive (real DashScope $$) run — 12 is 3x the default
    # and comfortably covers any real demo scenario without being unbounded.
    scene_count: int = Field(default=DEFAULT_SCENE_COUNT, ge=1, le=12)


@app.post("/api/generate")
def api_generate(request: GenerateRequest, background_tasks: BackgroundTasks) -> dict:
    """Starts a generation run in the background and returns its ID
    immediately — the caller opens /api/stream/{run_id} to watch it unfold.
    """
    run = create_run(request.premise)
    background_tasks.add_task(_run_generation_sync, run, request.scene_count)
    return {"run_id": run.id}


def _run_generation_sync(run: Run, scene_count: int) -> None:
    """BackgroundTasks runs its callable in a worker thread, so run_generation
    (an async function) needs its own event loop here rather than being
    awaited directly."""
    asyncio.run(run_generation(run, scene_count))


def _event_to_sse(event: DebateEvent) -> str:
    return f"event: {event.event_type}\ndata: {event.model_dump_json()}\n\n"


async def _stream_run(
    run: Run,
    pace_seconds: float = 0.0,
    slow_from: int = -1,
    slow_to: int = -1,
    slow_pace_seconds: float = 0.0,
    grace_seconds: float = 0.0,
):
    # Poll run.events by index rather than draining a shared queue — see
    # backend.runs.Run's docstring for why: a queue double-yields every
    # event whenever a subscriber connects after the run already finished
    # unwatched, and splits events non-deterministically across concurrent
    # subscribers. An index into the same always-growing list has neither
    # problem and naturally covers both "replay what already happened" and
    # "keep streaming what happens next" with one code path.
    #
    # pace_seconds exists for demo recording (see stratum-demo-and-
    # verification.md's pre-generate-and-replay fallback): a finished run's
    # events would otherwise all replay near-instantly, since they're
    # already sitting in run.events with nothing left to wait on. A small
    # per-event delay makes a pre-generated run watchable as if unfolding
    # live, without needing separate "live" and "replay" code paths.
    #
    # slow_from/slow_to/slow_pace_seconds let one narrow index range (e.g.
    # the gate-catch) play at a legible speed while the rest of a long run
    # (dozens of judge_score events per scene) moves quickly — recording
    # convenience only, not something the live path ever needs.
    next_index = 0
    grace_deadline = None
    while True:
        # Cheap, always-safe: a no-op indexed SQLite query when this
        # process is the one actually generating the run (nothing new to
        # find), and the mechanism that lets a *different* backend replica
        # stream a run it didn't itself generate (see
        # backend.runs.Run.refresh_events_from_store).
        run.refresh_events_from_store()
        pending = run.events[next_index:]
        for i, event in enumerate(pending, start=next_index):
            yield _event_to_sse(event)
            delay = slow_pace_seconds if slow_from <= i < slow_to else pace_seconds
            if delay:
                await asyncio.sleep(delay)
        next_index += len(pending)

        # grace_seconds keeps an already-"done" run's stream open a bit
        # longer instead of closing the instant history replay finishes —
        # otherwise there's no window to demo a live /api/inject against a
        # pre-generated replay, since the connection would already be gone
        # by the time the injection request lands. Real in-progress runs
        # never need this: their status simply isn't "done" yet.
        run_finished = run.status in ("done", "failed") and next_index >= len(run.events)
        if run_finished:
            if grace_deadline is None:
                grace_deadline = asyncio.get_event_loop().time() + grace_seconds
            if asyncio.get_event_loop().time() >= grace_deadline:
                yield f"event: run_complete\ndata: {json.dumps({'status': run.status, 'error': run.error})}\n\n"
                return
        await asyncio.sleep(0.1)


@app.get("/api/stream/{run_id}")
async def api_stream(
    run_id: str,
    pace: float = 0.0,
    slow_from: int = -1,
    slow_to: int = -1,
    slow_pace: float = 0.0,
    grace: float = 0.0,
) -> StreamingResponse:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id '{run_id}'.")
    return StreamingResponse(
        _stream_run(
            run,
            pace_seconds=pace,
            slow_from=slow_from,
            slow_to=slow_to,
            slow_pace_seconds=slow_pace,
            grace_seconds=grace,
        ),
        media_type="text/event-stream",
    )


@app.get("/api/world/{run_id}")
def api_world(run_id: str) -> dict:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id '{run_id}'.")
    return {
        "status": run.status,
        "error": run.error,
        "entries": [e.model_dump(mode="json", exclude={"embedding"}) for e in run.world_bible.list()],
    }


class InjectRequest(BaseModel):
    text: str


@app.post("/api/inject/{run_id}")
def api_inject(run_id: str, request: InjectRequest) -> dict:
    """Admits a human-submitted world constraint directly into the world
    bible without pausing generation, per stratum-project-overview.md — the
    next round's specialists will see it in CURRENT CANON immediately since
    world_bible.canon_context() is re-read at the start of every step.
    """
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id '{run_id}'.")

    entry = WorldBibleEntry(
        id=f"human-{uuid.uuid4().hex[:6]}",
        summary=request.text[:200],
        full_text=request.text,
        status="canon",
        provenance_agent="HUMAN",
        provenance_round=0,
        embedding=embed(request.text),
        tags=["human-injection"],
    )
    run.world_bible.add(entry)
    run.emit(
        DebateEvent(
            round=0,
            scene=0,
            agent="HUMAN",
            event_type="human_injection",
            payload=entry.model_dump(mode="json", exclude={"embedding"}),
        )
    )
    return {"entry_id": entry.id}


@app.get("/api/export/{run_id}")
def api_export(run_id: str) -> PlainTextResponse:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id '{run_id}'.")
    try:
        twee_text = export_twee(run.world_bible, title=run.premise[:60])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{run_id}.twee"'}
    oss_url = try_upload_export(run_id, twee_text)
    if oss_url:
        headers["X-OSS-Url"] = oss_url
    return PlainTextResponse(content=twee_text, media_type="text/plain", headers=headers)


@app.get("/api/metrics/{run_id}")
def api_metrics(run_id: str) -> dict:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id '{run_id}'.")
    if run.status != "done":
        raise HTTPException(status_code=409, detail=f"Run status is '{run.status}', not 'done' yet.")
    return compute_comparison(run)


class ImportRunRequest(BaseModel):
    premise: str
    events: list[DebateEvent]
    world_bible_entries: list[WorldBibleEntry]
    baseline_text: str | None = None
    status: str = "done"


@app.post("/api/runs/import")
def api_import_run(request: ImportRunRequest) -> dict:
    """Re-register a previously exported run (see scripts/save_demo_run.py)
    for replay via /api/stream — reconstructs the in-memory Run this
    server's registry would have held live, from exactly what a real run
    emitted.

    Exists for runs that were never registered with this server's in-memory
    `backend.runs._RUNS` cache at all (e.g. a run generated by a one-off
    script, or a demo recording captured on a different machine) — SQLite/
    Tablestore already make a *previously-run* run's data durable across a
    restart (see backend/runs.py, backend/sqlite_store.py), but this endpoint
    is what lets data that was never a live run on this server in the first
    place become displayable through the normal UI. This is what makes
    stratum-demo-and-verification.md's "pre-generate and replay" fallback
    actually usable, not just within a single server session.
    """
    run = create_run(request.premise)
    for entry in request.world_bible_entries:
        run.world_bible.add(entry)
    # Persist through sqlite_store directly (bulk-loading a whole exported
    # run's events at once, not one at a time) rather than calling emit()
    # per event and paying its per-call save_run_meta() write N times —
    # then a single explicit meta save once, matching what emit() would do.
    for seq, event in enumerate(request.events):
        sqlite_store.append_event(run.id, seq, event)
    run.events = list(request.events)
    run.baseline_text = request.baseline_text
    run.status = request.status  # type: ignore[assignment]
    sqlite_store.save_run_meta(run)
    return {"run_id": run.id}


# Serve the plain HTML/JS/CSS frontend as static files. Mounted last so it
# doesn't shadow the /api/* and /health routes above.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
