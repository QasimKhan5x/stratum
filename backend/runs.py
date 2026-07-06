"""In-memory generation-run registry.

ponytail: like world_bible.py, this is a temporary in-memory stand-in for
what would be Tablestore-backed run state in production — runs vanish on
server restart. A "run" bundles one WorldBible, its full event log (for
replay/provenance per stratum-architecture-plan.md's "debate event" data
shape), and a live asyncio.Queue that backend.negotiation and
backend.orchestrator push DebateEvents into as they happen, which
backend.main's SSE endpoint drains.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Literal

from backend.schemas import DebateEvent
from backend.world_bible import WorldBible

RunStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class Run:
    id: str
    premise: str
    world_bible: WorldBible = field(default_factory=WorldBible)
    events: list[DebateEvent] = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
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

    def emit(self, event: DebateEvent) -> None:
        self.events.append(event)
        self.queue.put_nowait(event)


_RUNS: dict[str, Run] = {}


def create_run(premise: str) -> Run:
    run = Run(id=uuid.uuid4().hex[:12], premise=premise)
    _RUNS[run.id] = run
    return run


def get_run(run_id: str) -> Run | None:
    return _RUNS.get(run_id)
