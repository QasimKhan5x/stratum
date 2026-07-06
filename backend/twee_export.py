"""Exports the world bible as valid Twee 3 source text.

Per stratum-architecture-plan.md's "Data shapes" section and the official
Twee 3 specification, the export must produce:

  - A `StoryData` passage carrying a required IFID (a capital-letter v4
    UUID), the target story `format` field, and an optional `tag-colors`
    map — the field that makes agent provenance visible natively in real
    Twine software with no custom viewer required.
  - One passage per admitted world-bible entry: a `name`, an optional
    space-separated tag list, an optional inline JSON metadata block
    (position and size, derived from the entry's grid_position), and body
    text containing `[[link text->Target Passage]]` syntax for navigation
    between passages.

See stratum-demo-and-verification.md for the concrete acceptance check:
the exported file must open correctly in real Twine desktop / twinejs,
with a well-formed IFID, a recognized format value, tag colors rendering
as expected, and all links resolving to passages that actually exist.
"""

from __future__ import annotations

import json
import uuid

from backend.world_bible import WorldBible

# One of Twine's seven recognized tag-pill colors per provenance agent, so
# opening the exported file in real Twine shows the full argument history
# natively via the tag-colors field — no custom viewer required.
_TAG_COLORS = {
    "LOREKEEPER": "blue",
    "PROVOCATEUR": "red",
    "HARMONIST": "purple",
    "ARCHITECT": "green",
    "ARBITER": "gray",
    "SEED": "yellow",
    "HUMAN": "orange",
}

# ponytail: a flat grid-cell-to-pixel multiply, per the architecture plan's
# "the same cell-to-pixel lookup doubles as the position field" — no real
# layout engine. Upgrade path: a proper packing/spacing algorithm if hexes
# ever overlap visually in the real Twine editor.
_CELL_PX = 140


def _story_data(start_name: str) -> str:
    # ponytail: format-version is deliberately omitted. Pinning an exact
    # patch version (e.g. "3.3.9") makes the file reject on any compiler
    # that only has a different Harlowe patch installed (confirmed via a
    # real tweego compile during verification — it hard-errors on a
    # version mismatch rather than falling back). Every Twee 3 compiler
    # accepts a bare format name and picks its own installed version.
    payload = {
        "ifid": str(uuid.uuid4()).upper(),
        "format": "Harlowe",
        "start": start_name,
        "tag-colors": _TAG_COLORS,
    }
    return f":: StoryData\n{json.dumps(payload, indent=2)}\n"


def _position_metadata(grid_position: tuple[int, int] | None) -> str:
    if grid_position is None:
        return ""
    x, y = grid_position
    return f' {{"position":"{x * _CELL_PX},{y * _CELL_PX}","size":"100,100"}}'


def export_twee(world_bible: WorldBible, title: str = "Untitled Stratum World") -> str:
    """Serialize the world bible's admitted entries into Twee 3 source text.

    Args:
        world_bible: the world bible to export. Only entries with
            status "canon" are compiled as passages — contested/rejected
            entries are not yet part of the playable story.
        title: the story's display title (StoryTitle passage).

    Returns:
        The full Twee 3 source text: a StoryTitle passage, a StoryData
        passage (IFID, format, tag-colors), and one passage per admitted
        entry, chained so the compiled story is always playable start to
        finish.

    ponytail: link resolution is a linear backbone (each passage links to
    the next by round/creation order) plus any arbiter-declared link that
    happens to name a real passage ID — not full branch-aware routing.
    This is what guarantees every exported story actually plays through
    with no dead links, at the cost of not yet supporting genuine branching
    structure. Upgrade path: constrain the Architect's link vocabulary to
    only ever name already-admitted entry IDs, then drop the backbone
    fallback in favor of the real graph.
    """
    entries = sorted(
        (e for e in world_bible.list() if e.status == "canon"),
        key=lambda e: (e.provenance_round, e.id),
    )
    if not entries:
        raise ValueError("Cannot export a world bible with no canon entries.")

    known_ids = {e.id for e in entries}

    parts = [f":: StoryTitle\n{title}\n", _story_data(start_name=entries[0].id)]
    for i, entry in enumerate(entries):
        tags = " ".join([entry.provenance_agent, *entry.tags])
        position = _position_metadata(entry.grid_position)

        resolved_links = [link for link in entry.links if link in known_ids and link != entry.id]
        if i + 1 < len(entries) and entries[i + 1].id not in resolved_links:
            resolved_links.append(entries[i + 1].id)

        body = entry.full_text or entry.summary
        link_lines = "\n".join(f"[[Continue->{target}]]" for target in resolved_links)
        passage_body = f"{body}\n\n{link_lines}" if link_lines else body

        parts.append(f":: {entry.id} [{tags}]{position}\n{passage_body}\n")

    return "\n".join(parts)
