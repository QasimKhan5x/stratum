"""Manual, real-API smoke check for the negotiation engine.

Not part of the pytest suite deliberately — this hits DashScope for real
(seed step + one full scene: 4 proposals, 4 critiques, 16 judge scores, 1
synthesis, at least one admission-gate check), which costs real tokens and
takes real wall-clock time. Run by hand after changing any agent-logic code:

    .venv/bin/python scripts/smoke_negotiation.py

Prints the seeded canon, the admitted scene, and which proposal the Arbiter
favored/overruled, so a human can actually read the output quality — per
stratum-demo-and-verification.md's verification loop, passing this doesn't
prove the negotiation is *interesting*, only that it runs correctly end to
end. Judging output quality still needs a human reading it.
"""

from __future__ import annotations

import asyncio

from backend.agents.seed import generate_seed
from backend.negotiation import run_scene
from backend.world_bible import WorldBible

PREMISE = (
    "Tideglass Reach: a coastal city, drowned for two generations, has just "
    "resurfaced after an unexplained \"long ebb.\" The Tideglass Guild and "
    "the Hush Choir are racing to claim it before the other does — and "
    "nobody agrees on whether the bell tone divers keep hearing near the "
    "Cathedral Spire is a hazard, a hoax, or a warning."
)


async def main() -> None:
    print("=== Seeding world bible ===")
    world_bible = WorldBible()
    for entry in generate_seed(PREMISE):
        world_bible.add(entry)
        print(f"[{entry.id}] ({entry.status}) {entry.summary}")

    contested = [e for e in world_bible.list() if e.status == "contested"]
    assert contested, "Seed produced no contested entry — prompt needs tuning."
    print(f"\n{len(world_bible.list())} entries seeded, {len(contested)} contested.\n")

    print("=== Running scene 1 negotiation ===")
    admitted = await run_scene(world_bible, round_number=1)
    print(f"\nAdmitted: [{admitted.id}] ({admitted.status})")
    print(f"Summary: {admitted.summary}")
    print(f"Grid position: {admitted.grid_position}")
    print(f"Tags: {admitted.tags}")
    print(f"\nFull text:\n{admitted.full_text}")


if __name__ == "__main__":
    asyncio.run(main())
