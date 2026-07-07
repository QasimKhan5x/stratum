# Stratum

Stratum is a multi-agent system that writes real, playable Twine stories
through adversarial negotiation: four specialist agents with genuinely
conflicting creative mandates propose, critique, and argue every scene
into existence before an Arbiter synthesizes it and a verified admission
gate checks it against everything already agreed. The output compiles to
valid Twee 3 notation, playable in the real Twine desktop app. Every
admitted scene is also illustrated automatically in a fixed cyanotype
style, and a human can inject a constraint mid-run that's admitted into
canon immediately and shapes every scene negotiated afterward.

**Live demo:** http://47.84.114.89 (Alibaba Cloud ECS, Singapore region)

## Architecture

```mermaid
flowchart TB
    subgraph Frontend["frontend/ (static, no build step)"]
        UI[Cyanotype hex map + debate panel<br/>D3.js, EventSource/SSE]
    end

    subgraph Backend["backend/ (FastAPI)"]
        API["main.py<br/>generate · stream · inject · world · export · metrics"]
        Orch["orchestrator.py<br/>seed → scenes 1..N → baseline (concurrent)"]
        Neg["negotiation.py<br/>per-scene: thesis → antithesis → judging →<br/>synthesis → admission (retry on rejection)"]
        Gate["admission_gate.py<br/>embedding screen → LLM contradiction check"]
        WB[("world_bible.py<br/>in-memory canon store")]
        McpClient["mcp_world_bible_client.py"]
    end

    subgraph MCP["Local MCP server (stdio subprocess)"]
        McpServer["mcp_world_bible_server.py<br/>check_contradiction · search_world_bible"]
    end

    subgraph Agents["backend/agents/"]
        Seed[seed.py]
        Spec["specialists.py<br/>Lorekeeper · Provocateur ·<br/>Harmonist · Architect"]
        Judges[judges.py]
        Arbiter[arbiter.py]
        Baseline[baseline.py]
        Illustrator[illustrator.py]
    end

    subgraph DashScope["Alibaba Cloud Model Studio (DashScope)"]
        Chat["qwen3.7-max / qwen-plus<br/>(OpenAI-compatible endpoint)"]
        Embed["text-embedding-v4"]
        Image["qwen-image-2.0-pro<br/>(native DashScope SDK)"]
    end

    subgraph ECS["Alibaba Cloud ECS deployment (ecs.e-c1m1.large, ap-southeast-1)"]
        Nginx["nginx<br/>serves frontend/ + reverse-proxies /api, /health"]
        Uvicorn["uvicorn (backend.main:app)<br/>managed by systemd (stratum.service)"]
    end

    UI <-- "SSE: DebateEvent stream" --> API
    API --> Orch --> Neg
    Neg --> Spec & Judges & Arbiter
    Neg --> Gate --> WB
    Gate --> McpClient
    McpClient -- "MCP: check_contradiction" --> McpServer
    McpClient -. "falls back in-process on failure" .-> Gate
    Orch --> Seed & Baseline
    Neg --> Illustrator
    Orch -. "concurrent, non-blocking" .-> Baseline
    Neg -. "concurrent, non-blocking" .-> Illustrator

    Seed & Spec & Judges & Arbiter & Baseline --> Chat
    Gate --> Embed
    Illustrator --> Image

    Nginx --> Uvicorn --> API
    Nginx -.-> UI
```

**Negotiation lifecycle** (`backend/negotiation.py`): each scene runs
thesis (all four specialists propose in parallel) → antithesis (structured
cross-critiques) → judging (four dimension-specific judges score every
proposal in one batched call each) → synthesis (the Arbiter rules,
favoring one proposal and stating what it overruled) → verified admission
(embedding-similarity screen, then an LLM contradiction check against only
the plausibly-related prior entries). A rejected synthesis triggers a
targeted re-negotiation of just the conflicting field, up to 3 attempts,
before the scene is honestly skipped rather than forced through.

**MCP integration** (`backend/mcp_world_bible_server.py`,
`backend/mcp_world_bible_client.py`): the admission gate's stage-1
embedding screen — ranking existing canon entries by cosine similarity to
a candidate scene, to narrow the field before the expensive LLM
contradiction check — runs through a small local MCP server instead of
being computed directly in-process. The server exposes two tools,
`check_contradiction` (used by the gate: which prior entries is this
candidate plausibly related to) and `search_world_bible` (general-purpose
top-k semantic lookup over canon, for future use by other agents). It's
spawned as a stdio subprocess per call via the official `mcp` Python SDK,
takes already-computed embedding vectors rather than raw text so it needs
no DashScope credentials or network access of its own, and every call is
wrapped in a fallback to the identical in-process computation if the MCP
round trip fails for any reason — so a real admission decision genuinely
flows through MCP on the common path, without putting the negotiation
critical path's reliability at the mercy of an extra subprocess.

Two distinct disagreement-resolution mechanisms are doing the work here,
not one: specialist-vs-specialist disagreement within a round is resolved
by the judge panel's scores plus the Arbiter's synthesis (a considered
ruling, not a vote or a coin flip); canon-level conflict — a synthesis
that contradicts something already agreed in an earlier round — is caught
separately by the admission gate and resolved by re-negotiation, not by
argument. The gate exists precisely because the first mechanism alone
can't catch that kind of contradiction: the Arbiter only sees this
round's four proposals, never the full canon.

