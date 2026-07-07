"""Shared test fixtures.

Forces `backend.cloud_storage.make_world_bible()`'s factory past its
Tablestore tier for the whole suite by default. Without this, any test
calling `backend.runs.create_run()` depends on whether the real Tablestore
instance happens to be reachable at test time — writing real test data into
production infrastructure when it is, and changing behavior out from under
tests that never meant to exercise Tablestore at all when it isn't. Tests
that specifically want to exercise `TablestoreWorldBible` (see
`tests/test_cloud_storage.py`) construct it directly against a fake OTS
client instead of going through this factory, so they're unaffected.
"""

from __future__ import annotations

import dataclasses

import pytest

from backend import cloud_storage


@pytest.fixture(autouse=True)
def _no_real_tablestore(monkeypatch):
    monkeypatch.setattr(
        cloud_storage,
        "settings",
        dataclasses.replace(cloud_storage.settings, tablestore_endpoint="", tablestore_instance_name=""),
    )
