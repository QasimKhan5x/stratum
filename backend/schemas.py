"""Pydantic v2 data models shared across the negotiation engine."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel


class WorldBibleEntry(BaseModel):
    id: str
    summary: str
    full_text: str
    status: Literal["canon", "contested", "rejected"]
    provenance_agent: str
    provenance_round: int
    grid_position: tuple[int, int] | None = None
    embedding: list[float] | None = None
    tags: list[str] = []
    links: list[str] = []
    image_url: str | None = None


class DebateEvent(BaseModel):
    round: int
    scene: int
    agent: str | None = None
    event_type: Literal[
        "seed_entry",
        "proposal",
        "critique",
        "judge_score",
        "synthesis",
        "admission_result",
        "image_ready",
        "human_injection",
        "baseline_ready",
        "scene_failed",
    ]
    payload: dict


class AgentRole(str, Enum):
    LOREKEEPER = "LOREKEEPER"
    PROVOCATEUR = "PROVOCATEUR"
    HARMONIST = "HARMONIST"
    ARCHITECT = "ARCHITECT"
    ARBITER = "ARBITER"
    JUDGE_COHERENCE = "JUDGE_COHERENCE"
    JUDGE_PLAYABILITY = "JUDGE_PLAYABILITY"
    JUDGE_SURPRISE = "JUDGE_SURPRISE"
    JUDGE_TONE = "JUDGE_TONE"
