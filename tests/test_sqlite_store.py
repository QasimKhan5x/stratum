"""Tests for backend/sqlite_store.py — the default, zero-config persistence
tier that makes runs survive a restart and lets more than one backend
process serve/stream the same run (the concrete horizontal-scalability and
self-host-without-a-cloud-account story; see that module's docstring).
"""

from __future__ import annotations

import threading
import time

import pytest

from backend import sqlite_store
from backend.runs import Run, _RUNS, create_run, get_run
from backend.schemas import DebateEvent, WorldBibleEntry


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Each test gets its own throwaway SQLite file and a clean in-memory
    run cache, so tests can't see each other's runs. (Tablestore is already
    forced off for the whole suite by tests/conftest.py's `_no_real_tablestore`
    fixture, so `make_world_bible()` lands on the SQLite tier these tests
    are actually exercising.)
    """
    monkeypatch.setattr(sqlite_store, "_DB_PATH", str(tmp_path / "test.db"))
    sqlite_store.init_db()
    _RUNS.clear()
    yield
    _RUNS.clear()


def _event(round_: int, event_type: str = "proposal") -> DebateEvent:
    return DebateEvent(round=round_, scene=1, agent="LOREKEEPER", event_type=event_type, payload={"n": round_})


def test_run_survives_being_dropped_from_the_in_memory_cache():
    run = create_run("a haunted lighthouse")
    run.emit(_event(1))
    run.emit(_event(2))
    run.status = "done"
    run.baseline_text = "once upon a time"
    run.emit(_event(3, "baseline_ready"))  # emit() is what actually persists status/baseline_text

    # Simulate a restart (or a second backend replica that never held this
    # run in memory): the only way to get it back is via SQLite.
    _RUNS.clear()
    reloaded = get_run(run.id)

    assert reloaded is not None
    assert reloaded.id == run.id
    assert reloaded.status == "done"
    assert reloaded.baseline_text == "once upon a time"
    assert [e.round for e in reloaded.events] == [1, 2, 3]


def test_world_bible_entries_persist_across_a_reload():
    run = create_run("a haunted lighthouse")
    run.world_bible.add(
        WorldBibleEntry(id="e1", summary="s", full_text="f", status="canon", provenance_agent="SEED", provenance_round=0)
    )

    _RUNS.clear()
    reloaded = get_run(run.id)

    assert reloaded is not None
    assert [e.id for e in reloaded.world_bible.list()] == ["e1"]


def test_refresh_events_from_store_picks_up_events_written_by_another_process():
    run = create_run("a haunted lighthouse")
    run.emit(_event(1))

    # A second "process" loads the same run from SQLite with only what
    # existed at that point...
    _RUNS.clear()
    second_process_view = get_run(run.id)
    assert second_process_view is not None
    assert len(second_process_view.events) == 1

    # ...then the first process (still holding its own in-memory `run`)
    # emits more events...
    run.emit(_event(2))
    run.emit(_event(3))

    # ...and the second process's view catches up via a refresh, exactly
    # what backend.main._stream_run's poll loop calls on every tick.
    second_process_view.refresh_events_from_store()
    assert [e.round for e in second_process_view.events] == [1, 2, 3]


def test_get_run_returns_none_for_an_unknown_run_id():
    assert get_run("does-not-exist") is None


def test_concurrent_writers_do_not_lose_or_corrupt_events():
    """Exercises the concurrency ceiling sqlite_store.py's ponytail comment
    already discloses (WAL mode: many readers, one writer per file) under
    real thread contention, rather than just asserting it in prose. Several
    threads hammer append_event against the *same* run/db file at once;
    `_write_lock` should serialize the actual writes so every one of them
    lands exactly once, with no interleaved/corrupted rows and no silent
    drops — the failure mode a missing/broken lock would produce.
    """
    run = create_run("a concurrency stress test")
    thread_count = 8
    events_per_thread = 25

    def write_events(thread_index: int) -> None:
        base_seq = thread_index * events_per_thread
        for i in range(events_per_thread):
            sqlite_store.append_event(
                run.id,
                base_seq + i,
                DebateEvent(
                    round=thread_index,
                    scene=1,
                    agent="LOREKEEPER",
                    event_type="proposal",
                    payload={"thread": thread_index, "i": i},
                ),
            )

    threads = [threading.Thread(target=write_events, args=(t,)) for t in range(thread_count)]
    started_at = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    elapsed = time.monotonic() - started_at

    assert all(not thread.is_alive() for thread in threads), "a writer thread hung/deadlocked"
    assert elapsed < 10, f"concurrent writers took too long ({elapsed:.2f}s) — possible lock contention regression"

    all_events = sqlite_store.load_events_from(run.id, 0)
    assert len(all_events) == thread_count * events_per_thread

    # No duplicate/interleaved corruption: every (thread, i) pair written
    # exactly once, and every payload deserialized cleanly as valid JSON
    # (a corrupted write would show up here as a garbled or missing pair).
    seen = {(e.payload["thread"], e.payload["i"]) for e in all_events}
    expected = {(t, i) for t in range(thread_count) for i in range(events_per_thread)}
    assert seen == expected


def test_runs_are_isolated_from_each_other():
    run_a = create_run("premise a")
    run_a.emit(_event(1))
    run_b = create_run("premise b")
    run_b.emit(_event(9))

    _RUNS.clear()
    assert [e.round for e in get_run(run_a.id).events] == [1]
    assert [e.round for e in get_run(run_b.id).events] == [9]
