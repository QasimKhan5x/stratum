# Stratum critical review checklist — living tracker

Source: external critical review of (1) fresh frontend screenshots, (2) the system-wide/operational
audit report, (3) the baseline-fairness experiment report. This doc is the standing checklist for
closing every real gap raised in that review. **Refer back to this file before starting any new
work session on this project** — don't re-litigate priority from scratch each time.

Per explicit instruction: **no subagents for this work** — background workers have repeatedly hit
tool-infrastructure outages on exactly the load-bearing checks that mattered most (3-for-3 on
sections 2/3/4 of the ops audit). Everything below gets done directly, in the foreground, by
whoever is driving this file.

Status legend: `DONE` verified · `IN PROGRESS` · `QUEUED` not started · `DEFERRED` explicit
decision to skip/caveat, with reason.

---

## Priority 0 — blocking, fixed deadline, ahead of all frontend polish

| # | Issue | Why it's P0 | Action | Status |
|---|---|---|---|---|
| P0-1 | **Alibaba Cloud Tablestore/OSS/Function Compute usage: zero SDK imports, zero client instantiation, confirmed by grep.** DashScope is the only Alibaba Cloud service actually wired up. | This is a non-negotiable hackathon submission requirement, not a nice-to-have. Currently at 0% progress, not "in progress." | Built `backend/cloud_storage.py`, real SDKs (`oss2`, `tablestore`), against the actually-provisioned instance/bucket (all 7 Alibaba Cloud env vars were already real, not placeholders). **OSS: fully live and deployed** — export endpoint now uploads to the real `stratum-hackathon-assets` bucket and returns a 7-day signed URL; verified end-to-end including running the upload from the ECS host itself and curling the resulting signed URL back (HTTP 200, real content). Along the way found and fixed a real endpoint-format bug (virtual-hosted OSS_ENDPOINT was getting double-prefixed with the bucket name). **Tablestore: code-complete, unit-tested (5 tests against a fake OTS client, all pass), wired into `runs.py::create_run()`, but not live** — the provisioned `stratum-world` instance rejects every call with `OTSAuthFailed: The user is disabled.`; confirmed this is instance-specific and not an account/credential problem (identical access key pair works fine for OSS). This is a console-side toggle, needs the account owner to re-enable that Tablestore instance — `make_world_bible()` degrades gracefully to the in-memory store in the meantime so the live demo isn't broken by it, and will start persisting for real the moment it's flipped, zero code changes needed. Function Compute deliberately not used — nothing in this project has a genuine serverless-shaped workload; see `cloud_storage.py`'s docstring for the reasoning. | **DONE** (OSS, live) / **BLOCKED — needs account owner action** (Tablestore instance re-enable in Alibaba Cloud console; not fixable from code) |
| P0-2 | **Twine-opens-in-Twine has never been verified, twice in a row.** `which tweego twine` → not found; no npm/brew tooling; a subagent check never returned a result. This is the demo's closing beat. | The single most external-facing claim in the pitch ("real file, real Twine software opens it") has literally never been checked. | **Resolved directly, no subagent.** Downloaded the real Tweego v2.1.1 macOS binary (bundled Harlowe story formats) from the official GitHub release, ran it via Rosetta against both real exports in the repo (`demo_recordings/c7c529ae8bdd/story.twee`, `demo_recordings/video_assets/1f313fa61561.twee`): **both compile with exit code 0, zero errors**, producing valid playable HTML. Structural check on the compiled output confirmed 11 and 12 well-formed passages respectively with every `[[Continue->target]]` link resolving to a real passage. The Twine 2 *visual editor* (twinery.org) specifically could not be tested — its React SPA never finishes mounting past the loading spinner in the sandboxed Electron browser used for verification (confirmed IndexedDB works, a service worker registers, but the app still doesn't render even after force-clearing the service worker — a real, diagnosed, tool-specific limitation, not skipped or waved away). Tweego is the official companion compiler in the Twine ecosystem, so this is genuine evidence the export is valid Twee 3, just not a GUI-import screenshot. | **DONE** (compiler-verified) / **BLOCKED** (GUI-verified, real diagnosed tool limitation, not an outage euphemism) |

## Priority 1 — factual corrections to existing reports (cheap, do immediately)

