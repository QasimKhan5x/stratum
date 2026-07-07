"""Tests for backend/cloud_storage.py.

TablestoreWorldBible is exercised against a fake OTS client (the real
`stratum-world` instance currently rejects all calls with
`OTSAuthFailed: The user is disabled.` — a console-side instance toggle, not
a code bug; see cloud_storage.py's module docstring) so its read/write logic
is proven correct independent of that external account state. The moment
the instance is re-enabled, this same code path runs for real with zero
changes.
"""

from __future__ import annotations

import tablestore

from backend.cloud_storage import TablestoreWorldBible, _bucket_endpoint
from backend.schemas import WorldBibleEntry


class FakeOTSClient:
    """Minimal in-memory stand-in for tablestore.OTSClient covering exactly
    the calls TablestoreWorldBible makes.
    """

    def __init__(self) -> None:
        self.tables: set[str] = set()
        self.rows: dict[tuple, str] = {}

    def list_table(self):
        return list(self.tables)

    def create_table(self, table_meta, table_options, reserved_throughput):
        self.tables.add(table_meta.table_name)

    def put_row(self, table_name, row, condition=None):
        key = tuple(row.primary_key)
        data = dict(row.attribute_columns)["data"]
        self.rows[key] = data

    def get_range(self, table_name, direction, start_pk, end_pk, limit=None):
        run_id = start_pk[0][1]
        matches = [(k, v) for k, v in self.rows.items() if dict(k)["run_id"] == run_id]
        rows = [tablestore.Row(list(k), [("data", v)]) for k, v in matches]
        return None, None, rows, None


def _entry(entry_id: str, status: str = "canon") -> WorldBibleEntry:
    return WorldBibleEntry(
        id=entry_id,
        summary=f"Summary {entry_id}",
        full_text=f"Full text {entry_id}",
        status=status,
        provenance_agent="ARBITER",
        provenance_round=1,
    )


def _make_store(monkeypatch, run_id: str) -> TablestoreWorldBible:
    fake_client = FakeOTSClient()
    monkeypatch.setattr(tablestore, "OTSClient", lambda *a, **k: fake_client)
    return TablestoreWorldBible(run_id)


def test_bucket_endpoint_strips_duplicate_bucket_prefix():
    assert (
        _bucket_endpoint("https://my-bucket.oss-ap-southeast-1.aliyuncs.com", "my-bucket")
        == "https://oss-ap-southeast-1.aliyuncs.com"
    )
    # Already-regional endpoints pass through unchanged.
    assert _bucket_endpoint("https://oss-ap-southeast-1.aliyuncs.com", "my-bucket") == "https://oss-ap-southeast-1.aliyuncs.com"


def test_tablestore_world_bible_add_get_list_round_trips(monkeypatch):
    store = _make_store(monkeypatch, run_id="run-a")
    store.add(_entry("scene-1"))
    store.add(_entry("scene-2"))

    assert store.get("scene-1").summary == "Summary scene-1"
    assert {e.id for e in store.list()} == {"scene-1", "scene-2"}


def test_tablestore_world_bible_update_persists_change(monkeypatch):
    store = _make_store(monkeypatch, run_id="run-b")
    store.add(_entry("scene-1", status="contested"))
    updated = _entry("scene-1", status="canon")
    store.update(updated)

    assert store.get("scene-1").status == "canon"


def test_tablestore_world_bible_recovers_state_after_restart(monkeypatch):
    fake_client = FakeOTSClient()
    monkeypatch.setattr(tablestore, "OTSClient", lambda *a, **k: fake_client)

    store = TablestoreWorldBible("run-c")
    store.add(_entry("scene-1"))
    store.add(_entry("scene-2"))

    # Simulate a process restart: a brand new instance, same backing table,
    # with an empty local cache until explicitly rehydrated.
    restarted = TablestoreWorldBible("run-c")
    assert restarted.list() == []
    restarted.load_from_tablestore()
    assert {e.id for e in restarted.list()} == {"scene-1", "scene-2"}


def test_tablestore_world_bible_isolates_entries_by_run_id(monkeypatch):
    fake_client = FakeOTSClient()
    monkeypatch.setattr(tablestore, "OTSClient", lambda *a, **k: fake_client)

    store_a = TablestoreWorldBible("run-x")
    store_a.add(_entry("scene-1"))
    store_b = TablestoreWorldBible("run-y")
    store_b.load_from_tablestore()

    assert store_b.list() == []
