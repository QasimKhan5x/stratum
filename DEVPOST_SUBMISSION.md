# Devpost submission draft — Stratum (Track 3: Agent Society)

Ready-to-paste text for the `qwencloud-hackathon.devpost.com` "Enter a Submission" form.
Every claim below is traceable to `README.md`, `BLOG_POST.md`,
`stratum-critical-review-checklist.md`, `stratum-architecture-plan.md`, or
`stratum-baseline-fairness-experiment.md` in this repo — nothing invented. Placeholders
that only a human can fill in are marked `[LIKE THIS]`.

Verified directly against the live `qwencloud-hackathon.devpost.com` rules pages on
2026-07-08 — see the "Definitive Devpost requirements" section at the bottom of this file
for the sourcing and two real discrepancies found against the prior session's notes.

---

## Track

**Track 3: Agent Society**

## Project name

Stratum

## Tagline / elevator pitch

*(Devpost's short one-line pitch field — keep under ~120 characters if the field is
character-limited; trim as needed)*

Four AI agents with genuinely incompatible mandates argue every scene of a story into
existence before it becomes canon — and the argument compiles to a real, playable Twine file.

## Links

- **Code repository:** https://github.com/QasimKhan5x/stratum (public, MIT licensed,
  license file detected by GitHub at the repo root)
- **Live demo:** http://47.84.114.89 (Alibaba Cloud ECS, Singapore region) — confirmed
  live and responding as of this write-up
- **Demo video:** [PASTE YOUTUBE LINK HERE — upload `demo_recordings/video_assets_v5/stratum_demo_v5.mp4`
  (167.5s, under the 3-minute judge-viewing cap) to YouTube as public/unlisted-public and paste the link]
- **Proof of Alibaba Cloud deployment (code file link, per the actual Devpost
  requirement — see note below):**
  https://github.com/QasimKhan5x/stratum/blob/main/backend/cloud_storage.py
  (real `oss2`/`tablestore` SDK usage — OSS upload+signed URL and Tablestore
  read/write, both live-verified against the real provisioned Alibaba Cloud
  resources; see that file's docstring and `stratum-critical-review-checklist.md`'s
  P0-1 row for the verification trail). Supplementary short screen recording also
  available locally at `demo_recordings/alibaba_cloud_deployment_proof.mp4` (33.5s,
  not required by the current rules text but kept as extra evidence — not committed
  to git per this repo's `.gitignore`, so it isn't linkable on GitHub; only the code
  file link is guaranteed to work as the Devpost-required proof).
- **Architecture diagram:** the Mermaid diagram in `README.md`'s "Architecture"
  section, rendered inline on the GitHub repo page:
  https://github.com/QasimKhan5x/stratum#architecture
- **Blog post (optional, for the separate Blog Post Prize):** `BLOG_POST.md` is
  written and complete in the repo, but not yet published to a public blog/social
  platform. [PASTE PUBLISHED BLOG/SOCIAL POST URL HERE IF PUBLISHING FOR THE BONUS PRIZE — OPTIONAL]

## Built With

Python, FastAPI, uvicorn, vanilla JavaScript, D3.js, Server-Sent Events (SSE), SQLite,
Alibaba Cloud ECS, Alibaba Cloud OSS, Alibaba Cloud Tablestore, QwenCloud / DashScope
(`qwen3.7-max`, `qwen3.7-plus`, `qwen3.6-flash`, `qwen-image-2.0-pro`,
`text-embedding-v4`), Model Context Protocol (MCP), OpenAI-compatible SDK, Twine / Twee 3,
Tweego, nginx, systemd, pytest, Playwright, axe-core

---

## Inspiration

Almost every AI-assisted worldbuilding or game-generation system today is a pipeline:
one agent (or one model, prompted in sequence) hands its output to the next stage —
generate premise, then locations, then characters, then scenes. Nothing in that chain
is designed to disagree with anything else in it, so nothing catches a contradiction,
and nothing pushes back on the safest, most generic continuation of whatever came
before.

Track 3 (Agent Society) asks for a system where agents actually negotiate — decompose
tasks, disagree, and resolve conflict — with a measurable efficiency gain over a
single-agent baseline. We wanted to build that literally, not just claim it: what if
four agents with genuinely incompatible creative mandates were forced to litigate every
scene of a story before it became canon, and the disagreement itself was a first-class,
visible part of the output instead of noise averaged away?

## What it does

