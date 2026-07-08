"""Vendor-neutral, self-hostable persistence: a SQLite-backed Run + WorldBible.

This is the default persistence tier for anyone who clones this repo without
an Alibaba Cloud account — `backend.cloud_storage.TablestoreWorldBible` stays
the tier used for the actual hackathon submission's cloud-deployment proof,
but it only works with real Alibaba Cloud credentials. Without this module,
forking the repo without those credentials meant every run lived only in one
process's memory (`backend.runs._RUNS`) and vanished on restart — a real
blocker for "clone it and self-host it" (see
stratum-critical-review-checklist.md's OSS-productization discussion).

Uses Python's stdlib `sqlite3` — zero new dependencies, works out of the box.
One file (`STRATUM_DB_PATH`, default `./stratum.db`) holds three tables:
`runs` (one row per Run's metadata), `events` (append-only, ordered by a
per-run sequence number), and `world_bible_entries` (mirrors
cloud_storage.TablestoreWorldBible's shape exactly, so both backends satisfy
the same WorldBible interface).

Why this is also the scalability story, not just an OSS one: the same
durable store is what lets more than one backend process serve the same
runs — `backend.runs.get_run()` falls back to loading from here on an
in-memory cache miss, so a second (or hundredth) stateless backend replica
behind a load balancer can serve `/api/world`, `/api/export`, `/api/metrics`,
and even a live `/api/stream` for a run some *other* replica is actively
generating (see `Run.refresh_events_from_store`, called from
backend.main._stream_run's poll loop). No pub/sub system, no message bus —
just an indexed SQLite query every 100ms per active stream connection for
that cross-replica case (skipped entirely when this process is the one
generating the run — see `Run.generated_here`).

ponytail: SQLite in WAL mode supports concurrent readers plus one active
writer per file, which is genuinely enough for this project's real scale
(a handful of concurrent negotiations, not thousands of writes/second). It
is NOT a distributed database — the ceiling is "all replicas share one disk
(or one NFS/EBS-like mount)," not true multi-region write scaling. The
upgrade path if that ceiling is ever actually hit is swapping this for
Postgres or Tablestore, which is a drop-in swap: both already implement the
exact same WorldBible interface (add/get/list/update/canon_context), and
Run's persistence hooks here are the only two places (`_persist_event`,
`load_run`) that would need a new backend.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from backend.schemas import DebateEvent, WorldBibleEntry
from backend.world_bible import WorldBible

_DB_PATH = os.environ.get("STRATUM_DB_PATH", str(Path(__file__).resolve().parent.parent / "stratum.db"))

# One lock guarding all writes: sqlite3 connections aren't safe to share
# across threads, and FastAPI's BackgroundTasks/asyncio.to_thread calls into
# this module from whichever worker thread happens to be running — a fresh
# short-lived connection per call (like backend.mcp_world_bible_client's
# "one subprocess per call" tradeoff) is simpler and safe at this project's
# real concurrency level than a shared pooled connection would be.
_write_lock = threading.Lock()


@contextmanager
def _connect():
    conn = sqlite3.connect(_DB_PATH, timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Creates all tables if missing. Safe to call on every process start."""
    with _write_lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                premise TEXT NOT NULL,
                status TEXT NOT NULL,
                baseline_text TEXT,
                error TEXT,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                total_calls INTEGER NOT NULL DEFAULT 0,
                baseline_tokens INTEGER NOT NULL DEFAULT 0,
                baseline_calls INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (run_id, seq)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS world_bible_entries (
                run_id TEXT NOT NULL,
                entry_id TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (run_id, entry_id)
            )
            """
        )


def save_run_meta(run) -> None:
    """Upserts a Run's scalar metadata (status, baseline_text, token/call
    counters, error). Called from Run.emit() so it stays fresh within one
    event's latency without needing to hook every individual attribute
    assignment elsewhere in the codebase (orchestrator.py sets
    run.status/run.baseline_text/etc. as plain attribute writes)."""
    with _write_lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO runs (run_id, premise, status, baseline_text, error,
                               total_tokens, total_calls, baseline_tokens, baseline_calls)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status=excluded.status,
                baseline_text=excluded.baseline_text,
                error=excluded.error,
                total_tokens=excluded.total_tokens,
                total_calls=excluded.total_calls,
                baseline_tokens=excluded.baseline_tokens,
                baseline_calls=excluded.baseline_calls
            """,
            (
                run.id,
                run.premise,
                run.status,
                run.baseline_text,
                run.error,
                run.total_tokens,
                run.total_calls,
                run.baseline_tokens,
                run.baseline_calls,
            ),
        )


