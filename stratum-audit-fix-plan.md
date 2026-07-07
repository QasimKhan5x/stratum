# Stratum audit fix plan — live tracker

Working document for closing every hole raised across (a) the external UI/demo-readiness
critique and (b) the technical backend/AI audit. Updated in place as work lands. Deadline:
July 9.

Status legend: `DONE` verified · `IN PROGRESS` worker running · `QUEUED` not started ·
`DEFERRED` explicit decision to skip/caveat, with reason.

---

## Part A — Frontend / demo-readiness critique

| # | Issue | Fix | Status | Evidence |
|---|---|---|---|---|
| A1 | UI drifted into generic dark SaaS dashboard, not the locked indigo cyanotype aesthetic | Full rewrite of `index.html`/`style.css` to blueprint/cyanotype theme (deep indigo base, pale-cyan linework, redline/crimson/verdigris semantic ink) | **DONE** | Screenshots in `/tmp/stratum_screenshots/` |
| A2 | Fixed 12×8 hex grid + real fog-of-war missing | Full-bleed grid renders complete on load; unrevealed hexes dark/dashed, revealed ones pulse+flash in | **DONE** | `d-full-grid-fog.png` |
| A3 | Seed step (scene 0) incorrectly shows Arbiter badge / per-scene template | Scene 0 renders as "Foundation," SeedAgent-only, no Arbiter/Gate badge (matches backend — Arbiter is never called during seeding) | **DONE** | `a-seed-step.png` |
| A4 | Tiny ambiguous 2-letter role initials | Glyph-based SVG-sprite avatars, no 2-letter pills | **DONE** | all screenshots |
| A5 | 16 raw `judge_score` events rendered as 16 separate badges (clutter, misleading — real per-call cardinality is 4) | Frontend groups into 4 dimension-verdict badges. Backend fix B5 (below) also collapses emission at the source so this isn't just a UI patch over noisy data. | **DONE** (frontend) / **IN PROGRESS** (backend source fix) | verified 20 real groups across 5 attempts in demo replay |
| A6 | Gate-catch visually indistinguishable from a clean admit | Round 1 / Round 2 grouping with redline tint + "caught → resolved after retry" vs "admitted on first pass" labels | **DONE** | `c-gate-catch.png`, `c2-gate-catch-resolved-timeline.png` |
| A7 | Raw internal entry-id hashes leaking into user-facing text | `describeEntry()` helper scrubs to human summaries everywhere; backend fix B6 adds real `summary` data to the synthesis event so this has something real to show instead of a fallback string | **DONE** (frontend) / **IN PROGRESS** (backend data support) | scanned rendered page, zero raw hash patterns found |
| A8 | Debug/pacing URL params (`pace`, `slow_from`, etc.) visible in address bar during demo | Captured into memory on load, then stripped from the URL | **DONE** | verified address bar shows only `?run=...` post-load |
| A9 | Mobile horizontal overflow | Fixed `.stage__map`/`.dossier` grid track sizing (`min-width: 0`), defensive `overflow-x: hidden` on body | **DONE** | `e-mobile-390-fixed.png` |
| A10 | Core features (constraint injection, `.twee` export, baseline comparison) not visually surfaced | Confirmed present: premise form, constraint injection, export button, baseline `<details>` panel, world-bible ledger | **DONE** | covered by Playwright smoke test, 2/2 passing |
| A11 | Accessibility gaps found during QA (aria-labels on non-interactive elements, contrast failures) | Fixed roles on hex/timeline elements; nudged `--paper-faint`/`--redline` to pass 4.5:1 AA | **DONE** | axe scan on fully-loaded run: 0 critical/serious violations |
| A12 | "Open Twine website" button pointed at dead domain `twinejs.org` | Changed to real domain `twinery.org` | **DONE** | `frontend/app.js`, fixed directly |
| A13 | Hex label overlap on dense clusters | Round-number label moved off dead-center into its own corner backdrop chip (`hex-cell__label-backdrop`), so it stays legible over both flat fill and busy scene-illustration images, including in tightly-packed clusters | **DONE** — visually verified via screenshot |
| A14 | Demo video may have captured an inconsistent mid-redesign UI state (recorded concurrently with the redesign rewrite) | Re-record once A1–A13 + all Part B fixes are stable | **QUEUED** | see Part C |

## Part C1 detail — frontend now consumes real attempt/phase data