Stratum is a framework for multi-agent creative negotiation. Four specialist agents —
**Lorekeeper** (defends established canon, must cite the specific entry it thinks a
proposal violates), **Provocateur** (structurally required to push against whatever
looks safest), **Harmonist** (enforces tonal consistency, can raise a hard flag the
Arbiter can't just weigh and move past), and **Architect** (owns spatial/traversal
logic) — negotiate a Twine interactive-fiction scene by scene, live, streamed to a
debate panel on a cyanotype-styled hex map.

Each scene runs the same loop: **thesis** (all four propose in parallel), **antithesis**
(structured, cited cross-critiques), **judging** (four dimension-specific judges score
every proposal), **synthesis** (an Arbiter rules on one final version and states what it
overruled), and **verified admission** (an embedding-similarity screen, then an LLM
contradiction check against everything already agreed — a rejected synthesis triggers a
targeted re-negotiation of just the conflicting field, not a full restart). A user can
inject a constraint mid-run (e.g. "the surveyor is blind") and it's admitted into canon
immediately, shaping the very next round.

Two distinct disagreement mechanisms are both surfaced live in the UI, not buried in
transcript prose: a disagreement banner + persistent timeline badge when the Arbiter
overrules a specialist, and a separate gate-rejection banner when a synthesis
contradicts established canon. Every admitted scene also gets an auto-generated
illustration and compiles to a real, valid Twee 3 file, playable in the actual Twine
desktop app — verified by compiling real exports with the official Tweego compiler
(exit code 0, zero errors).

## How we built it

- **Backend:** FastAPI (`backend/main.py`) orchestrates the negotiation
  (`backend/orchestrator.py`, `backend/negotiation.py`) and streams every event over
  SSE. Five distinct QwenCloud model roles run through the OpenAI-compatible DashScope
  endpoint: `qwen3.7-max` (world-foundation seeding and final synthesis, thinking on),
  `qwen3.7-plus` (the four parallel specialists), `qwen3.6-flash` (the four judges,
  batched into one call per judge instead of one call per proposal to cut model calls
  4x with no quality loss), `text-embedding-v4` (the admission gate's similarity
  screen), and `qwen-image-2.0-pro` via DashScope's native SDK (scene illustration,
  the one piece that isn't provider-swappable since it's not on the OpenAI-compatible
  endpoint).
- **MCP integration:** the admission gate's embedding-similarity screen runs through a
  small local MCP server (`backend/mcp_world_bible_server.py`,
  `backend/mcp_world_bible_client.py`) spawned as a stdio subprocess via the official
  `mcp` Python SDK, exposing `check_contradiction` and `search_world_bible` tools —
  with a fallback to identical in-process computation if the MCP round trip fails, so
  reliability on the negotiation critical path doesn't depend on an extra subprocess.
- **Persistence:** SQLite by default (`backend/sqlite_store.py`, WAL mode, zero new
  dependencies), with a genuine Alibaba Cloud Tablestore implementation
  (`TablestoreWorldBible`) as a drop-in upgrade behind the same four-method interface,
  live-verified with a real read/write round-trip against the provisioned instance.
  Exported `.twee` files upload to a real Alibaba Cloud OSS bucket and come back with a
  7-day signed URL, verified end-to-end including from the ECS host itself.
- **Frontend:** vanilla JS + D3.js rendering a hex-grid map (cyanotype/blueprint visual
  register) and a live debate panel over SSE, no build step.
- **Deployment:** a single Alibaba Cloud ECS instance (`ecs.e-c1m1.large`,
  Singapore/`ap-southeast-1`) — nginx serves the static frontend and reverse-proxies
  `/api` and `/health` to a uvicorn process managed by systemd, auto-restarting on
  failure.
- **Testing:** 57 automated tests (`pytest`, fully mocked — no external services or API
  keys required, runs in CI via `.github/workflows/test.yml`) plus a Playwright smoke
  test (page load, core controls, zero console errors, an axe-core accessibility scan).

## Challenges we ran into

- The admission gate's first retry loop threw away all context on a rejection and just
  asked agents to "try again," which produced *worse* contradictions on the second
  attempt — fixed by threading the specific rejection reason and full canon context
  into the retry.
- An unhandled exception from a single failed scene could crash the entire server
  process for every run in flight, discovered mid-testing on a slow-DashScope day — now
  an unresolvable scene is an honest, logged outcome instead of a crash.
- The hex map that illustrates each admitted scene was, for most of development, mostly
  empty and clustered in one corner: a 96-cell (12×8) grid against a typical run that
  only ever fills 8-15 hexes, fed by a placement prompt with no stated bounds or spread
  instruction. Shrinking the grid to 6×5 and giving the model explicit bounds + a
  spread instruction fixed it — a real run's seed entries landed genuinely spread
  across the grid, not clustered near the origin.
