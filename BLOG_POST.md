# Stratum: worlds argued into existence

*A submission for the QwenCloud Hackathon, Track 3 (Agent Society).*

## The idea in one sentence

Stratum is four AI agents with genuinely incompatible creative mandates,
forced to argue every scene of a story into existence before it becomes
canon — and the transcript of that argument compiles to a real Twine file
you can open, edit, and play tonight.

## The problem with how AI worldbuilding usually works

Almost every AI-assisted worldbuilding or game-generation system today is
a pipeline: one agent (or one model, prompted in sequence) hands its
output to the next stage. Generate premise → generate locations → generate
characters → generate scenes. Nothing in that chain is designed to
disagree with anything else in it, so nothing catches a contradiction, and
nothing pushes back on the safest, most generic continuation of whatever
came before.

We wanted to know what happens if you refuse to let that convergence
happen quietly. So Stratum's four specialist agents don't collaborate —
they litigate:

- **The Lorekeeper** defends everything already established and cites the
  specific prior entry it thinks a new proposal violates.
- **The Provocateur** is structurally required to push against whichever
  option looks safest, even when safe would be easier.
- **The Harmonist** enforces tonal consistency and can raise a hard flag
  the Arbiter isn't allowed to just weigh and move past.
- **The Architect** owns spatial logic — where things are, whether
  traversal makes sense — and enforces it against everyone else's ideas.

These mandates are permanently in tension by design. They cannot converge
sycophantically, because agreeing with each other would mean abandoning
the one thing they each exist to protect.

## What actually happens each scene

Every scene goes through the same four-step loop, live, streamed to a
debate panel as it happens:

1. **Thesis.** All four specialists propose a scene in parallel, each
   having just read the current world bible.
2. **Antithesis.** Structured, cited cross-critiques — not "I disagree"
   but "this contradicts entry `scene-a1b7`, which established X." The
   Lorekeeper and Provocateur always critique each other; the Harmonist
   and Architect route to whichever proposal is weakest on their axis.
3. **Synthesis.** An Arbiter — informed by a panel of four
   dimension-specific judges scoring coherence, playability, surprise, and
   tone — rules on one final version, and states out loud which proposal
   it favored and which it overruled.
4. **Verified admission.** Before the synthesized scene is allowed to
   become canon, it's checked against everything already agreed: a cheap
   embedding-similarity pass first (so this stays fast as the world bible
   grows), then an LLM contradiction check on only the handful of prior
   entries that pass the similarity bar. If it contradicts something, it's
   rejected and the conflicting field goes back for targeted
   re-negotiation — not a full restart, just the one thing that was wrong.

