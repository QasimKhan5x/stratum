# Stratum — Baseline Fairness Experiment

## The question this answers

Stratum's efficiency-gain claim (contradiction rate, creative-divergence
score, provenance depth vs. a single-shot baseline — see `backend/metrics.py`
and `backend/agents/baseline.py`) compares negotiated multi-agent generation
(~13 model calls per scene) against the *weakest possible* single-agent
baseline: exactly 1 call, no scaffolding, no self-review. That comparison
cannot distinguish two different hypotheses:

- **(A) Categorical:** structured multi-agent negotiation catches
  contradictions and avoids generic tropes in a way a single agent cannot
  achieve even in principle.
- **(B) Just compute:** any approach given ~13x more compute/tokens
  produces a better result, and negotiation happens to be one way to spend
  that budget — a single agent given an equivalent budget (more
  self-critique/revision passes) might close most of the gap.

The original baseline has no compute-matched variant, so it cannot tell (A)
from (B). This experiment builds one and measures it for real.

## What was built

- `backend/agents/baseline_reflective.py` — `generate_reflective_baseline`.
  Same "arbiter" role (qwen3.7-max), same `BASELINE_PROMPT`, same premise,
  and the *identical* initial call as `generate_baseline` — the only
  difference is what happens after the first draft. From there, it runs
  self-critique→revise rounds: one agent, talking to itself, in the format
  `CRITIQUE:` / `REVISED DRAFT:`, with `thinking=True` enabled on each
  revision call for extra per-call reasoning compute (the same lever the
  real pipeline's seed/arbiter steps use). It stops once its own tracked
  token spend reaches a caller-supplied `token_budget`, or after
  `max_rounds` (a safety cap against runaway cost), whichever comes first.
  It does not import or call anything in `backend/negotiation.py` — no
  specialists, no judges, no arbiter-synthesizes-a-panel machinery. One
  agent, more self-directed compute, nothing else.
- `backend/metrics.py` — `compute_comparison` gained two **optional**
  parameters, `reflective_baseline_text` and `reflective_baseline_tokens`,
  both defaulting to values that reproduce the exact old behavior
  (`None` / `0`). No existing call site (including `/api/metrics`) needed
  to change, and none did. When provided, a third `"reflective_baseline"`
  column is added to each of the four metrics, computed by the identical
  methodology as the `"baseline"` column (same admission-gate reuse for
  contradiction_rate, same generic-corpus centroid for divergence_score).
- `scripts/reflective_baseline_experiment.py` — standalone. Does not import
  or modify `backend/orchestrator.py`'s behavior; nothing about the live
  run path changed. Runs the real negotiated pipeline once, reads its real
  `total_tokens`, generates the calibrated reflective baseline, computes
  all three variants, and saves raw text + a JSON report under
  `experiments/reflective_baseline_experiment/`.

`backend/orchestrator.py`, `backend/agents/baseline.py`, and the existing
`stratum`/`baseline` comparison were not touched.

## Exact methodology used

- **Premise:** the locked demo premise verbatim from
  `stratum-demo-premise.md` — "Tideglass Reach" (drowned city, Tideglass
  Guild vs. Hush Choir, the contested Drowned Bell).
- **Stratum run:** the real negotiated pipeline (`run_generation`), called
  directly (not through the live API) with `scene_count=2` — reduced from
  the demo's default of 4 purely to bound real API spend/wall-clock time
  for this one-off validation. This is a disclosed scope reduction, not a
  hidden one: with only 2 scenes, this run is smaller than a full demo run,
  and its own numbers (below) should not be read as "the" official demo
  metrics — see the Limitations section.
- **Naive baseline:** generated concurrently by the same run, via the
  existing, untouched `generate_baseline` — 1 call, no scaffolding.
- **Reflective baseline:** calibrated against the Stratum run's own real
  `total_tokens` (174,771) as the target budget, with `max_rounds=10` as
  the safety cap.
- **Metrics:** `backend.metrics.compute_comparison`, unmodified methodology
  — contradiction_rate via the real admission gate (live gate events for
  Stratum, the gate re-applied to a baseline's own paragraphs for both
  baselines), divergence_score via cosine distance from a fixed generic
  genre corpus, provenance_depth, token_usage.
- **Runs:** one real DashScope run per variant, one premise. Not repeated —
  see Limitations for what that does and doesn't support.

## Raw numbers

| Metric | Stratum | Naive baseline | Reflective baseline |
|---|---|---|---|
| contradiction_rate | 0.0 | 0.0 | 0.0 |
| divergence_score | 0.404 | 0.3959 | **0.4784** |
| provenance_depth | 1.0 | 0.0 | 0.0 |
| token_usage (tokens) | 174,771 | 2,930 | 81,707 |
| total model calls | 27 | 1 | 11 (1 draft + 10 revision rounds) |

Raw generated text for all three variants, and the full JSON report, are
saved under `experiments/reflective_baseline_experiment/` (`stratum_canon.txt`,
`naive_baseline.txt`, `reflective_baseline.txt`, `comparison.json`).

## Honest interpretation

**Divergence score — this is the metric that actually moved, and it moved
against the categorical-gap claim.** The reflective baseline scored
*higher* than Stratum (0.4784 vs. 0.404), and the naive baseline was
already close to Stratum (0.3959 vs. 0.404). On this one real run, on this
one metric, giving a single agent more self-directed compute did not just
close the gap — it exceeded it. That's a real, uncomfortable number for the
"negotiation produces a categorical creative-divergence advantage" version
of Stratum's pitch, and it is being reported exactly as measured, not
softened.

**Contradiction rate — inconclusive, and for a specific, disclosed reason.**
All three variants scored 0.0. For Stratum, that means the live admission
gate rejected nothing in this particular 2-scene run — the demo's
flagship "gate catches a premature resolution" moment did not occur here
(contrast with the previously recorded 4-scene demo run, where
`contradiction_rate` for stratum was 0.2). For both baselines, 0.0 means
neither baseline's own text logically contradicted itself when checked
paragraph-against-paragraph by the same gate. This metric simply didn't
discriminate anything on this run — not evidence for either hypothesis,
just a non-result that a run with more scenes (and more chances for the
gate to actually fire) might resolve differently.

There is also a real, separate qualitative observation that this specific
metric misses entirely: `_baseline_contradiction_rate` checks whether a
baseline's *own later paragraphs* contradict its own earlier ones — it does
not check whether a baseline **prematurely and definitively resolves a
deliberately unresolved ambiguity**, which is the actual failure mode the
demo's Lorekeeper/admission-gate mechanism is built around. Reading the raw
text: the naive baseline ends on a genuine, unresolved cliffhanger (the
Bell tone turns out to be something "massive" emerging from the cathedral,
never explained). The reflective baseline, despite ten rounds of
self-critique, still fully and definitively resolves the Bell mystery into
one specific literal answer ("The bell tone isn't a hazard or a hoax; it's
a structural release valve") — exactly the move a Lorekeeper-style citation
check exists to catch and block. No quantitative metric here captured that
difference; it only shows up from actually reading the output. That's a
real, if anecdotal (n=1, one premise, one run), point in favor of hypothesis
(A) — self-critique-that-can't-see-outside-its-own-single-context still
converges to certainty on a fact that was deliberately supposed to stay
contested, while a structurally separate specialist whose entire mandate is
"defend contested ambiguity and cite the entry ID" has a mechanism the
reflective baseline simply doesn't.

**Provenance depth — this metric doesn't actually test the hypothesis at
all.** It measures whether output has a real, structured, per-entry
attribution chain. By construction, no single-agent process — however much
compute it gets — produces that; it's an architectural property of running
multiple attributed synthesis steps, not a capability a bigger compute
budget could ever buy a single flat text blob. Its 1.0/0.0/0.0 split is real
but tautological, and shouldn't be read as evidence for (A) or against (B).

**Net read:** this single-run, single-premise experiment does not support
a clean "categorical gap" story. On the one metric that actually
discriminated (divergence_score), a compute-matched single agent matched
and then exceeded Stratum. Contradiction_rate was a non-result here. The
one piece of evidence that does point toward something negotiation-specific
is qualitative and anecdotal, not one of the three numbers Stratum's own
metrics track: a single self-critiquing agent, even given a comparable
compute budget, still collapsed a deliberately-contested fact into a
confident answer, which the specific "Lorekeeper must cite an entry ID"
mechanism is designed to prevent. That's a real, but narrower and less
sweeping, claim than "no single agent can do this" — and it's not what the
divergence_score number shows.

## Limitations, disclosed plainly

- **One run, one premise.** This is exactly the kind of result that could
  flip on a re-roll given LLM stochasticity, or on a richer premise/longer
  run. Treat every number above as one data point, not a settled result.
- **Reflective baseline did not reach full budget parity.** It hit the
  `max_rounds=10` safety cap at 81,707 tokens — about 47% of Stratum's
  174,771-token run, not the full amount. It's the same order of magnitude
  (10⁴–10⁵ tokens, ~28x the naive baseline's spend vs. Stratum's ~60x), but
  it is not an exact match, and this was a deliberate, disclosed
  cost/safety tradeoff, not an attempt to under-power the comparison. If
  anything, this makes the divergence_score result *more* notable — the
  reflective baseline beat Stratum on that metric while spending less than
  half its token budget, not more.
- **Stratum's own run here used `scene_count=2`, not the demo default of
  4.** Also a disclosed cost/time tradeoff. Its raw numbers here (e.g.
  contradiction_rate=0.0) are specific to this smaller run and shouldn't be
  read as replacing the previously recorded demo run's own metrics.
- **contradiction_rate's methodology doesn't cover "premature resolution of
  a contested fact,"** only direct self-contradiction between paragraphs.
  The most demo-relevant failure mode Stratum claims to catch isn't
  actually instrumented by this specific number — see the qualitative
  observation above. A real upgrade path here would be a fourth metric
  specifically checking whether a baseline resolves a seed-marked
  `contested` fact without ambiguity, reusing the same seed step against
  both baselines.
- **No held-out judge.** "Generic tropes" and "premature resolution" were
  read by the person running this experiment, not scored blind by a
  separate model or human. That's a real source of confirmation-bias risk
  this experiment doesn't control for.

## Where this leaves the project's efficiency-gain claim

The existing `stratum` vs. `baseline` comparison in `backend/metrics.py`
(unmodified by this work) still stands as-is for the demo — it's honest
about comparing against the *weakest* baseline, and the demo script never
claimed otherwise. What this experiment adds is a check on the *stronger*,
unstated version of that claim ("no amount of single-agent compute gets you
there") — and on the one real run performed, that stronger version does
not hold up cleanly. The honest framing for anything built on top of this
result: Stratum's mechanism produces a *specific, narrower* advantage (an
explicit, citable channel for defending a deliberately unresolved fact
against premature resolution) that showed up qualitatively but not in the
three tracked numbers, rather than a wholesale, every-metric categorical
advantage over any equal-budget alternative. That is a real difference from
this project's current pitch language, and it should be represented as
such rather than glossed over.
