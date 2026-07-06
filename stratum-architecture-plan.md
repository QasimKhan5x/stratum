# Stratum — Architecture Plan

> **Shipped vs. planned:** this doc describes the original plan, including
> Tablestore/OSS/Function Compute/API Gateway below — the actual shipped
> system uses in-memory state (`backend/world_bible.py`, `backend/runs.py`)
> and a single Alibaba Cloud ECS instance instead (see README.md's
> "Deployment" section for what's really running).

This document describes the system conceptually: what each component does
and why, the data that flows between them, and the specific QwenCloud and
Alibaba Cloud services involved. It intentionally avoids full
implementation code — the target model for this build (Sonnet 5 /
Composer 2.5) needs the design decisions and constraints, not scaffolded
function bodies.

---

## System overview

Five layers, in order of data flow:

1. **Frontend** — a hex-grid map (D3, cyanotype/ink-wash visual register)
   rendering the negotiation live via Server-Sent Events, plus a debate
   panel, a world-bible browser, a human-constraint injection field, and
   export buttons (`.twee` / `.html`).
2. **Orchestration layer** — a FastAPI service holding SSE connections
   and coordinating the debate-round lifecycle. This must be a persistent
   process (ECS), not serverless, because SSE requires long-lived
   connections that Function Compute is not designed for.
3. **Agent workers** — six Function Compute functions: SeedAgent,
   Specialist (handles all four specialists and all four judges via a
   role parameter), Arbiter, Admission Gate, Image Generator, Baseline
   Agent (for the single-agent comparison).
4. **Model layer** — QwenCloud / DashScope API calls. See the model
   table below.
5. **Data layer** — Tablestore (world bible, debate log), OSS (scene
   images, frontend static assets, Twine exports, divergence corpus).

---

## QwenCloud reference

**Endpoint (confirmed stable, verified against QwenCloud's own
quickstart documentation):**
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
OpenAI-compatible — works directly with the standard OpenAI SDK by
swapping `base_url` and `api_key`.

**QwenCloud is the model-API layer only.** Its documentation scope is
entirely: text generation, images/video, audio, embeddings/reranking,
tool calling, structured output, thinking mode, batch API, streaming,
fine-tuning, and administration (API keys, workspaces, rate limits).
There is no general compute, storage, or database product under
QwenCloud — those are Alibaba Cloud products, a separate (though related)
account and console. A QwenCloud API key alone is sufficient to build and
test the entire agent/negotiation layer; Alibaba Cloud is only needed for
persistence, hosting, and the deployment proof the hackathon requires.

**Model names drift quickly.** Verify current availability before
building with:
```
curl -H "Authorization: Bearer $DASHSCOPE_API_KEY" \
  https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models
```

**Model assignments (current names as of this plan — reverify):**

| Model | Used for | Reasoning |
|---|---|---|
| `qwen3.7-max`, thinking on | SeedAgent, Arbiter | Both require deep reasoning over accumulated constraints — world foundation and final multi-objective synthesis are the two places reasoning quality matters most. Arbiter's thinking tokens stream to the debate panel live, turning otherwise-idle latency into visible content. |
| `qwen3.7-plus`, thinking off | Four specialist agents | Parallel, high-volume (8 calls per debate round), speed matters more than deep reasoning at this stage — reasoning complexity is concentrated at the Arbiter. |
| `qwen3.6-flash`, thinking off | Four judge agents | Cheapest tier; scoring against a single stated dimension is low-complexity and highest-volume relative to value, a natural place to save cost. Escalate back to `qwen3.7-plus` if judge output proves inconsistent in testing. |
| `qwen-image-2.0-pro` | Scene illustration | One call per admitted scene, fired asynchronously outside the negotiation critical path. A separate lightweight `qwen3.7-plus` call first converts the scene's narrative text into a tightly-scoped image prompt in the fixed cyanotype/ink-wash register, rather than passing raw narrative prose directly to the image model. |
| `text-embedding-v4` (verify current name/version) | Admission gate, divergence metric | Semantic similarity check at admission time; also used to compute the creative-divergence score against a precomputed corpus of generic genre synopses for the baseline comparison. |
| — (planned, not shipped) | Lorekeeper grounding | MCP-based web search for real-world plausibility checks was planned here but never implemented. What's actually shipped: the Lorekeeper reads the full world-bible canon context on every call and its prompt requires citing a specific entry ID for any critique — grounding is against established in-fiction canon, not external real-world facts. |

---

## Alibaba Cloud reference

Separate account/console from QwenCloud, same underlying company. Needed
specifically for: persistence, static/asset hosting, serverless agent
execution, and the "proof of Alibaba Cloud deployment" the hackathon
rules require.

| Service | Role | Why this and not something else |
|---|---|---|
| **Tablestore** | World bible + debate log, with native vector search | Purpose-built "AI Agent Memory" data model with vector index support out of the box — avoids standing up a separate vector database. |
| **OSS** | Scene images, frontend static build, Twine `.twee`/`.html` exports, divergence corpus | Standard object storage; images have to be re-hosted here anyway since DashScope's returned image URLs expire in 24 hours. |
| **Function Compute** | Six agent-worker functions | Serverless, scales to zero between demo runs, matches the "one function per agent role" decomposition naturally. |
| **API Gateway** | Auth layer in front of Function Compute | FC's native auth is HMAC-signed requests, which is unnecessary complexity for this project; putting API Gateway in front with a simple API key is far less implementation overhead for the timeline available. |
| **ECS** (small instance) | FastAPI orchestrator | The one piece that must be a persistent process rather than serverless, because it holds SSE connections open to the frontend for the duration of generation. |

**Region:** Singapore (`ap-southeast-1`) throughout — the international
endpoint, lowest latency for an EU-based demo audience.

**Twine and Tweego add zero new Alibaba services.** Twine itself is never
deployed anywhere — it's a desktop/browser tool end users run locally.
The integration is a serialization step against data already being
written to Tablestore, plus one small vendored binary (Tweego, an
open-source Go compiler, a few MB) invoked from the existing ECS
instance, plus one new OSS object type for the export files.

---

## Data flow, end to end

1. User submits a premise. The **SeedAgent** (`qwen3.7-max`, thinking on)
   reads it and produces 6–8 foundational world-bible entries — enough
   concrete facts and at least one deliberately unresolved tension for
   the specialists to have something real to argue about from round one.
   Each entry gets a position on the map grid.
2. For each scene: the four **specialists** read the current world bible
   and propose in parallel (**thesis**). They then critique each other in
   fixed structural pairs plus dynamically-selected targets (**antithesis**)
   — critiques must cite a specific prior entry as evidence, or they are
   rejected and re-requested.
3. The four **judges** score all four proposals on coherence,
   playability, surprise, and tone.
4. The **Arbiter** synthesizes one final scene informed by the proposals,
   critiques, and judge scores, states which proposal it favored and
   which it overruled, and produces the passage's position, links, and
   Twine tags.
5. The **admission gate** checks the proposed scene against the existing
   world bible: a cheap embedding-similarity screen runs first, and only
   pairs above a similarity threshold trigger the more expensive LLM
   contradiction check. In the Twine-targeted design, this stage also
   rejects passages linking to a target that will never exist. Rejected
   scenes trigger a **targeted re-negotiation** of only the conflicting
   field, not a full restart.
6. Admitted scenes are committed to Tablestore, streamed to the frontend
   as they happen, and trigger an async image-generation call that never
   blocks the next round from starting.
7. At any point, the world bible can be **exported**: a plain
   text-templating function serializes admitted entries into valid Twee 3
   notation (with agent provenance encoded as native passage tags and
   assigned tag-colors), and optionally compiled via the vendored Tweego
   binary into a standalone playable HTML file.
8. A parallel **baseline agent** runs the same premise as a single
   sequential `qwen3.7-max` call with no debate loop, no admission gate,
   and no world-bible structure, for the efficiency-gain comparison.

---

## Key architectural decisions and why

**Why a hex grid, not a free-form node graph.** A grid gives deterministic,
demo-legible layout without needing real coordinate-geometry reasoning
from the agents — the Architect just names an unoccupied cell rather than
computing pixel positions, and fog-of-war over unassigned cells is an
immediately legible visual metaphor for "not yet negotiated." The same
cell-to-pixel lookup doubles as the `position` field required by Twee's
metadata block, so the map and the export format share one source of
truth rather than needing separate coordinate systems.

**Why critiques must cite a specific entry ID.** This is the direct,
practical answer to the MAST failure-taxonomy finding that unstructured
coordination causes the majority of production multi-agent failures.
Free-form disagreement risks becoming vague or sycophantic; a citation
requirement forces every objection to be falsifiable against something
concrete.

**Why the admission gate is two-stage.** Checking every new proposal
against every existing entry with an expensive LLM call does not scale as
the world bible grows. A cheap embedding-similarity pre-filter means the
expensive check only fires on the rare pairs that are actually similar
enough to plausibly contradict — this is a real engineering optimization,
not just a description of a check that happens.

**Why generation pre-fetches the next round's proposals during the
current round's synthesis.** Without this, the perceived latency between
scenes (specialist calls, several seconds each) breaks the sense that the
negotiation is continuous and live. Running the next round's thesis calls
in the background while the current Arbiter is synthesizing means the
next round's proposals are usually already available by the time they're
needed, with a bounded timeout fallback if they aren't.

**Why the baseline never gets a seed step or world-bible structure.**
The comparison needs to isolate the effect of structured, negotiated
generation specifically — giving the baseline the same rich seed would
muddy which part of the architecture produces the measured gain. The
baseline is deliberately the leanest fair comparison: same model, same
premise, no scaffolding.

**Why Twine integration is purely additive at the serialization layer,
never touching Twine's own codebase.** Twine's editor application
(twinejs) is a large Electron/React app not designed for this kind of
integration; forking or embedding it would be a significant, high-risk
engineering task for uncertain benefit. Generating valid Twee 3 text —
a plain, well-specified, human-readable format — and optionally
compiling it with the small, stable, open-source Tweego binary achieves
full compatibility with zero risk to the negotiation engine and zero new
infrastructure.

---

## Data shapes, described (not code)

**A world-bible entry** carries: a unique ID, a compact summary (the
"gist" agents read by default) and full text (read on demand), a status
(canon, contested, or rejected), provenance (which agent or process
produced it, and in which round), its grid position if it represents a
location, an embedding vector for the admission gate, and — specific to
the Twine target — its assigned tags and any outbound links to other
entries.

**A debate event**, streamed over SSE and logged for replay/provenance,
carries: which round and scene it belongs to, which agent (if any)
produced it, its type (a proposal, a critique, a synthesis, an admission
result, an image becoming ready, a human injection), and its payload.

**A Twee passage**, per the official Twee 3 specification: a name, an
optional space-separated tag list, an optional inline JSON metadata block
(position and size), and body text containing `[[link text->Target
Passage]]` syntax for navigation. The story-level `StoryData` passage
carries a required IFID (a capital-letter v4 UUID), the target story
format, and an optional `tag-colors` map — this last field is what makes
agent provenance visible natively in real Twine software with no custom
viewer required.