`frontend/app.js` previously inferred retry rounds purely by counting synthesis/admission event
pairs (no backend signal existed yet). Now that B1/B4 landed:
- Every DebateEvent's real `attempt`/`phase` fields are read from the wire and combined with the
  existing local inference via `combineAttempt()` — new runs get authoritative backend-tagged
  attempts; old saved replays (which default to `attempt: 1` for everything) fall back to the
  original inference, so historical demo recordings still show their real retry structure.
- The judge_score handler now accepts **both** wire shapes: the new grouped
  `{scores: [...16 items]}` (backend fix B5) and the old one-event-per-score shape used by every
  saved replay from before that fix — normalized into the same per-item loop either way.
- Verified against the real reimported `c7c529ae8bdd` saved run: Playwright smoke test passes,
  judge-score grouping still renders as "N verdict · 4/4 scored" badges, and Scene 1 correctly
  shows "caught → resolved after retry" with Round 1/Round 2 grouping.

## Part B — Backend / AI technical audit

All confirmed with real data analysis (saved event logs, code tracing), not guessed.

| # | Issue | Fix | Status |
|---|---|---|---|
| B1 | No `attempt`/retry counter on `DebateEvent` — root cause of "gate-catch looks identical to a clean pass" at the data level (QUARE traceability gap) | Added `attempt: int = 1` to schema; `negotiation.py`'s `emit()` now takes and propagates it from the retry loop | **DONE** — verified: `test_attempt_number_increments_across_retries` |
| B2 | Role name strings not normalized (`"The Harmonist"`, `"HARMONIST"` vs canonical `"Harmonist"`) causing UI/matching bugs | `backend/agent_roles.py`'s `normalize_role()`, wired into specialists/arbiter/judges | **DONE** — verified: `test_normalize_role` |
| B3 | Saved demo run `a3a1318598eb` has ~50% duplicate events (339 total / 170 unique) | **Real root cause found**: `Run.emit()` pushed to both `run.events` (list) and `run.queue` (asyncio.Queue). If nobody watched the run live, the queue held every event un-drained; a subscriber connecting after the fact replayed full history from `run.events` *and then* drained the still-full queue, yielding every event twice. Also a latent second bug: two concurrent subscribers would race on the same shared queue and split events non-deterministically. Fix: removed the queue entirely; `backend.main._stream_run` now polls `run.events` by index — single source of truth, safe for any number of readers. | **DONE** — verified: `test_stream_run_does_not_double_yield_events_for_unwatched_finished_run`; old saved runs (incl. the corrupted `a3a1318598eb`) still parse fine (bug was in the *live streaming/save path*, not the saved JSON itself, so no data regeneration needed — new saves won't reproduce it) |
| B4 | Round/scene 0 conflates unrelated `SEED` and `BASELINE` events (both use `round=0, scene=0`) | Added `phase: "seed"\|"negotiation"\|"baseline"` field to `DebateEvent`; set explicitly at both emit sites in `orchestrator.py` | **DONE** |
| B5 | 16 discrete `judge_score` stream events per scene (4 dims × 4 proposals) — real cardinality is 4 batched calls; wasn't a deliberate legibility decision | Collapsed to one `judge_score` event per attempt carrying all 16 scores as a structured list — no data lost | **DONE** — verified: `test_judge_score_collapsed_into_one_event_per_attempt` |
| B6 | Rejected candidate's content (`summary`) never captured in the event stream — only an opaque `entry_id` hash survives if never admitted | Added `summary` to the `synthesis` event payload | **DONE** — verified: `test_synthesis_event_carries_candidate_summary` |
| B7 | `divergence_score` reference corpus is 5 hand-written examples, narrow to one genre trope | Expanded to 20 examples spanning 6 distinct IF tropes (flooded-city, haunted-house, space-station-mystery, post-apocalyptic-settlement, mystery/heist, locked-room) | **DONE** |
| B8 | `provenance_depth` is a trivial binary flag dressed as "depth" — not honest about what it measures | Went further than a rename: now a genuine per-entry fraction — for each admitted, negotiated canon entry, checks whether its *winning attempt's* critique stage actually cited a real prior world-bible entry (using the citation data already in the event stream), rather than a flat 1.0 the moment any canon exists. Key name kept (`provenance_depth`) since it's now honestly earned, no frontend change needed. | **DONE** — verified: `test_provenance_depth_is_graduated_not_a_flat_flag` |
| B9 | No equal-compute-budget baseline tested — can't distinguish "categorical capability gap" from "just more tokens spent" | Isolated "reflective baseline" (single agent + self-critique/revision rounds, matched token budget) built as `backend/agents/baseline_reflective.py` + standalone `scripts/reflective_baseline_experiment.py`; wired as an optional 3rd column in `compute_comparison`, fully backward compatible | **DONE** — real experiment run against DashScope, see `stratum-baseline-fairness-experiment.md` |

**B9's honest result (real numbers, one run, 2 scenes, "Tideglass Reach" premise):**

| Metric | Stratum | Naive baseline | Reflective baseline |
|---|---|---|---|
| contradiction_rate | 0.0 | 0.0 | 0.0 (non-result — gate never fired in this smaller run) |
| divergence_score | 0.404 | 0.396 | **0.478** (reflective baseline matched *and exceeded* Stratum) |
| provenance_depth | 1.0 | 0.0 | 0.0 |
| tokens | 174,771 | 2,930 | 81,707 (hit the 10-round safety cap at ~47% of Stratum's budget — not full parity) |

This does **not** support a clean "categorical gap" story — on the one metric that actually
discriminated, the equal(ish)-budget single agent matched or beat Stratum. The one real point
still favoring negotiation is qualitative, not a tracked number: the reflective baseline still
confidently resolved the deliberately-contested "Bell" mystery into one definitive answer after
ten self-critique rounds — exactly the premature-resolution failure mode the
Lorekeeper/admission-gate exists to catch — while the naive baseline left it genuinely open.
That's a narrower, disclosed-as-anecdotal (n=1) claim, not "no single agent can do this ever."
Full methodology and limitations are in `stratum-baseline-fairness-experiment.md` — this finding
is reported as found, not softened, per this project's own stated values.

All of B1–B9 verified together: `.venv/bin/python -m pytest tests/ -q` → **23 passed**, both real saved demo runs (`c7c529ae8bdd`, `a3a1318598eb`) still parse cleanly under the new schema fields, and B9's real experiment output is on disk in `experiments/reflective_baseline_experiment/`.

Note on delegation: after two subagents assigned to this work stalled on repeated tool/execution-environment outages, B1–B8 above were implemented directly rather than via a third delegation attempt. B9 is running as a plain background shell process (not an agent) for the same reason — a long real-API task shouldn't depend on a fragile agent loop when it's just "run this already-correct script."

## Part C — Final polish (depends on A + B landing)

| # | Item | Status |
|---|---|---|
| C1 | Follow-up frontend pass to consume new `attempt`/`phase` fields directly (B1/B4) instead of inferring rounds from event-pair counts | **QUEUED**, blocked on B1/B4 |
| C2 | Re-record demo video against fully-stable, fully-fixed UI + backend | **QUEUED**, blocked on A + B |
| C3 | Final repo cleanup, README pass, public-visibility check | **DONE** — see details below |

**C3 details:**
- `.gitignore`: added `test-results/` (Playwright run metadata) and `experiments/` (one-off
  research script output) — both regenerable, neither meant for git history, matching the
  existing `demo_recordings/` pattern.
- `README.md`: fixed a real overclaim — the "On efficiency gain" section previously said a single
  agent has "no mechanism to buy [the quality gain] at any price, however many tokens it's
  given." B9's real experiment directly contradicts the strong version of that claim. Rewrote it
  to state the honest, narrower finding and linked `stratum-baseline-fairness-experiment.md`.
  Added that doc and `stratum-audit-fix-plan.md` to "Further reading" and the evidence checklist.
- GitHub repo confirmed public (`gh repo view`): `QasimKhan5x/stratum`, visibility `PUBLIC`.
- **Critical finding, fixed**: the live ECS demo (`http://47.84.114.89`) was running severely
  stale code — a pre-redesign 370-line `app.js` and a backend venv that had **never actually had
  the `mcp` package installed** despite it being in `requirements.txt` since the MCP integration
  was added (the running process just hadn't been restarted since before that point, so it never
  hit the import). Synced current `backend/`, `frontend/`, `requirements.txt` via `rsync`,
  installed the missing `mcp` (and its transitive deps) in the remote venv, restarted
  `stratum.service`, and verified: `/health` 200, live `app.js` byte-identical to local, `/api/models`
  returns real DashScope models, `backend/mcp_world_bible_server.py` present. The live demo now
  actually reflects everything shipped today, including the MCP integration for the first time.

---

## Operating rule for this plan

If any worker executing a piece of this plan reports a tool/execution-environment outage
mid-task, it must be relaunched with a faithful continuation of exactly what it was doing —
never left half-done, never silently dropped. Re-verify on-disk state before resuming (don't
trust an outage-interrupted worker's self-report of what saved vs. didn't) — the way this was
handled for the frontend redesign worker (verified `app.js` was still stale via `git status`
before resuming it) is the pattern to repeat.