- Alibaba Cloud Tablestore briefly went dark mid-build (`OTSAuthFailed: The user is
  disabled`) when the provisioned instance got disabled account-side — logged as a
  blocked item rather than papered over, and re-verified live (a real `put_row` write
  and fresh-client read-back) once fixed. That same re-verification pass surfaced a
  second, previously-latent bug: real Tablestore rows carry a trailing per-column
  timestamp our code didn't handle, because our own unit-test fake client never
  exercised that shape — fixed, and the fake client's return shape corrected so the
  same class of drift can't hide behind a passing test suite again.
- Our own efficiency-gain claim didn't survive an honest, harder fairness check: a
  single agent given the *same* compute budget (spent on self-critique/revision
  instead of negotiation) closes most of the gap on one metric. We ran that check
  ourselves rather than avoid it — see "What we learned" below.

## Accomplishments that we're proud of

- A working, deployed, five-agent negotiation loop with two distinct, separately
  surfaced disagreement-resolution mechanisms (specialist-vs-specialist via the judge
  panel + Arbiter; canon-level contradiction via the admission gate) — not one
  disagreement mechanism doing double duty.
- Real, live-verified Alibaba Cloud OSS and Tablestore integration (not just DashScope
  model calls), plus an ECS deployment that survives a genuine production restart with
  SQLite-backed persistence.
- Every admitted scene compiles to a real, valid Twee 3 file — verified by compiling
  actual exports with the official Tweego compiler, exit code 0, zero errors, every
  passage link resolving correctly.
- We built and ran a genuinely adversarial fairness check against our own efficiency
  claim (a compute-matched single-agent baseline, not just a 1-call strawman),
  replicated it across 3 independent premises, and reported the result even where it
  didn't fully support the pitch.
- 57 automated tests, fully mocked, running in CI on every push — including tests that
  caught a real production-shaped bug (a Tablestore row-shape mismatch) that would
  otherwise have hidden behind a passing suite.

## What we learned

The honest, harder fairness experiment (`scripts/baseline_fairness_replication.py`,
n=3 premises, full methodology in `stratum-baseline-fairness-experiment.md`) taught us
that our first framing of "efficiency gain" was too broad. The `divergence_score`
result that originally favored Stratum did **not** replicate cleanly — on the original
premise rerun fresh, Stratum and a compute-matched reflective baseline are a
statistical tie (0.5704 vs. 0.5708); Stratum was clearly ahead on the two new premises.
What *did* replicate 3-for-3, and is now a quantified metric rather than one person's
reading of one baseline's prose: a new `premature_resolution` metric shows Stratum's
admission gate protected a deliberately contested, seed-marked fact in every premise
(0/3), while both the naive and the compute-matched single-agent baseline collapsed it
into a confident answer in 2 of 3. The real, narrower, now-evidenced claim is that
Stratum's gate gives the system a structural mechanism for protecting deliberate
ambiguity that self-critique alone doesn't reliably provide — not a categorical
advantage on every metric. We'd rather submit that honest, replicated finding than a
broader claim that doesn't hold up under a harder check.

On the engineering side: batching the judge panel's 16 calls (4 judges × 4 proposals)
into 4 calls (one per judge, scoring all proposals at once) cut latency and cost with
no quality loss — a reminder that the first working version of a multi-agent loop is
rarely the cheapest, and it's worth revisiting call structure once the logic is proven.

## What's next

The negotiation engine, admission gate, and metrics harness are deliberately generic —
see `README.md`'s "Core engine vs. reference app" table. They operate on generic
`DebateEvent`/`WorldBibleEntry` records and don't know anything about interactive
fiction specifically; only the specialist mandates, schema, and Twee export are
domain-specific. Next steps we'd want to take: a second reference app in a different
domain (co-writing, TTRPG worldbuilding, structured brainstorming) to prove the
framework claim, not just assert it; a Postgres-backed `WorldBible` implementation for
teams that outgrow SQLite's single-writer-per-file ceiling (same four-method interface
as `SQLiteWorldBible`/`TablestoreWorldBible`, so it's a config change, not a rewrite);
and real per-user auth/access control, since the current no-auth model is an honest fit
for self-hosting but not multi-tenant SaaS.

---

## Definitive Devpost requirements (verified live, 2026-07-08)

Fetched directly from `https://qwencloud-hackathon.devpost.com/` and
`https://qwencloud-hackathon.devpost.com/rules` on 2026-07-08. Summary for reference
while filling out the form:

