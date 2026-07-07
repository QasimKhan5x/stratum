"""One-off: re-import the saved demo run into the (in-memory) running backend.

Run with: .venv/bin/python scripts/reimport_demo_run.py
"""

import json
from pathlib import Path

import requests

RECORDING_DIR = Path(__file__).resolve().parent.parent / "demo_recordings" / "c7c529ae8bdd"
API_BASE = "http://localhost:8000"


def main() -> None:
    world_state = json.loads((RECORDING_DIR / "world_state.json").read_text())
    event_log = json.loads((RECORDING_DIR / "event_log.json").read_text())

    events = [e["data"] for e in event_log if e["event"] != "run_complete"]
    baseline_event = next(e for e in event_log if e["event"] == "baseline_ready")
    baseline_text = baseline_event["data"]["payload"]["text"]

    payload = {
        "premise": "A drowned coastal city resurfaces after a 60-year submersion, its resurgence contested by rival factions.",
        "events": events,
        "world_bible_entries": world_state["entries"],
        "baseline_text": baseline_text,
        "status": "done",
    }

    res = requests.post(f"{API_BASE}/api/runs/import", json=payload, timeout=30)
    res.raise_for_status()
    run_id = res.json()["run_id"]
    (RECORDING_DIR / "imported_run_id.txt").write_text(run_id)
    print(run_id)


if __name__ == "__main__":
    main()