A user can inject a constraint mid-generation ("the cartographer is
blind") and it's admitted straight into canon, incorporated by the very
next round of proposals, with nothing paused.

Two different kinds of disagreement get surfaced live, not left buried in
transcript prose. When the Arbiter's synthesis names a proposal it actually
overruled, a disagreement banner fires in the moment — reusing the same
visual layout as the admission gate's own rejection banner, but amber-toned
rather than the gate's crimson — plus a persistent badge on that round in
the timeline, so scrolling back through a finished run still shows exactly
where two specialists clashed and who won. Separately, the debate panel's
baseline comparison renders the single-shot baseline paragraph by paragraph, with
any self-contradicting paragraph flagged inline against the specific
earlier paragraph it conflicts with — the tradeoff Stratum is arguing for
is something you can read directly, not a bare percentage somewhere else
on the page.

## Where this comes from

Three papers, none of which alone solves this, but together they do:

- **QUARE** (2603.11890) gave us the structural shape: explicit
  thesis-antithesis-synthesis negotiation among agents with genuinely
  conflicting quality mandates, with full traceability. It reports 98.2%
  compliance coverage against requirements, roughly double the best
  non-negotiating baseline — evidence this pattern isn't just aesthetically
  nice, it changes outcomes.
- **Debate2Create** (2510.25850) is where the judge panel comes from — a
  role-separated debate loop where multiple judges score different
  criteria so the system can't quietly optimize for just one thing.
  Reports 18–35% quality gains over compute-matched zero-shot generation.
- **DELM** (2606.10662, Stanford) is where the admission gate comes from.
  DELM checks agent output against source documents before committing it
  — corpus-grounded verification. There's no source document for "is this
  fantasy city consistent with itself," so Stratum's actual contribution
  is swapping corpus-grounded verification for **consistency-grounded**
  verification: not "is this true," but "does this contradict what we
  already agreed."

The closest existing system we found, RPGAgent (CHI 2026), is explicit
about its own limitation: its narrative/scene/mechanics agents hand off
sequentially, and its own paper names the tension between full automation
and the granular oversight users wanted. That's the gap Stratum is built
to close — agents that must reach consensus through structured conflict,
not agents that pass work down a line.

## The part that isn't a demo trick: it's a real Twine file

Every admitted scene compiles to valid Twee 3 — the source notation for
[Twine](https://twinery.org), the interactive-fiction tool an actual
hobbyist and game-jam community already uses. The negotiation history
(which agent proposed what, what got overruled, which round) is encoded
as native Twine passage tags with assigned colors, using a field Twine's
own format already supports. There's no custom viewer required to see the
provenance — open the exported `.twee` file in the real Twine desktop app
and the argument history is just... there, as colored tag pills on real
passages.

That was a deliberate bet: the generalizable, reusable artifact here isn't
"a worldbuilding app," it's a verified-world-bible-to-Twee compiler.
Anyone building a different creative multi-agent system that produces
branching structured content could take the same admission-gate-to-Twee
pipeline and use it for something else entirely.

## Building it, honestly

A few things that didn't work on the first try, because a demo-ready
project post shouldn't pretend everything did:

- The first version of the admission gate's retry loop threw away all
  context on a rejection and just asked agents to "try again," which
  produced worse contradictions on the second attempt than the first —
  fixed by threading the specific rejection reason and full canon context
  into the retry, not just a bare "you were wrong."
- An early orchestrator design let an unhandled exception from a single
  failed scene take down the entire run — and, we discovered mid-testing
  on a day when DashScope was unusually slow, it could actually crash the
  whole server process for every run in flight, not just the one that
  failed. Scenes that can't converge after a bounded number of revision
  attempts are now an honest, logged outcome — the gate correctly refused
  a contradiction — not a crash.
- The judge panel originally made 16 separate model calls per negotiation
  attempt (four judges × four proposals). Batching each judge into one
  call that scores all four proposals at once cut that to 4 calls per
  attempt with no change in judging quality, and meaningfully reduced
  both latency and cost per scene.
- The hex map that illustrates each admitted scene was, for most of
  development, mostly empty and clustered in one corner — a 96-cell
  (12×8) grid against a typical run that only ever fills 8-15 hexes, fed
  by a placement prompt that just said "small non-negative integers" with
  no stated bounds or instruction to spread out, so nearly everything
  landed near `[0,0]`. Shrinking the grid to a real 6×5 and telling the
  model its actual bounds, with an explicit spread instruction, fixed
  both problems: a real run's seed entries landed at `[0,0] [5,0] [2,4]
  [1,2] [4,1] [0,4] [5,3] [3,0]` — genuinely spread across the grid, not
  clustered near the origin.

## Does the negotiation actually earn its keep?

The metrics panel already concedes the honest cost story: Stratum makes
13-18 model calls per scene against one for a single-shot baseline, and
that's a real cost, not an efficiency win we're going to spin. The harder
question a hackathon pitch is tempted to duck: does a single agent given
the *same* compute budget — spent on self-critique and revision instead of
adversarial negotiation — get you most of the way there anyway?

We built `scripts/baseline_fairness_replication.py` to check, across three
genre-distinct premises, each with its own seed-marked fact that's
deliberately meant to stay unresolved. The first pass at this (n=1, one
premise) found something uncomfortable: on a creative-divergence metric, a
compute-matched reflective baseline slightly beat Stratum. We didn't bury
that result, and the honest follow-through — rerunning it at n=3, not just
reasserting the n=1 finding — is that it doesn't replicate cleanly. On the
original premise rerun fresh, Stratum and the baseline are a statistical
tie (0.5704 vs. 0.5708); on the two new premises, Stratum is clearly ahead.
The honest read: no longer evidence *against* Stratum, but not a clean win
either — divergence_score is premise-dependent noise, not a settled
direction.

What did replicate, 3 for 3, and is now a real quantified number instead of
one person's reading of one baseline's prose: a new `premature_resolution`
metric that checks whether a variant collapses the seed-marked contested
fact into a confident answer. Stratum protected it in all three premises
(0/3). Both the naive and the compute-matched reflective baseline
collapsed it into a confident answer in two of the three (2/3 each). That's
the actual, narrower claim this project can now back with numbers: not "no
amount of single-agent compute closes this gap," but "no amount of
self-critique alone gave the single agent a structural mechanism — a
specialist whose mandate is literally to cite the entry and defend the
ambiguity, plus a gate that can reject a scene for violating it — and that
held up across three independent premises, not one lucky run." Full
methodology, raw numbers, and the parts that still don't hold up are in
`stratum-baseline-fairness-experiment.md`.

## Where Alibaba Cloud shows up

Five distinct model roles run through Alibaba Cloud's Model Studio
(QwenCloud): a high-reasoning model for world-foundation and final
synthesis, a fast model for the four parallel specialists, a
cost-efficient model for the four judges, `text-embedding-v4` for the
admission gate's similarity screen, and `qwen-image-2.0-pro` (via the
native DashScope SDK — it isn't exposed on the OpenAI-compatible endpoint)
for scene illustration, generating a cyanotype-blueprint-style image for
each admitted scene that populates its hex on the live map.

The backend itself runs on a provisioned Alibaba Cloud ECS instance in the
Singapore region — nginx serving the static frontend and reverse-proxying
the API to a uvicorn process managed by systemd — not just calling the
model API from an arbitrary host.

Beyond DashScope, two more Alibaba Cloud services are actually wired up,
not just namedropped: exported `.twee` story files upload to a real OSS
bucket and come back with a signed URL instead of only a one-time download,
and the world-bible canon itself can persist to a real Tablestore instance.
Tablestore briefly went dark mid-build when the provisioned instance got
disabled account-side — we didn't paper over that, it's logged as a
blocked item until it was confirmed fixed — and is now live again,
verified with a direct read/write check rather than taken on anyone's
word. Function Compute is deliberately unused: nothing in this project has
a genuine serverless-shaped workload, and wrapping something in an FC
function just to check a box isn't a feature.

For anyone who wants to run this without an Alibaba Cloud account at all,
canon and run history persist to a local SQLite file by default — durable
across restarts, and more than one backend process can serve the same run
off the same file — with Tablestore as the drop-in upgrade path once you
have one. The model provider itself is swappable via three environment
variables; everything except scene illustration runs through the standard
OpenAI-compatible SDK, since `qwen-image` isn't exposed on that endpoint.
One honest limit that didn't get solved: there's no per-user auth or
access model, so this is built for self-hosting, not multi-tenant SaaS.

## What this is, honestly, and what it isn't

The reusable core here is bigger than the demo: a negotiation protocol
with cited, typed critiques that generalizes well beyond game worlds to
any domain needing adversarial-but-structured creative consensus, plus a
compiler target that outputs to software people already use (Twine)
instead of a format only this app can read. The honest scope limit: as
shipped, this is a genuinely useful tool for a real but bounded audience —
indie interactive-fiction authors, game-jam participants, tabletop GMs who
want a starting world with actual internal tension rather than a generic
premise — not infrastructure for an industry, and framing it as solving an
enterprise-scale problem wouldn't survive scrutiny.

---

*Code: [GitHub link]. Live demo: http://47.84.114.89. Demo video: [link].*
