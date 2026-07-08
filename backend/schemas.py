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


EventType = Literal[
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


class DebateEvent(BaseModel):
    round: int
    scene: int
    agent: str | None = None
    event_type: EventType
    payload: dict
    # Which revision attempt (1-indexed) of this scene's negotiation this
    # event belongs to — see backend.negotiation.run_scene's retry loop.
    # Defaults to 1 so old saved runs (backend.schemas predates this field)
    # still parse: a clean one-pass admission is indistinguishable from
    # "attempt 1" anyway.
    attempt: int = 1
    # Which phase of the pipeline this event belongs to — lets a consumer
    # tell seed_entry (round=0, scene=0, agent="SEED") and baseline_ready
    # (round=0, scene=0, agent="BASELINE") apart without inferring it from
    # agent name or round number. Defaults to "negotiation" so every scene
    # 1+ call site is unaffected.
    phase: Literal["seed", "negotiation", "baseline"] = "negotiation"


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