**On "efficiency gain":** Stratum makes roughly 13-18 model calls per
scene (four proposals, four critiques, four judge-dimension batches, one
synthesis, plus occasional retries) against exactly one call for the
single-shot baseline — see `/api/metrics`'s `token_usage` figure. The
efficiency gain isn't fewer tokens; it's a favorable quality-per-token
trade a single agent has no mechanism to buy at any price, however many
tokens it's given.

## Setup

1. `.env` should already exist at the repo root with your DashScope and
   Alibaba Cloud credentials (see `.env.example` for the expected shape).
   It's git-ignored — never commit it.
2. Create a virtualenv and install dependencies (Python 3.11+):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Running locally

```bash
uvicorn backend.main:app --reload
```

Then serve the frontend as static files (no build step) from a second
terminal, e.g. `python3 -m http.server 8090` from `frontend/`, and open
`http://localhost:8090/index.html`.

### API

- `GET /health` — liveness check.
- `GET /api/models` — lists models visible to your `DASHSCOPE_API_KEY`.
- `POST /api/generate` — starts a run (`{"premise": str, "scene_count"?: int}`),
  returns `{"run_id": str}` immediately; generation runs in the background.
- `GET /api/stream/{run_id}` — SSE stream of `DebateEvent`s as the
  negotiation unfolds (proposals, critiques, judge scores, synthesis,
  admission results, image-ready, etc). Reconnecting mid-run replays
  everything emitted so far before continuing live.
- `GET /api/world/{run_id}` — the run's current world bible snapshot.
- `POST /api/inject/{run_id}` — inject a human constraint mid-run; it's
  admitted into canon immediately and visible to the next scene.
- `GET /api/export/{run_id}` — compiles the run to a `.twee` file.
- `GET /api/metrics/{run_id}` — contradiction rate, creative-divergence
  score, provenance depth, and token usage, compared against the
  single-shot baseline.
- `POST /api/runs/import` — re-registers a run saved by
  `scripts/save_demo_run.py` (see `demo_recordings/`) so it survives a
  server restart and can be replayed via `/api/stream` (see the demo
  section below).

## Demo

The locked demo run and the assembled `stratum_demo.mp4` live under
`demo_recordings/` (git-ignored — regenerate or re-download separately).
To replay a saved run instead of generating live:

```bash
python scripts/load_demo_run.py demo_recordings/<run-dir> "premise text"
# prints a run_id — open the frontend at:
#   ?run=<run_id>&pace=0.2&slow_from=8&slow_to=60&slow_pace=0.8
```

`pace` paces every event by a fixed delay so a finished run looks like
it's unfolding live; `slow_from`/`slow_to`/`slow_pace` slow down one index
range (e.g. the gate-catch scene) without dragging out the rest; `grace`
keeps the stream open a bit past completion so a live `/api/inject` demo
has time to land. All are recording conveniences only — see
`backend/main.py`'s `_stream_run`.

## Tests

```bash
pytest tests/
```

A Playwright smoke test also covers the frontend (page loads, core controls
are present, no console errors, and an axe-core scan finds no critical/
serious accessibility violations). Requires the frontend dev server running
on `:8090` (see "Running locally"):

```bash
npm install && npx playwright install chromium  # one-time setup
npx playwright test
```

## Deployment

Deployed on a single Alibaba Cloud ECS instance (`ecs.e-c1m1.large`,
Singapore/`ap-southeast-1`): nginx serves `frontend/` as static files and
reverse-proxies `/api/` and `/health` to a uvicorn process managed by
systemd (`stratum.service`, auto-restarts on failure).

## Submission Evidence Checklist

- Live demo URL: http://47.84.114.89
- Architecture diagram and system explanation: this README's Architecture
  section.
- Qwen/DashScope integration: `backend/models_client.py` for
  OpenAI-compatible chat, JSON, embeddings, and token accounting;
  `backend/agents/illustrator.py` for native DashScope qwen-image calls.
- MCP evidence: `backend/mcp_world_bible_server.py`,
  `backend/mcp_world_bible_client.py`, and
  `tests/test_mcp_admission_gate.py`.
- Demo replay path: `scripts/load_demo_run.py` with saved artifacts under
  `demo_recordings/` when available locally.
- Verification: `.venv/bin/python -m pytest tests/ -q`; frontend smoke via
  `npx playwright test` when frontend changes are in scope.
- ECS deployment evidence: this README's Deployment section and the live
  URL above. Current shipped deployment is a single ECS host with nginx and
  systemd; Tablestore-style persistent state remains a planned cloud-native
  upgrade, not a shipped claim.
- Demo video/artifact note: assembled video and locked replay artifacts are
  expected under git-ignored `demo_recordings/` or attached separately for
  judging.

## Further reading

Full architecture rationale, research foundations, hackathon context, and
the demo verification plan live in the planning docs at the repo root:

- `stratum-project-overview.md`
- `stratum-architecture-plan.md`
- `stratum-hackathon-reference.md`
- `stratum-demo-and-verification.md`
- `stratum-demo-premise.md`
