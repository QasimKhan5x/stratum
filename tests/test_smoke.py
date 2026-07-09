from fastapi.testclient import TestClient

from backend import main
from backend.main import app
from backend.models_client import MODEL_ROLES

client = TestClient(app)


def test_import_and_replay_run():
    """POST /api/runs/import (see scripts/save_demo_run.py's
    pre-generate-and-replay fallback) should reconstruct a run from
    exported events well enough that both /api/world and a replay of
    /api/stream see the same state a live run would have produced.
    """
    entry = {
        "id": "seed-00-test",
        "summary": "A drowned city resurfaces.",
        "full_text": "A drowned city resurfaces after decades underwater.",
        "status": "canon",
        "provenance_agent": "SEED",
        "provenance_round": 0,
        "grid_position": [0, 0],
    }
    event = {
        "round": 0,
        "scene": 0,
        "agent": "SEED",
        "event_type": "seed_entry",
        "payload": entry,
    }
    response = client.post(
        "/api/runs/import",
        json={
            "premise": "test premise",
            "events": [event],
            "world_bible_entries": [entry],
            "baseline_text": "a baseline paragraph",
            "status": "done",
        },
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    world = client.get(f"/api/world/{run_id}").json()
    assert world["status"] == "done"
    assert [e["id"] for e in world["entries"]] == ["seed-00-test"]

    with client.stream("GET", f"/api/stream/{run_id}") as stream:
        body = b"".join(stream.iter_bytes()).decode()
    assert "event: seed_entry" in body
    assert "event: run_complete" in body


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_generate_rejects_out_of_range_scene_count():
    """scene_count is public, unauthenticated input (POST /api/generate) —
    it must be bounded so a bad/malicious value can't kick off an
    arbitrarily expensive (real DashScope $$) run. Both requests must fail
    validation (422) before any background generation task is scheduled;
    if they didn't, this test would hang/error trying to reach DashScope."""
    too_many = client.post("/api/generate", json={"premise": "test premise", "scene_count": 999})
    assert too_many.status_code == 422

    too_few = client.post("/api/generate", json={"premise": "test premise", "scene_count": 0})
    assert too_few.status_code == 422


def test_generate_accepts_in_range_scene_count(monkeypatch):
    # BackgroundTasks run synchronously within TestClient's request/response
    # cycle, so the real background job is stubbed out here — this test is
    # only about request validation accepting boundary values (1 and 12),
    # not about exercising a real (costly) generation run.
    monkeypatch.setattr(main, "_run_generation_sync", lambda run, scene_count: None)

    for scene_count in (1, 12):
        response = client.post("/api/generate", json={"premise": "test premise", "scene_count": scene_count})
        assert response.status_code == 200
        assert "run_id" in response.json()


def test_model_roles():
    assert set(MODEL_ROLES.keys()) == {
        "seed",
        "arbiter",
        "specialist",
        "judge",
        "image",
        "embedding",
    }
    assert MODEL_ROLES["seed"] == "qwen3.7-max"
    assert MODEL_ROLES["arbiter"] == "qwen3.7-max"
    assert MODEL_ROLES["specialist"] == "qwen3.7-plus"
    assert MODEL_ROLES["judge"] == "qwen3.6-flash"
    assert MODEL_ROLES["image"] == "qwen-image-2.0-pro"
    assert MODEL_ROLES["embedding"] == "text-embedding-v4"
