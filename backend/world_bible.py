"""In-memory world bible.

This base class now permanently serves three roles rather than being a
throwaway placeholder:

1. The base class both persistence tiers subclass — `backend.sqlite_store.
   SQLiteWorldBible` and `backend.cloud_storage.TablestoreWorldBible` both
   extend this class, overriding only add/update to write through to their
   respective stores, while inheriting get/list/canon_context as-is.
2. The last-resort fallback tier in `backend.cloud_storage.make_world_bible`'s
   three-tier factory (Tablestore -> SQLite -> this bare in-memory class),
   used if even a local SQLite file can't be opened (e.g. a read-only
   filesystem) — see that function's docstring.
3. The disposable "shadow bible" `backend.metrics.compute_comparison` builds
   to replay a baseline's paragraphs through the same admission-gate logic
   the negotiated pipeline uses, purely to compute a contradiction rate for
   comparison — never persisted, thrown away after that one calculation.

Not a stand-in for anything else shipping later; it's the permanent
in-memory implementation these three cases actually want.
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
