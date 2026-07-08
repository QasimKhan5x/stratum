"""Shared test fixtures and stub helpers.

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


# Shared negotiation-stage stubs, used by test_resilience.py and
# test_traceability_fixes.py to mock backend.negotiation.run_scene's
# specialist/judge calls without hitting a real model.
def stub_proposal(role) -> dict:
    return {"role": role.value, "scene_title": "t", "summary": "s", "full_text": "f", "tags": [], "grid_position": [0, 0]}


def stub_critique(critic_role, target_proposal, world_bible) -> dict:
    return {"critic_role": critic_role.value, "target_role": target_proposal["role"], "objection": "none", "cited_entry_id": "n/a", "hard_flag": False}


def stub_score_all(dimension, proposals, world_bible) -> list[dict]:
    return [{"dimension": dimension, "role_scored": p["role"], "score": 5, "rationale": "ok"} for p in proposals]
