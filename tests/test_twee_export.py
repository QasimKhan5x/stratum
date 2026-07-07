from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from backend.main import app
from backend.twee_export import export_twee
from backend.world_bible import WorldBible
from backend.schemas import WorldBibleEntry

client = TestClient(app)


def _canon_entry(
    entry_id: str,
    round_number: int,
    links: list[str] | None = None,
) -> WorldBibleEntry:
    return WorldBibleEntry(
        id=entry_id,
        summary=f"Summary for {entry_id}",
        full_text=f"Full text for {entry_id}.",
        status="canon",
        provenance_agent="ARBITER",
        provenance_round=round_number,
        grid_position=(round_number, round_number + 1),
        tags=["reef"],
        links=links or [],
    )


def test_export_twee_contains_storydata_metadata_and_resolved_links():
    world_bible = WorldBible()
    world_bible.add(_canon_entry("scene-start", 1, links=["scene-end", "missing-scene"]))
    world_bible.add(_canon_entry("scene-end", 2))

    twee = export_twee(world_bible, title="Test World")

    story_data = json.loads(twee.split(":: StoryData\n", 1)[1].split("\n\n::", 1)[0])
    assert re.fullmatch(r"[0-9A-F]{8}-[0-9A-F]{4}-4[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}", story_data["ifid"])
    assert story_data["format"] == "Harlowe"
    assert story_data["start"] == "scene-start"
    assert story_data["tag-colors"]["ARBITER"] == "gray"

    assert ":: StoryTitle\nTest World" in twee
    assert ':: scene-start [ARBITER reef] {"position":"140,280","size":"100,100"}' in twee
    assert ':: scene-end [ARBITER reef] {"position":"280,420","size":"100,100"}' in twee
    assert "[[Continue->scene-end]]" in twee
    assert "missing-scene" not in twee


def test_api_export_returns_twee_for_imported_done_run():
    entry = {
        "id": "seed-00-export",
        "summary": "A drowned city resurfaces.",
        "full_text": "A drowned city resurfaces after decades underwater.",
        "status": "canon",
        "provenance_agent": "SEED",
        "provenance_round": 0,
        "grid_position": [0, 0],
        "tags": ["origin"],
        "links": [],
    }
    response = client.post(
        "/api/runs/import",
        json={
            "premise": "export premise",
            "events": [],
            "world_bible_entries": [entry],
            "status": "done",
        },
    )
    assert response.status_code == 200

    export_response = client.get(f"/api/export/{response.json()['run_id']}")

    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("text/plain")
    assert ":: StoryData" in export_response.text
    assert ":: seed-00-export [SEED origin]" in export_response.text
