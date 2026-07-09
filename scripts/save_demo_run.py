#!/usr/bin/env python3
"""Save a completed run's full state to disk for later replay.

Implements a "pre-generate and replay" fallback: record a real run once,
then replay it at a controlled pace (see backend.main's /api/stream
?pace/&slow_from/&slow_to params) for demo recording, without depending on
live model calls working on the one take that gets recorded.

The saved directory is exactly what POST /api/runs/import expects, so a
run can be restored into a *different* server process (e.g. after a
restart) with:

    python scripts/save_demo_run.py <run_id> demo_recordings/<run_id>
    python scripts/load_demo_run.py demo_recordings/<run_id>

Usage:
    python scripts/save_demo_run.py <run_id> [output_dir] [--base-url URL]
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def _parse_sse(raw: str) -> list[dict]:
    events = []
    for block in raw.split("\n\n"):
        event_type, data = None, None
        for line in block.strip().split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if event_type and data:
            events.append({"event": event_type, "data": json.loads(data)})
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("output_dir", nargs="?")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    out_dir = Path(args.output_dir or f"demo_recordings/{args.run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    world = _get_json(f"{args.base_url}/api/world/{args.run_id}")
    (out_dir / "world_state.json").write_text(json.dumps(world, indent=2))

    if world["status"] == "done":
        metrics = _get_json(f"{args.base_url}/api/metrics/{args.run_id}")
        (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    with urllib.request.urlopen(f"{args.base_url}/api/stream/{args.run_id}") as resp:
        raw = resp.read().decode()
    events = [e for e in _parse_sse(raw) if e["event"] != "run_complete"]
    (out_dir / "event_log.json").write_text(json.dumps(events, indent=2))

    try:
        with urllib.request.urlopen(f"{args.base_url}/api/export/{args.run_id}") as resp:
            (out_dir / "story.twee").write_bytes(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"twee export skipped: {exc}")

    print(f"saved run {args.run_id} ({len(events)} events) to {out_dir}/")


if __name__ == "__main__":
    main()
