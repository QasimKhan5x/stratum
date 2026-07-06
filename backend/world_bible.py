"""In-memory world bible.

ponytail: this is a temporary stand-in for Tablestore (see
stratum-architecture-plan.md's data layer section). Per the project's
local-first build order, the negotiation engine runs entirely against
this in-memory store first; swapping it for a Tablestore-backed
implementation with the same add/get/list/update surface is the
intended upgrade path once the core negotiation logic is proven.
"""

from __future__ import annotations

from backend.schemas import WorldBibleEntry


class WorldBible:
    def __init__(self) -> None:
        self._entries: dict[str, WorldBibleEntry] = {}

    def add(self, entry: WorldBibleEntry) -> None:
        self._entries[entry.id] = entry

    def get(self, entry_id: str) -> WorldBibleEntry | None:
        return self._entries.get(entry_id)

    def list(self) -> list[WorldBibleEntry]:
        return list(self._entries.values())

    def update(self, entry: WorldBibleEntry) -> None:
        if entry.id not in self._entries:
            raise KeyError(f"No existing world-bible entry with id '{entry.id}' to update.")
        self._entries[entry.id] = entry

    def canon_context(self) -> str:
        """Format non-rejected entries as a citable, ID-tagged list for
        agent prompts. This is the "current canon" every specialist reads
        before proposing or critiquing, and the exact list a critique's
        cited entry ID is checked against.

        ponytail: this includes each entry's full_text, not just its
        summary — found necessary via live testing, where agents working
        only from a vague one-line summary of a prior scene kept reinventing
        that scene's specific details (e.g. exactly whose confession a plot
        device contained) differently on every negotiation round, which is
        itself a contradiction the admission gate then had to catch. This
        doesn't scale forever (every entry's full text, forever, in every
        prompt): the upgrade path once world bibles get large is retrieval
        (only pull full text for entries plausibly relevant to what's being
        proposed, summary-only for the rest) rather than this flat dump.
        """
        citable = [e for e in self.list() if e.status != "rejected"]
        if not citable:
            return "(The world bible is currently empty — this is the first scene.)"
        return "\n\n".join(
            f"[{e.id}] ({e.status}) {e.summary}\n{e.full_text}" if e.full_text else f"[{e.id}] ({e.status}) {e.summary}"
            for e in citable
        )
