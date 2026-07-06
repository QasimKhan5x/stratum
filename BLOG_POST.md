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