- **Deadline:** the live hackathon page shows **Jul 20, 2026 @ 9:00pm UTC** ("12 more
  days to deadline" as of Jul 8). Note: the separate Official Rules sub-page still
  shows an older, stale "Submission Period: ...–Jul 9, 2026" date that has not been
  updated to reflect the extension — the main hackathon page's live countdown is the
  one to trust (and matches what the project owner already knew about the deadline
  push).
- **Submission must include:**
  1. A public code repository URL — must contain all source/assets/instructions needed
     for the project to be functional, must be public with a **detectable, visible
     open-source license file at the top of the repo page** (confirmed: this repo is
     public, MIT-licensed, GitHub auto-detects the license).
  2. **Proof of Alibaba Cloud Deployment** — explicitly defined as **"a link to a code
     file in their code repo that demonstrates use of Alibaba Cloud services and
     APIs"** (not a video). Point this at `backend/cloud_storage.py`.
  3. An architecture diagram (a clear visual of how Qwen Cloud connects to
     backend/database/frontend). The README's Mermaid diagram satisfies this.
  4. A text description of features/functionality.
  5. A demo video, **under 3 minutes** ("judges are not required to watch beyond three
     minutes"), showing the project functioning, **uploaded to and publicly visible
     on YouTube, Vimeo, or Youku** (see discrepancy note below), no third-party
     trademarks/copyrighted music without permission.
  6. Which track you're submitting to (Track 3: Agent Society).
  7. Optional: a public blog/social post link, for the separate Blog Post Prize only.
- **Eligibility:** open to individuals (age of majority in their residence), teams, and
  organizations, except residents of jurisdictions where QwenCloud registration isn't
  supported or that are subject to trade sanctions, and except anyone affiliated with
  the sponsor/administrator/judges. No specific team-size cap stated.
- **Judging:** Stage 1 pass/fail (fits theme, plausibly uses required
  APIs/SDKs); Stage 2 scored on Innovation & AI Creativity (30%), Technical Depth &
  Engineering (30%), Problem Value & Impact (25%), Presentation & Documentation (15%).

### Two corrections to the prior (2026-07-07, "fifth session") checklist note

The fifth session's Devpost note is **partially stale/inaccurate**, re-verified
directly against the live pages rather than trusted as-is:

1. **Video hosting platforms:** the fifth session said "YouTube/Vimeo/Facebook Video."
   The live pages actually disagree with *each other* — the main hackathon page's
   summary text says "YouTube, Vimeo, or Facebook Video," but the Official Rules
   (which explicitly state they prevail over other hackathon materials in case of
   conflict) say **"YouTube, Vimeo, or Youku."** Facebook Video is not mentioned in the
   Official Rules at all. **YouTube is the one platform both lists agree on** — use it
   and this discrepancy is moot.
2. **"Separate short recording as proof of Alibaba Cloud deployment":** this is **not
   accurate** per the current live rules text on either page. Both explicitly define
   the required proof as **a link to a code file in the repo**, not a video recording.
   A supplementary short recording doesn't hurt and one already exists locally
   (`demo_recordings/alibaba_cloud_deployment_proof.mp4`, 33.5s), but it is not what
   Devpost's form is actually asking for — the code-file link
   (`backend/cloud_storage.py`) is the real, required proof.

---

## Remaining human-only steps

- [ ] Upload `demo_recordings/video_assets_v5/stratum_demo_v5.mp4` to YouTube (public
  or unlisted-but-publicly-viewable) and paste the link into both this file's Links
  section and the Devpost submission form's video field.
- [ ] Paste the drafted text above (Inspiration / What it does / How we built it /
  Challenges / Accomplishments / What we learned / What's next / Built With) into the
  matching fields on the actual Devpost "Enter a Submission" form — field names/layout
  may differ slightly from this draft's headings; adapt as needed.
- [ ] Paste the repo URL, live demo URL, and the `backend/cloud_storage.py` GitHub
  permalink into their respective form fields.
- [ ] Select "Track 3: Agent Society" on the submission form.
- [ ] Decide whether to publish `BLOG_POST.md` publicly (e.g. Medium, dev.to, a
  personal blog, or a social post) to be eligible for the separate Blog Post Prize —
  optional, not required for the main track submission — and paste that URL if so.
- [ ] Fill in any account-specific fields Devpost requires (team member info if
  submitting as a team, any project short tagline character limit that differs from
  what's drafted here, etc.).
- [ ] Save as a draft on Devpost, review once more, then click Submit before the
  deadline (Jul 20, 2026 @ 9:00pm UTC — confirm this is still current on the actual
  form before finalizing, since one of the two rules pages checked here still shows a
  stale date).
