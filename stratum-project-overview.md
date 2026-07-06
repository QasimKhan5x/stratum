# Stratum — Project Overview

## What Stratum is

Stratum is a multi-agent system that writes real, playable Twine stories
through adversarial negotiation. Four specialist AI agents with genuinely
conflicting creative mandates argue every scene into existence before it
becomes canon. The negotiation is not a formality — it is the generative
mechanism. Nothing is added to the world until it has been proposed,
challenged, revised under objection, and ruled on by an Arbiter, then
checked against everything already agreed for internal consistency.

The output is not locked inside a custom app. Every admitted scene
compiles to valid Twee 3 notation — the source format of Twine, the most
widely used open-source interactive fiction tool (2.8k+ GitHub stars,
active development, large hobbyist and game-jam community). At any point
during or after generation, the world can be exported as a `.twee` source
file (editable in the real Twine desktop app) or compiled via the
open-source Tweego compiler into a standalone playable `.html` file with
zero dependencies. The negotiation history — which agent proposed what,
what was overruled, what round it happened in — is encoded as native
Twine passage tags with assigned colors, using the `tag-colors` field
Twine's own format already supports. Nothing about this provenance layer
is custom UI; opening the exported file in real Twine software shows the
full argument history natively.

While a world generates, a live cyanotype-style map renders the
negotiation happening in real time — hexes lit white as scenes are
admitted, amber where consensus hasn't been reached, ghost outlines where
a losing proposal was overruled. This map is the **spectator view**: how
you watch the argument happen. The Twine file is the **product**: what
you get to keep, edit, and share.

## The problem this addresses

Every existing AI-assisted worldbuilding or game-generation system treats
generation as a pipeline: one agent (or one model, prompted sequentially)
hands off to the next stage. There is no genuine disagreement built into
the process, so there is nothing to catch when a proposal contradicts
something already established, nothing forcing the system away from
generic genre defaults, and no mechanism that makes tension between
narrative and design goals visible rather than silently resolved by
whichever agent ran last.

Stratum's specialists hold mandates that are structurally, permanently in
tension: the Lorekeeper defends established canon, the Provocateur is
required to push against the safest available option, the Harmonist
enforces tonal consistency, the Architect enforces spatial and
playability logic. These agents cannot converge sycophantically because
their objectives are incompatible by design — the disagreement is not
simulated, it is load-bearing.

## The four agents and the negotiation protocol

- **Lorekeeper** — guards admitted canon, blocks contradictions, cites
  specific prior entries as evidence in every objection.
- **Provocateur** — demands tension and moral complexity, structurally
  opposes whichever current proposal is safest, but must still produce a
  viable scene.
- **Harmonist** — enforces tonal and aesthetic register across scenes,
  can issue a hard flag on severe tonal violations that the Arbiter must
  explicitly address rather than merely weigh.
- **Architect** — owns spatial logic and playability, assigns each new
  location a position on the map, ensures traversal makes sense.
- **Arbiter** — synthesizes the four proposals and their cross-critiques
  into one final scene, informed by a panel of four dimension-specific
  judges (coherence, playability, surprise, tone), and states which
  proposal it favored and which it overruled.

Each scene goes through a dialectical loop: **thesis** (all four agents
propose in parallel, each reading current canon first), **antithesis**
(structured cross-critiques — the Lorekeeper and Provocateur always
critique each other; the Harmonist and Architect are routed to whichever
proposal is most tonally divergent or spatially weak), **synthesis** (the
Arbiter rules, informed by the judge panel), and **verified admission**
(the proposed scene is checked against the existing world bible for
contradictions before it is committed — including, in the Twine-targeted
version, a check that no link points to a passage that will never exist).

A user can inject a world constraint at any point mid-generation — it is
admitted directly into the world bible without pausing generation, and
agents visibly incorporate it into their next round of proposals.

## Research foundations

Three papers ground the architecture, chosen specifically because none of
them alone matches this problem, but combined they do:

**QUARE** (arXiv 2603.11890, June 2026) — the primary structural
reference. Formulates multi-agent collaboration as explicit dialectical
negotiation among quality-specialized agents with genuinely conflicting
mandates: thesis (proposal), antithesis (peer critique citing specific
violated constraints), synthesis (moderated resolution), with explicit
termination and full traceability. Reported 98.2% compliance coverage,
roughly double the best non-negotiating baseline. Stratum's four
specialists and dialectical loop are a direct structural adaptation of
this protocol from requirements engineering to creative generation.

**Debate2Create** (arXiv 2510.25850, Feb 2026) — source of the
pluralistic judge panel. Introduces a role-separated thesis-antithesis-
synthesis debate loop where a panel of judges, each focused on a
different criterion, provides multi-objective feedback that prevents
convergence on a single narrow optimum. Reports 18–35% quality gains over
compute-matched zero-shot generation, with synthesis consistently
outperforming the initial thesis across rounds — this is the reference
point for Stratum's claimed efficiency gain over a single-agent baseline.

**DELM** (arXiv 2606.10662, June 2026, Stanford) — source of the verified
admission gate and the dependency-aware task queue. DELM replaces
centralized orchestration with parallel agents writing to a shared
verified context: updates are checked against supporting evidence before
being admitted, so errors cannot propagate because they are never
committed. DELM's own verification mechanism is corpus-grounded (checking
factual claims against source documents) and does not transfer directly
to creative generation, where there is no ground truth to check against.
Stratum's contribution here is a direct and explicit adaptation: replacing
corpus-grounded verification with **consistency-grounded verification**
against a living, agent-authored world model — checking not "is this
true" but "does this contradict what we've already agreed." The
dependency-aware task queue (scene N cannot begin until scene N-1 is
admitted) is used as-is.