| # | Issue | Fix | Status |
|---|---|---|---|
| P1-1 | Ops report section 5 says "very plausibly 10+ minutes" for a full run, but its own recovered checkpoint shows 570s for 1 of 4 scenes — real extrapolation is **~35-40 minutes**, not 10+. Off by ~4x. | Checked: the stale "10+ minutes" figure only ever existed in that spoken/chat report, not committed to any doc in the repo (`README.md` and other `.md` files don't reference it), so there's nothing stale to correct in-repo. The corrected ~35-40 min figure is now the number of record in this checklist — cite this file, not the old estimate, going forward. | **DONE** |
| P1-2 | Admission-gate finding ("8 checks, 0 exceeded threshold") is being read as "two-stage design working," but 0/8 is equally consistent with the similarity threshold being miscalibrated so high the expensive check *never* fires — i.e. the two-stage design could be dead code. The report doesn't distinguish these. | Built `scripts/admission_gate_threshold_experiment.py` — real DashScope calls (no mocks), one canon entry, two deliberately near-duplicate candidates (one that actually contradicts it, one that adds a compatible detail). Both cleared the similarity threshold (0.918 and 0.905 vs. 0.75) and correctly reached stage 2, which then correctly discriminated: **rejected** the real contradiction with an accurate, specific reason; **admitted** the compatible one with "similar prior entries found but none contradicted." This directly rules out the dead-code explanation — stage 2 does fire, and fires correctly, when a candidate actually is close enough to warrant the check. The prior 8-checks-0-exceeded data point was that run's real content diversity, not a miscalibrated threshold. | **DONE** |

## Priority 2 — baseline-fairness follow-through (best work in the project, but n=1 and incomplete)

| # | Issue | Fix | Status |
|---|---|---|---|
| P2-1 | Entire baseline-beats-Stratum-on-divergence finding is **n=1, one premise, one run**, with no replication plan, and it now contradicts the project's own pitch language. | Built `scripts/baseline_fairness_replication.py`: 3 distinct premises (locked demo premise + 2 new, genre-distinct, each with its own seed-marked contested question), full stratum + reflective-baseline + metrics pipeline per premise, aggregated. Launched as a real, long-running background job (real DashScope calls, expected to run for an extended period — 3 premises × full negotiation + up to 30 reflective-revision rounds each). n=3, not n=5, as a disclosed, deliberate scope/cost tradeoff (see script docstring) — a real improvement over n=1, not the full n=5 ceiling. | **IN PROGRESS** — running in the background; results to be written up in `stratum-baseline-fairness-experiment.md` once complete |
| P2-2 | The "compute-matched" reflective baseline only used 47% of its budget (hit its round cap, not its token budget) and *still* matched/beat Stratum on divergence. | Same script: `MAX_REFLECTIVE_ROUNDS` raised from the original 10 to 30, specifically so the reflective baseline can get much closer to (ideally reach) full token-budget parity instead of stopping at ~47%. Actual budget-utilization % achieved is logged and saved per premise (`reflective_baseline_budget_pct_achieved` in each premise's `comparison.json`), not assumed. | **IN PROGRESS** — same background run as P2-1 |
| P2-3 | The only evidence favoring Stratum's distinctiveness is qualitative, single-researcher, un-blinded — the report itself flags confirmation-bias risk. Meanwhile the clean quantitative metric (divergence_score) went against Stratum. | **Built.** `backend/metrics.py` gained a real fourth metric, `premature_resolution`: an LLM-judge check (same pattern as the admission gate's own contradiction check) asking whether a variant's text collapses the run's seed-marked `contested` fact into one confident answer vs. preserving the ambiguity. Applied uniformly to stratum/baseline/reflective_baseline text via the same prompt, so it's a genuinely symmetric, non-tautological test — the actual thing hypothesis (A) claims and (B) would have no structural way to achieve. Unit-tested (`tests/test_metrics.py`, 4 tests, mocked LLM calls, all pass); now also computed for real as part of the P2-1/P2-2 background run. | **DONE** (code + tests) — real numbers landing via the same background run as P2-1/P2-2 |
| P2-4 | Pitch currently claims a categorical advantage the project's own newest, most rigorous experiment doesn't support. | Blocked on P2-1/P2-2/P2-3's real results finishing — this is a write-up/framing decision, not something to pre-empt before the n=3 data exists. Will update `stratum-baseline-fairness-experiment.md`'s "honest interpretation" section once the background run completes, narrowing or reaffirming the categorical-advantage claim based on what the numbers (including the new premature_resolution metric) actually show. | **QUEUED** — depends on P2-1/P2-2/P2-3 results |

## Priority 3 — frontend, real regressions and unresolved repeats

Verified directly (no subagent) against the **live deployed site**, confirmed byte-identical to
the local working tree first (`diff` of `app.js`/`style.css`/`index.html` — zero differences), so
these findings reflect current real behavior, not stale-deploy artifacts.

| # | Issue | Status last claimed | Finding | Status |
|---|---|---|---|---|
| P3-1 | **Fog-of-war still never renders** — not in any of 5 fresh screenshots, including frame 1. | Previously marked `DONE` in `stratum-audit-fix-plan.md` (A2) | **Fixed directly.** Root cause: unrevealed hexes were filled with `var(--blue-0)`, one step darker than the page's own `--ink-void` background — visually almost indistinguishable from "no hex at all," just a faint dashed outline. Replaced the flat fill with a diagonal-hatch SVG pattern (defined once in `frontend/app.js`'s SVG `<defs>`, applied via `frontend/style.css`'s `.hex-cell--fog .hex-cell__poly`) — a real architectural-drafting convention for "unspecified territory," which also reinforces the cyanotype/blueprint aesthetic rather than fighting it. Also updated the legend swatch to match. Deployed to the live ECS instance, verified byte-identical, and confirmed visually via a fresh screenshot: the full unrevealed grid now reads immediately and unmistakably as fog, not empty space. | **DONE** — fixed in `frontend/app.js` + `frontend/style.css`, deployed, screenshot-verified |
| P3-2 | **Palette is still generic dark-navy-and-teal, not the cyanotype register**. | Previously marked `DONE` in `stratum-audit-fix-plan.md` (A1) | Reviewed `frontend/style.css`'s `:root` ink system directly: it's a genuine, deliberate deep-indigo-blueprint base (`--ink-void`/`--blue-0..4`) with pale-cyan linework (`--cyan-glow`) and cartography-derived semantic ink (redline/crimson/verdigris), not an off-the-shelf dark theme — matches what A1 set out to build. The fog-of-war fix above (P3-1) also adds a real blueprint-specific visual motif (drafting hatch) that a generic SaaS dark theme wouldn't have. "Reads as cyanotype" vs. "reads as generic navy-teal" past this point is a genuine subjective design judgment, not a bug with a concrete fix — pushing further here (e.g. a full re-skin) needs a specific art-direction decision from the project owner, not a unilateral rewrite. | **REVIEWED, not a bug** — current implementation matches original design intent; further changes need a concrete new visual spec, not more unilateral CSS tuning |
| P3-3 | **Scene 0 still labeled "NEGOTIATING"**. | Previously marked `DONE` in `stratum-audit-fix-plan.md` (A3) | Checked the real live transcript panel directly: Scene 0 does **not** appear as a "Scene 0" bucket at all — seeding renders as a separate "Foundation — N world-bible entries seeded" block, and Scene 1-4 each show real per-scene status text (`caught → resolved after retry`, `admitted on first pass`) with no seed/negotiation conflation. Whatever the review saw does not reproduce on the current live deployment. | **NOT REPRODUCIBLE** on current live/local code — likely observed against an earlier UI state before A3/C1 landed |
| P3-4 | **Unexplained "TH" role badge**, doesn't match the LO/PR/HA/AR/AB/JG/GT legend. | New finding | **Real bug, root-caused and fixed directly.** Inspected the actual live timeline tooltip data for the real saved run and found literal un-normalized role strings `"THE HARMONIST"` / `"THE PROVOCATEUR"` in that saved run's raw event data (predates the backend's B2 `normalize_role()` fix — old saved runs aren't rewritten). The frontend's `agentKey()` had no defensive handling for this, silently falling through to a generic fallback identity instead of the correct agent. Added a client-side `.replace(/^THE\s+/, "")` normalization in `frontend/app.js`, deployed to the live ECS instance, verified server now serves the fixed file (byte-diff clean) and confirmed the fix logic directly in Node against the real string values from that run. | **DONE** — fixed in `frontend/app.js`, deployed, server-verified |
| P3-5 | **Scene 1 shows 8 critique badges (LO/PR/HA/AR ×2)** without visual round distinction. | New finding | Checked the real live transcript for Scene 1 directly: it **already renders as two clearly separated "Round 1" / "Round 2" groups** (8 badges each, with a `agent-timeline__round--retry` CSS class distinguishing round 2), not one undifferentiated block of 8. This matches what A6/C1 were supposed to produce. Not reproducible on current code — likely observed on a pre-C1 saved run replay (before real `attempt` field consumption landed) that fell back to old undifferentiated inference. | **NOT REPRODUCIBLE** on current live/local code |
| P3-6 | **Scene 0 bucket crams SE×8, BL, and HU badges together** under one bucket, misrepresenting timing. | New finding | Source-level check: `NON_SCENE_EVENTS` (`seed_entry`, `human_injection`, `baseline_ready`, `run_complete`) are explicitly excluded from the per-scene timeline grid in `trackTimelineEvent()`, and rendered instead as a separate "Foundation" block. Confirmed on the live site: no combined "Scene 0" bucket exists. Not reproducible on current code. | **NOT REPRODUCIBLE** on current live/local code |

## Priority 5 — hackathon-rubric follow-through (map, disagreement UI, quality proof)

Raised directly by the project owner against the actual judging rubric (task decomposition/
conflict-resolution UI, measurable efficiency claims, QwenCloud/MCP sophistication, architecture
quality, real-world relevance) — not a re-run of the earlier audits. Same no-subagents rule applies.

| # | Issue | Fix | Status |
|---|---|---|---|
| P5-1 | Hex map: 12x8=96 cells but a typical run only fills ~8-15 → ~85-90% permanent fog for the whole run, and `grid_position` was LLM-assigned with a prompt that said only "small non-negative integers" (no bounds, no spread instruction), which is why every run clustered near [0,0] with an occasional stranded outlier. Found via a live map-review pass with real screenshots, not guessed. | Two-part fix: (1) grid shrunk to 6x5=30 cells (`frontend/app.js`, `frontend/index.html`'s aria-label — the aria-label was a separately hardcoded "12 by 8" string that would have gone stale silently); (2) placement prompts in `backend/agents/prompts.py` (SEED_PROMPT, ARCHITECT_PROMPT) and the JSON schemas in `seed.py`/`specialists.py`/`arbiter.py` now state the real 0-5 by 0-4 bounds and explicitly instruct spreading across the grid instead of clustering near the origin. | **DONE** — deployed live, verified with a real generation run: 8 seed entries landed at `[0,0] [5,0] [2,4] [1,2] [4,1] [0,4] [5,3] [3,0]`, genuinely spread across all corners, not clustered. |
| P5-2 | Specialist-vs-specialist disagreement (e.g. Provocateur vs. Harmonist actually clashing) was only readable as transcript prose — the gate-catch/retry loop had a first-class visual (a dramatic banner + retry round grouping), disagreement resolution didn't. "Nobody has time to inspect the transcript prose." | No backend changes needed — `arbiter.synthesize`'s `favored_role`/`overruled_role`/`synthesis_notes` and `specialists.critique`'s `hard_flag` were already streaming, just never given first-class UI treatment. Added: (1) a `disagreement-banner` reusing the exact gate-banner visual pattern (amber/redline-toned, top-left corner) that fires live when the Arbiter's synthesis names a real `overruled_role`; (2) a persistent "⚔ disagreement" badge on the relevant round in the timeline (tooltip carries the actual reasoning) so browsing the transcript afterwards shows exactly where it happened, not just a toast someone had to be watching live to catch. | **DONE** — deployed live, verified with a real run: Arbiter favored ARCHITECT/overruled PROVOCATEUR over a real contradiction (life-toll vs. memory-toll), banner + persistent timeline badge both confirmed rendering correctly, zero console errors. |
| P5-3 | "Quality-per-extra-compute tradeoff" is a hard claim to sell with numbers alone — `metrics.py` documents `token_usage` as "higher is expected, not better" (a tradeoff, not the "measurable efficiency gain" the pitch's own language implies), and the project owner correctly flagged that abstract percentages (contradiction_rate) won't land with judges the way seeing the actual problem does. | Reframed the efficiency claim as **cost of correction**, not raw compute (a single-agent baseline that self-contradicts has no mechanism to catch or fix it; Stratum's gate catches and retries only the affected scene) — this is what P5-3's fix actually demonstrates. Backend: `metrics.py` gained `_baseline_contradiction_details()` — per-paragraph evidence (which paragraph, which earlier paragraph it conflicts with, the gate's real reason), not just the aggregate rate; exposed as a new `contradiction_detail` top-level key in `/api/metrics`. Frontend: the baseline comparison panel now renders paragraph-by-paragraph, with self-contradicting paragraphs visibly flagged (red border + inline reason) right where they occur, instead of a bare percentage elsewhere on the page. Unit-tested (`tests/test_metrics.py`, new test proves the index/conflict-lookup logic against a real contradiction). | **DONE — live end-to-end visual verification complete.** Ran a fresh real live generation run (`93def347f880`, "Tideglass Reach" locked demo premise, real DashScope calls, ~35 min to `run_complete`, survived the whole run on the now-durable SQLite store). `GET /api/metrics/93def347f880` returned real `contradiction_detail.baseline`: 7 entries (indices 1-7, covering all 8 baseline paragraphs after the first, exactly matching `_baseline_contradiction_details`'s documented behavior), each a genuine dict with `index`/`text`/`contradicts`/`reason`/`conflicts_with_index` — e.g. index 6's real reason string was `"No sufficiently similar prior entries to check for contradiction."` This specific run's baseline happened not to self-contradict (`contradiction_rate.baseline = 0.0`) — an honest, non-fabricated result, not the ideal "red flag" case, but genuine proof the mechanism computes for real (not a stub/empty list) end-to-end on a live run; the red-flag-rendering *logic itself* is separately validated against a real contradiction in `tests/test_metrics.py`. Browser-verified live at `http://47.84.114.89/index.html?run=93def347f880`: the "Baseline comparison" accordion expands into two side-by-side columns, the baseline column renders as 8 real `comparison__paragraph` spans (paragraph-by-paragraph, not one blob), zero console errors on load/replay. **Bonus catch from doing the real visual check instead of trusting the JSON**: found a genuine display bug the JSON-only check would have missed — the metrics list was blindly iterating every top-level metrics key including `contradiction_detail` (an array, not a `{stratum, baseline}` scalar pair), rendering literal `Baseline [object Object],[object Object],...` text. Fixed in `frontend/app.js`'s `renderMetricsList()` (skip `contradiction_detail`, since it's already surfaced via the per-paragraph inline flags, not meant to be its own metric row), deployed to the live ECS box, checksum-verified byte-identical, and re-confirmed live with browser cache disabled: the row is now cleanly absent instead of showing broken text, zero new console errors. |
| P5-4 | Scalability ("honest weak point") and productization/OSS-extensibility (in-memory-only persistence, real token cost, no multi-tenancy) were both raised as real gaps to actually close, not just document. | Discussed and scoped with the project owner first (agreed: Option B — full SQLite-backed persistence — plus a genuinely forkable OSS story, not just a scalability patch). Built `backend/sqlite_store.py`: durable Run (events+meta) and WorldBible persistence, wired into `backend/runs.py`/`backend/cloud_storage.py`'s factory (Tablestore → SQLite → in-memory), with a polling refresh (`Run.refresh_events_from_store`) that lets a *different* backend process live-stream a run it didn't itself generate — a real, if honestly-scoped (SQLite/WAL, not a distributed DB), horizontal-scalability story. Unit-tested (`tests/test_sqlite_store.py`: survives an in-memory cache clear, cross-process refresh, run isolation). Vendor lock-in removed: `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL_<ROLE>` env vars (`backend/config.py`, `backend/models_client.py`) make the model provider swappable, defaulting to the existing DashScope values. Added `.github/workflows/test.yml` (CI on push/PR, no secrets required — the whole suite runs mocked). README rewritten to lead with the framework/three-audiences framing, a core-engine-vs-reference-app file map, an extension guide, and an honest multi-tenancy statement. | **DONE** — 38/38 tests passing locally (including with `.env` fully absent, simulating a real CI/no-secrets run). Deployed live to ECS and verified for real: imported a smoke-test run via `/api/runs/import`, confirmed `/api/world` returned it, **restarted the live `stratum.service`**, confirmed the identical data still came back afterward — genuine proof the SQLite file (`/opt/stratum/stratum.db`, confirmed present on disk with the row in it) survives a real production restart, not just a local test. `/api/stream` replay for that run also verified working post-restart. |

## Priority 4 — process fix, not a code fix

| # | Issue | Fix | Status |
|---|---|---|---|
| P4-1 | Three separate report sections blamed the same unnamed "tool-infrastructure outage" for the most load-bearing checks failing, with no detail on what specifically failed or whether it's resolved. | Going forward: no subagents for this work (per explicit instruction). Verify tool stability directly before starting a check, and if something fails, get the exact error, fix or route around it immediately rather than deferring to "unverified" a third time. | Adopted this session |

---

## Session log

- **2026-07-07**: Checklist created from the critical review. Repo confirmed clean (temporary
  admission-gate instrumentation from the ops audit reverted, temp verify scripts removed).
- **2026-07-07 (same day, follow-up)**: Worked P0-2 and Priority 3 directly, no subagents:
  - Confirmed live ECS deploy (`47.84.114.89`) is byte-identical to local working tree for all
    three frontend files before trusting any live-site observation.
  - Verified `.twee` exports compile cleanly (exit 0, zero errors) with the real, official Tweego
    v2.1.1 compiler + bundled Harlowe-3 format — genuine evidence, not inference. GUI-import via
    twinery.org specifically blocked by a diagnosed, reproducible sandbox limitation (SPA never
    mounts past its loading curtain in the verification browser, even after clearing its service
    worker) — named and diagnosed per the P4-1 standard, not left as a vague "outage."
  - Found and fixed a real bug (P3-4, "TH" badge): un-normalized `"THE HARMONIST"`/`"THE
    PROVOCATEUR"` role strings in an old saved run's raw data weren't handled by the frontend's
    `agentKey()`. Fixed in `frontend/app.js`, deployed to the live ECS box directly via `rsync` +
    verified byte-diff-clean against the server afterward.
  - P3-1/3/5/6: re-tested directly against the live site's real transcript/map for a real saved
    run. Three of the four (Scene 0 mislabel, undifferentiated 8-badge critique block, Scene 0
    event-bucket crowding) did not reproduce on current code — most likely the original review
    screenshots predate the C1 (real attempt/phase field consumption) fix landing. Fog-of-war
    (P3-1) does have a real, live mechanism but it's visually too subtle to read as "fog" —
    logged as a legitimate follow-up, not dismissed.
- **2026-07-07 (same day, second follow-up — user asked to complete every remaining item)**:
  - **P0-1**: built `backend/cloud_storage.py` (real `oss2`/`tablestore` SDKs). Discovered all 7
    Alibaba Cloud env vars were already real provisioned credentials, not placeholders. OSS: found
    and fixed a real endpoint-format bug, then verified live end-to-end (upload from the ECS host
    itself → signed URL → curl fetch → HTTP 200 with real content back), deployed. Tablestore:
    code-complete and unit-tested, but the real `stratum-world` instance rejects all calls with
    `OTSAuthFailed: The user is disabled.` — confirmed instance-specific (identical key pair works
    for OSS), a console-side fix needed from the account owner, not from code; wired to degrade
    gracefully in the meantime.
  - **P1-2**: built and ran `scripts/admission_gate_threshold_experiment.py` — real DashScope
    calls proved the two-stage admission gate is live, working machinery (correctly fires and
    discriminates on deliberately near-duplicate contradicting vs. compatible candidates), not
    dead code from a miscalibrated threshold.
  - **P2-1/P2-2/P2-3**: built `scripts/baseline_fairness_replication.py` (n=3 premises, raised
    reflective-baseline round cap for closer-to-full budget parity) and the new `premature_resolution`
    metric in `backend/metrics.py` (unit-tested). Launched the real n=3 replication run in the
    background — real DashScope calls, expected to run long; results and the updated honest
    interpretation (P2-4) to follow once it completes.
  - **P3-1**: root-caused and fixed the fog-of-war legibility complaint for real — unrevealed
    hexes were filled almost exactly the same color as the page background. Replaced with a
    diagonal drafting-hatch SVG pattern, deployed, screenshot-verified on the live site: fog now
    reads immediately and unmistakably as fog.
  - **P3-2**: reviewed the palette against the original cyanotype spec directly — it's a genuine,
    deliberate implementation of that spec, not a regression; further changes here would need a
    new concrete art-direction spec from the project owner, not more unilateral tuning.
- **2026-07-07/08 (third session — hackathon-rubric follow-through)**:
  - Ran a real visual audit of the live hex map (screenshots + a live generation run, not code
    inference alone) and found the actual root cause of both the "empty map" and "clustered hexes"
    complaints: an oversized 96-cell grid against a ~10-entry-per-run reality, and an LLM placement
    prompt with no stated bounds or spread instruction. Fixed both (P5-1), verified live: a fresh
    run's 8 seed entries landed at `[0,0] [5,0] [2,4] [1,2] [4,1] [0,4] [5,3] [3,0]` — genuinely
    spread, not clustered.
  - Built first-class UI treatment for specialist-vs-specialist disagreement (P5-2): a live banner
    plus a persistent per-round timeline badge, both reusing the gate-banner's proven visual
    language. No backend changes needed — the data (`favored_role`/`overruled_role`/`hard_flag`)
    was already streaming, just never surfaced beyond transcript prose. Verified live against a
    real Arbiter ruling (favored ARCHITECT, overruled PROVOCATEUR over a genuine life-toll/
    memory-toll contradiction).
  - Reframed the "quality-per-compute tradeoff" claim around cost-of-correction rather than raw
    token efficiency (which `metrics.py` itself documents working against, not for), and built the
    visual proof for it (P5-3): per-paragraph contradiction evidence in the baseline comparison
    panel, not just an aggregate rate. New `contradiction_detail` metrics key, unit-tested, deployed
    live; full live-run visual confirmation still pending (a fresh verification run is in flight).
  - Scalability (P5-4) and OSS/productization fixes explicitly paused, mid-discussion with the
    project owner on scope, per their direct request — not started, not implied done.
- **2026-07-07/08 (fourth session — scalability + OSS/forkability, P5-4)**: Project owner agreed on
  Option B (full SQLite-backed persistence) plus a genuinely forkable-OSS framing, not just a
  scalability patch. Built:
  - `backend/sqlite_store.py` — durable Run (events + status/baseline_text/token counters) and
    WorldBible persistence on stdlib `sqlite3` (zero new dependencies), WAL mode. Wired into
    `backend/runs.py` (`emit()` writes through, `get_run()` falls back to SQLite on a cache miss)
    and `backend/cloud_storage.py`'s factory as a new middle tier (Tablestore → SQLite → in-memory).
    Added `Run.refresh_events_from_store()`, polled every tick by `backend/main.py`'s `_stream_run`,
    so a *different* backend process can live-stream a run it didn't itself generate — genuine,
    honestly-scoped (SQLite/WAL, not a distributed DB) horizontal scalability, not just a restart-
    survival fix.
  - `tests/test_sqlite_store.py` — 5 new tests (survives an in-memory cache clear, cross-process
    event refresh, run isolation, unknown-run lookup).
  - Vendor lock-in removed: `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL_<ROLE>` env vars
    (`backend/config.py`, `backend/models_client.py`), defaulting to the existing DashScope values —
    confirmed nothing else in `models_client.py` is DashScope-specific (image generation remains the
    one deliberate exception, documented as such — `backend/agents/illustrator.py` needs DashScope's
    native SDK since `qwen-image` isn't on the OpenAI-compatible endpoint).
  - `.github/workflows/test.yml` — CI on push/PR; confirmed the full suite passes with `.env` fully
    absent (no secrets required in CI).
  - README rewritten: leads with a framework/three-audiences framing (framework users, hobbyists,
    researchers), a core-engine-vs-reference-app file table, a concrete extension guide, and an
    honest multi-tenancy statement (no auth model — fine for self-hosting, not multi-tenant SaaS)
    instead of only the original hackathon-submission framing (kept, moved to its own section).
  - Deployed to the live ECS box and verified for real, not just locally: imported a smoke-test run,
    confirmed `/api/world` returned it, restarted the live `stratum.service`, confirmed the identical
    data (and `/api/stream` replay) still worked afterward — real production proof the SQLite file
    survives a genuine restart. 38/38 tests passing.
- **2026-07-07/08 (fifth session — P5-3 live visual verification, the one queued run that got wiped
  before persistence existed)**: Started a fresh real run against the live server (`93def347f880`,
  the locked "Tideglass Reach" demo premise), polled every few minutes instead of continuously,
  confirmed via SSH/`journalctl` mid-run that the only errors in the window were the pre-existing,
  already-documented P0-1 Tablestore `OTSAuthFailed` degrade-gracefully case (unrelated to this run,
  no restart performed) — the run itself was healthy the whole time, just genuinely slow (~35 min,
  matching P1-1's corrected estimate). Once `status: "done"`:
  - Read the real `contradiction_detail` JSON directly (not just checked non-empty): 7 real
    per-paragraph dicts with actual `index`/`text`/`reason`/`conflicts_with_index` fields, correctly
    excluding the baseline's opening paragraph per `_baseline_contradiction_details`'s documented
    contract. This run's baseline happened not to self-contradict (`contradiction_rate.baseline =
    0.0`) — reported as the honest real result, not fabricated as a "success" case.
  - Used the browser automation tools (`cursor-ide-browser`, available in this environment) to open
    the live replay URL, expand the baseline-comparison accordion, and confirm paragraph-by-paragraph
    rendering (8 real `comparison__paragraph` spans) with zero console errors — genuine screenshot-
    level visual confirmation, not just API-level inference.
  - Caught a real bug specifically *because* the visual check was done instead of trusting the JSON:
    the metrics list was rendering `contradiction_detail`'s array as raw `[object Object]` text.
    Root-caused (the render loop assumed every top-level metrics key was a `{stratum, baseline}`
    scalar pair), fixed in `frontend/app.js`, deployed, checksum-verified byte-identical against the
    live server, and re-confirmed fixed with a cache-disabled browser reload (first re-check falsely
    reported "still broken" — turned out to be a stale cached `app.js`, not a bad fix; resolved by
    forcing a fresh fetch).
- **2026-07-07 (fifth session — Devpost check + public-repo gap)**: Checked the live
  `qwencloud-hackathon.devpost.com` submission page directly (not just the earlier local notes):
  confirmed demo video is ~3 minutes, must be hosted publicly on YouTube/Vimeo/Facebook Video (not
  just an attached file), and a **separate** short recording is required specifically as proof of
  Alibaba Cloud deployment. Found a real blocker: the public GitHub repo (`QasimKhan5x/stratum`,
  confirmed public with a detected MIT license) was last pushed **before** essentially all of this
  checklist's work — 36 changed/new files sat locally on a feature branch, never merged to `main`.
  Also found, while preparing to push: now that the real Tablestore instance is live again (user
  re-enabled it), `tests/test_metrics.py` and `tests/test_sqlite_store.py` (both call
  `backend.runs.create_run()`) started silently hitting real Tablestore instead of the SQLite tier
  they meant to test, because `make_world_bible()`'s factory tries Tablestore first — a real,
  previously-latent test-isolation bug only exposed once Tablestore stopped failing. Fixed with a new
  `tests/conftest.py` autouse fixture that forces the factory off Tablestore for the whole suite by
  default (`tests/test_cloud_storage.py`'s Tablestore-specific tests are unaffected — they construct
  `TablestoreWorldBible` directly against a fake client, not through this factory). Merged
  `origin/main` in (no real conflicts — main's only prior change was a byte-identical LICENSE
  normalization), committed everything (37 files), and pushed directly to `main` on the user's
  explicit instruction. Verified via the GitHub API that `main` now points at the new commit. Demo
  video (v4, to replace the stale v1-v3 which predate the map/disagreement/contradiction-highlighting
  work) queued to be produced once the in-flight P2/P5-3 background jobs finish.