def append_event(run_id: str, seq: int, event: DebateEvent) -> None:
    with _write_lock, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO events (run_id, seq, data) VALUES (?, ?, ?)",
            (run_id, seq, event.model_dump_json()),
        )


def load_events_from(run_id: str, start_seq: int) -> list[DebateEvent]:
    """Returns events for `run_id` with seq >= start_seq, in order — the
    query backend.main._stream_run polls on every tick so a run being
    generated by a *different* process still streams live here."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT data FROM events WHERE run_id = ? AND seq >= ? ORDER BY seq",
            (run_id, start_seq),
        ).fetchall()
    return [DebateEvent.model_validate_json(row[0]) for row in rows]


def load_run(run_id: str):
    """Reconstructs a full Run from SQLite, or None if it doesn't exist —
    the cache-miss path for backend.runs.get_run() (e.g. after a restart,
    or on a replica that didn't itself generate this run)."""
    from backend.runs import Run  # local import: backend.runs imports this module

    with _connect() as conn:
        row = conn.execute(
            "SELECT premise, status, baseline_text, error, total_tokens, total_calls, "
            "baseline_tokens, baseline_calls FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        event_rows = conn.execute(
            "SELECT data FROM events WHERE run_id = ? ORDER BY seq", (run_id,)
        ).fetchall()

    premise, status, baseline_text, error, total_tokens, total_calls, baseline_tokens, baseline_calls = row
    run = Run(
        id=run_id,
        premise=premise,
        world_bible=SQLiteWorldBible(run_id),
        status=status,
        baseline_text=baseline_text,
        error=error,
        total_tokens=total_tokens,
        total_calls=total_calls,
        baseline_tokens=baseline_tokens,
        baseline_calls=baseline_calls,
        # Reconstructed from storage, not the process actively generating
        # it — see Run.generated_here.
        generated_here=False,
    )
    run.events = [DebateEvent.model_validate_json(r[0]) for r in event_rows]
    return run


class SQLiteWorldBible(WorldBible):
    """Same interface as `WorldBible` (add/get/list/update/canon_context),
    backed by SQLite instead of a bare dict — the default self-hostable
    persistence tier. Mirrors backend.cloud_storage.TablestoreWorldBible's
    shape closely on purpose: both are drop-in implementations of the same
    contract, so swapping between "no cloud account" and "real Alibaba
    Cloud deployment" is a config choice, not a code change.
    """

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id
        self._load_from_sqlite()

    def _load_from_sqlite(self) -> None:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT data FROM world_bible_entries WHERE run_id = ?", (self._run_id,)
            ).fetchall()
        for (data,) in rows:
            entry = WorldBibleEntry.model_validate_json(data)
            self._entries[entry.id] = entry

    def _put(self, entry: WorldBibleEntry) -> None:
        with _write_lock, _connect() as conn:
            conn.execute(
                """
                INSERT INTO world_bible_entries (run_id, entry_id, data) VALUES (?, ?, ?)
                ON CONFLICT(run_id, entry_id) DO UPDATE SET data=excluded.data
                """,
                (self._run_id, entry.id, entry.model_dump_json()),
            )