**RPGAgent** (CHI 2026) — the closest existing system, and the one whose
gap defines Stratum's delta. RPGAgent is a story-to-play pipeline for
novice game designers using the Elemental Tetrad framework: specialized
agents for narrative, scene, and mechanics, in a **sequential handoff**,
outputting a Unity prototype. Its own stated finding is an unresolved
tension between full automation and the granular creative oversight
users wanted — its agents never negotiate, they hand off. That gap — a
pipeline instead of a society — is the precise, citable delta Stratum
claims: agents that must reach consensus through structured conflict,
not agents that pass work down a line.

**Applied 2026 findings that inform the design, beyond the three core
papers:** a controlled 2025 study on multi-agent incident response found
single-agent recommendations were actionable only 1.7% of the time versus
100% for a multi-agent pipeline — evidence that multi-agent coordination
can produce categorical, not marginal, quality differences on tasks where
a single agent structurally cannot hold all constraints at once. PwC
demonstrated a 7x accuracy improvement using structured validation loops.
The MAST failure taxonomy (1,600+ traces) found specification ambiguity
and unstructured coordination cause 79% of production multi-agent
failures — the reason Stratum's critiques must cite specific entry IDs
rather than being free-form disagreement. Production systems in 2026 have
converged on 3-4 agent teams with typed messages and explicit roles,
because coordination overhead grows faster than returns beyond that —
Stratum's four-agent-plus-arbiter structure matches this finding rather
than adding agents for spectacle.

## Judging criteria and how each is addressed

**Technical Depth & Engineering (30%)** — five distinct QwenCloud model
roles, each doing a job the others cannot: a high-reasoning model for
world-foundation and final synthesis, a fast model for the four parallel
specialists, a cost-efficient model for the four judges, an image model
for scene illustration, an embedding model for the admission gate's
similarity check. The Lorekeeper's grounding comes from reading the full
world-bible canon context on every call and being required by its prompt
to cite a specific entry ID for any critique — canon-grounded, not
external-web-grounded (MCP-based real-world web search was considered but
not implemented). The admission gate is a genuine
engineering optimization — a cheap vector-similarity screen runs first,
and the expensive LLM contradiction check only fires on the rare
high-similarity pairs, keeping the gate fast as the world bible grows.
Three cited, dated research papers are structurally embedded in the
architecture, not name-dropped.

**Innovation & AI Creativity (30%)** — the specific, defensible novelty
claim is the consistency-grounded admission gate (an explicit adaptation
of a mechanism built for factual verification into one for creative
consistency), the pluralistic judge panel applied to a creative task
rather than a scoring task, and the compilation of negotiated, provenance-
tagged output directly into an established, external file format rather
than a proprietary schema. The honest limit: "multi-agent debate" alone
is not a novel pattern by mid-2026; the pitch must lead with the specific
mechanism, not the generic framing.

**Problem Value & Impact (25%)** — the deliverable is a real file that
opens in software an existing, active community already uses, edits, and
shares — not an output trapped inside a demo app. The generalizable
artifact for the open-source community is the verified-world-bible-to-
Twee compiler itself: any creative multi-agent system producing branching
structured content could adopt the same admission-gate-to-Twee pipeline,
independent of anything else in Stratum. The honest limit: this serves a
real but bounded audience (indie interactive-fiction authors, game-jam
participants, tabletop GMs) rather than an enterprise pain point — a
genuinely useful niche tool, not infrastructure for an industry, and the
pitch should not oversell past that.

**Presentation & Documentation (15%)** — the three track requirements
(task decomposition, disagreement resolution, measurable efficiency gain)
are demonstrated in that exact order within the first two minutes of the
demo, each with a live visual, not an explanation. The riskiest part of
this criterion is entirely execution risk around live-demo latency,
mitigated by pre-generation and a replay mode rather than live generation
under time pressure during recording.

**What "efficiency gain" actually means here.** `backend/metrics.py`'s
`compute_comparison()` reports a 4th figure, `token_usage`, alongside the
three quality metrics, and it is not a win by the obvious reading: Stratum
spends far more tokens and model calls per scene than the single-shot
baseline. Counting proposal/critique/judge/synthesis calls in the saved
demo run (`demo_recordings/c7c529ae8bdd/event_log.json`) gives roughly 13
chat calls per scene in the base case (4 proposals + 4 critiques + 4
judge-dimension batches + 1 synthesis), rising toward ~16-18 when a
citation retry or an admission-gate rejection fires — this is an estimate
from counting call sites and events, not a token-level measurement, since
that demo run predates the token instrumentation. The baseline makes
exactly 1 call. The efficiency gain the track requirement asks for isn't
fewer tokens — it's a favorable quality-per-token trade that a single
agent has no mechanism to buy at any price: no amount of tokens handed to
one undifferentiated model call produces cited, adversarial critique, a
pluralistic judge panel, or a verified admission gate, because those are
structural properties of having multiple accountable roles, not
properties of more inference on one call.

## Honest value assessment

The negotiated-world-bible-to-Twee compiler is something a developer
building their own AI-assisted interactive fiction tool would plausibly
want independent of the rest of Stratum — that is the test for whether
this is a real contribution or a demo dressed up as one, and it passes.
The dialectical negotiation protocol with cited, typed critiques is a
reusable pattern for any domain needing adversarial-but-structured
creative consensus, not something specific to game worlds. The
limitation to state plainly, not hide: the user base is real but not
large, and this is closer to "a genuinely useful tool for a passionate
niche" than "a solution to an authentic business pain point" in the sense
the judging language implies for enterprise-scale submissions. Framed
honestly at that scale, the value claim is credible; framed as solving an
industry-wide problem, it would not survive scrutiny.
