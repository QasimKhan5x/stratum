#!/usr/bin/env python3
"""Restore a run saved by scripts/save_demo_run.py into a running server.

Necessary because Run/WorldBible storage is in-memory (see backend/runs.py's
documented ponytail limitation): a server restart otherwise makes a saved
run's data undisplayable through the normal UI, even though the data
itself is preserved on disk by save_demo_run.py.

Usage:
    python scripts/load_demo_run.py <saved_run_dir> [premise] [--base-url URL]

Prints the new run_id — use it in the frontend as ?run=<run_id>, optionally
with &pace=<seconds> for a controlled-speed replay (see backend.main's
/api/stream).
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("saved_run_dir")
    parser.add_argument("premise", nargs="?", default="(restored demo run)")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    run_dir = Path(args.saved_run_dir)
    world = json.loads((run_dir / "world_state.json").read_text())
    event_log = json.loads((run_dir / "event_log.json").read_text())

    baseline_text = next(
        (e["data"]["payload"]["text"] for e in event_log if e["event"] == "baseline_ready"),
        None,
    )

    payload = {
        "premise": args.premise,
        "events": [e["data"] for e in event_log if e["event"] != "run_complete"],
        "world_bible_entries": world["entries"],
        "baseline_text": baseline_text,
        "status": world.get("status", "done"),
    }
    req = urllib.request.Request(
        f"{args.base_url}/api/runs/import",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    print(result["run_id"])


if __name__ == "__main__":
    main()
