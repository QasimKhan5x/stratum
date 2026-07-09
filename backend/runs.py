"""Generation-run registry, backed by SQLite for durability + cross-process
sharing (see backend/sqlite_store.py), with an in-memory dict as a hot-path
cache for the common single-process case.

A "run" bundles one WorldBible and its full event log (for replay and
provenance — see backend/schemas.py's DebateEvent for the shape each
event takes).
backend.main's SSE endpoint polls `events` directly by index rather than
draining a queue — a shared asyncio.Queue was tried first, but it
double-yields every event whenever a subscriber connects after the run
already finished with nobody watching live (the queue still holds every
event, never drained, on top of the full history replay), and would also
split events non-deterministically across two concurrent subscribers.
Polling a list by index has neither problem — and now that list can also be
refreshed from SQLite (see Run.refresh_events_from_store), the same polling
loop works whether this process generated the run or a sibling replica did.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from backend import sqlite_store
from backend.cloud_storage import make_world_bible
from backend.schemas import DebateEvent
from backend.world_bible import WorldBible

RunStatus = Literal["pending", "running", "done", "failed"]

sqlite_store.init_db()


@dataclass
class Run:
    id: str
    premise: str
    world_bible: WorldBible = field(default_factory=WorldBible)  # replaced with a Tablestore- or SQLite-backed store in create_run()
    events: list[DebateEvent] = field(default_factory=list)
    status: RunStatus = "pending"
    baseline_text: str | None = None
    error: str | None = None
    # Running token/call totals, incremented by backend.models_client as
    # chat()/chat_json() calls happen (see models_client.track_run) — kept
    # as separate stratum/baseline buckets since that split is exactly what
    # metrics.compute_comparison's efficiency-tradeoff figure needs.
    total_tokens: int = 0
    total_calls: int = 0
    baseline_tokens: int = 0
    baseline_calls: int = 0
    # True only for a Run this process itself created (see create_run) and
    # is actively calling emit() on directly — i.e. self.events is already
    # authoritative and up to date with no help needed. False for a Run
    # reconstructed by sqlite_store.load_run (this process didn't generate
    # it: a restart, or a replica serving a run some sibling is generating),
    # where refresh_events_from_store must keep polling SQLite to see new
    # events at all. See refresh_events_from_store's docstring.
    generated_here: bool = True

    def emit(self, event: DebateEvent) -> None:
        self.events.append(event)
        # Write-through: persisted before returning so a reader in another
        # process (or this one, after a restart) never sees a gap. Meta is
        # re-saved on every event rather than hooked to each individual
        # `run.status = ...`/`run.baseline_text = ...` assignment elsewhere
        # (backend.orchestrator sets those as plain attributes) — simpler,
        # and "at most one event's latency stale" is a non-issue at this
        # project's real event cadence (seconds between events, not µs).
        sqlite_store.append_event(self.id, len(self.events) - 1, event)
        sqlite_store.save_run_meta(self)

    def refresh_events_from_store(self) -> None:
        """Pulls any events this process hasn't seen yet from SQLite — the
        mechanism that lets /api/stream serve a run live even when a
        *different* backend process/replica is the one actually generating
        it (see backend/sqlite_store.py's module docstring). Skipped
        entirely when this process is the one generating the run
        (generated_here=True): self.events is already authoritative via
        emit(), so the SQLite round-trip would just be a guaranteed-empty
        query repeated every 100ms per open stream — real (if individually
        cheap) blocking I/O on the event loop for zero benefit."""
        if self.generated_here:
            return
        new_events = sqlite_store.load_events_from(self.id, len(self.events))
        if new_events:
            self.events.extend(new_events)
            fresh = sqlite_store.load_run(self.id)
            if fresh is not None:
                self.status = fresh.status
                self.baseline_text = fresh.baseline_text
                self.error = fresh.error


_RUNS: dict[str, Run] = {}


def create_run(premise: str) -> Run:
    run_id = uuid.uuid4().hex[:12]
    run = Run(id=run_id, premise=premise, world_bible=make_world_bible(run_id))
    sqlite_store.save_run_meta(run)
    _RUNS[run.id] = run
    return run


def get_run(run_id: str) -> Run | None:
    """Checks the in-memory cache first (the fast path for a run this
    process is actively generating), falling back to SQLite on a miss —
    either this process restarted, or a sibling replica generated this run.
    """
    cached = _RUNS.get(run_id)
    if cached is not None:
        return cached
    loaded = sqlite_store.load_run(run_id)
    if loaded is not None:
        _RUNS[run_id] = loaded
    return loaded
