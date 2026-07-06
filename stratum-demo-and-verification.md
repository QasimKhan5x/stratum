# Stratum — Demo Script and Verification Loop

## Purpose of this document

Two related things: what the 3-minute demo needs to show and why each
beat exists, and how to verify — before ever hitting record — that the
system will actually produce those beats reliably. A demo script without
a verification plan behind it is a hope, not a plan.

---

## The demo, beat by beat, with the reason for each beat

**0:00–0:12 — Cold open, no explanation.** The interface appears already
mid-negotiation: the cyanotype hex map partially lit, one region pulsing
amber, the debate panel mid-argument. One line of narration: *"This world
is being argued into existence."* Reason: judges see something visually
distinctive before they're told what it is — curiosity before
explanation, not the reverse.

**0:12–0:30 — The four agents, one line each.** Role cards for
Lorekeeper, Provocateur, Harmonist, Architect. Reason: establishes the
mental model the rest of the demo depends on, in the minimum time
possible.

**0:30–1:00 — The seed step, visibly.** The premise is typed, the map
goes to full fog, and `qwen3.7-max` streams 6–8 foundational entries into
the world bible and onto the map — one of them, deliberately, lands amber
and marked contested. Reason: this establishes Qwen3.7-Max as a distinct,
purposeful model call (Technical Depth), makes the world bible a visible
artifact before negotiation even starts, and plants the specific
contested entry the demo will pay off in the next beat.

**1:00–2:00 — Live negotiation, scene one.** Thesis proposals stream in
from all four specialists. The Provocateur tries to resolve the planted
contested entry prematurely. The Lorekeeper objects, citing it by ID. The
Arbiter's synthesis is submitted to the admission gate — and the gate
**catches the contradiction and rejects it**, triggering a visible,
targeted re-negotiation of just that one field. The corrected version is
admitted; the map's fog lifts over that region; the illustration
populates the hex. Reason: this 15-second gate-catch is the single most
important moment in the entire demo. It is the one beat that cannot occur
in a single-agent system, and it must be shown happening, not described.

**2:00–2:20 — Human constraint injection.** The user types a world
constraint mid-generation (e.g. "the cartographer is blind"). It is
admitted immediately without pausing anything. The next round's
proposals visibly incorporate it. Reason: demonstrates the world bible is
a live, writable structure, not a read-only log — and sets up the
baseline comparison that follows by establishing something the baseline
has no equivalent mechanism for.

**2:20–2:40 — Baseline comparison.** Split screen: Stratum's map next to
a single-agent baseline map generated from the same premise. Three
numbers on screen: contradiction rate, creative-divergence score,
provenance depth (count of entries with a full attribution chain versus
the baseline's flat, unstructured text). Reason: the efficiency-gain
requirement made visible and specific rather than asserted — and it lands
harder here than at the start, because the audience has already watched
the mechanism that produces the difference.

**2:40–3:00 — The Twine reveal and close.** Cut to the actual `.twee`
file, or the compiled `.html`, opening in real Twine desktop — the same
negotiation history visible as native colored tag pills on real passages,
no custom viewer. One closing line: *"Every world is a real Twine story.
Every layer, argued into existence."* GitHub link. Reason: this is the
Problem Value payoff — the deliverable is real and portable, not a demo
trick.

---

## What must be verified before recording, and why each check exists

The single biggest risk to this demo is that beats 1:00–2:00 and
2:20–2:40 depend on specific things actually happening — a contradiction
being caught, a measurable gap between Stratum and the baseline — and
neither is guaranteed just because the architecture is correctly built.
These need to be checked for real, ahead of time, not assumed.

**Does the gate-catch moment actually happen with this premise?**
Run the full pipeline against the intended demo premise multiple times.
If the Provocateur never actually tries to prematurely resolve the
planted contested entry, or if it does but the Lorekeeper's objection
doesn't land specifically enough to be legible on screen, the seed
entry's contested framing needs to be made more tempting — a stronger,
more concretely valuable-sounding unresolved tension — until the
gate-catch reliably occurs. This is a prompt-tuning problem, not an
engineering bug, and it needs a human watching real output to diagnose,
not just a passing test.

**Does the baseline comparison actually show a real, honest gap?**
Run the baseline on the same premise and check the three numbers for
real. If the baseline happens not to contradict itself on this
particular premise, the comparison looks weak on screen regardless of
whether the underlying architecture is sound. The premise needs enough
genuine internal complexity (multiple named factions, a scarce resource,
at least one ambiguous fact) that a single sequential generation is
likely to trip over itself by scene 3–5. This should be empirically
checked, not assumed from the premise reading well on paper.

**Does the exported Twine file actually open correctly in real Twine
software?** Generate a `.twee` file from a real run and literally open it
in the Twine desktop app (or twinejs in a browser) before the demo is
locked. Check: does the `StoryData` passage validate (a well-formed
capital-letter v4 UUID as IFID, a recognized `format` value), do the tag
colors render as expected, do all links resolve to passages that exist,
does the compiled `.html` actually play through without a broken link
stopping the story. This is the one part of the demo relying on an
external tool's exact expectations rather than our own code, so it is
the part most likely to fail from a small formatting mismatch that only
shows up when the real tool tries to read the file.

**Does the negotiation feel continuous, not laggy, when actually run
live-adjacent?** Time an actual run end to end, including the seed step,
several full scenes, and image generation. If there are visible dead
gaps where nothing appears to be happening, that is a latency problem to
solve (background pre-fetching of the next round while the current one
finalizes, streaming the Arbiter's reasoning tokens so the wait itself
becomes visible content) — not something to paper over by speeding up
the video, which reads as fake.

---

## The verification loop, as a general practice through the build

The core discipline, independent of any specific tooling: **never trust
a component's own self-report that it worked — check the actual output.**
Concretely, this means layering checks from cheapest to most expensive
and not skipping ahead:

1. **Structural checks first** — does the code run without error, does
   structured output actually parse against the expected shape. Cheap,
   fast, catches basic mistakes immediately.
2. **State-machine checks** — using mock agent responses, does the
   negotiation lifecycle (thesis → antithesis → judging → synthesis →
   admission → re-negotiation on rejection) transition correctly in
   every case, including the rejection-and-retry path and a timeout
   fallback if a background pre-fetch doesn't complete in time. This
   catches orchestration bugs without spending on real model calls.
3. **Real-model schema checks** — call each real agent prompt against
   DashScope once and confirm the output is genuinely usable: does the
   Lorekeeper actually cite an entry ID when it objects, does the
   Architect actually avoid an already-occupied position, does the
   Arbiter's stated position match what the Architect proposed rather
   than inventing its own. This is where prompt problems surface, and it
   needs to happen before building anything downstream that assumes
   these outputs are reliable.
4. **Full local run, no cloud infrastructure** — the entire pipeline
   against real model calls, storing state in memory rather than
   Tablestore, to verify the actual negotiation dynamics are interesting
   and coherent before any cloud deployment work begins. This is the
   step most likely to reveal that a prompt is technically correct but
   produces boring or repetitive results — something no automated test
   can catch, because it's a judgment call about output quality, not
   correctness.
5. **End-to-end with real infrastructure** — once cloud services are
   live, run the same checks again against the deployed system, because
   network latency, cold starts, and real concurrent SSE connections
   introduce failure modes that a local run cannot surface.
6. **The demo-specific checks above** — run last, against the actual
   intended demo premise, because passing every general test does not
   guarantee the specific narrative beats the demo depends on will occur.

The philosophy underneath all of this: automated checks are necessary
but not sufficient. Whether a generated scene is actually interesting,
whether an objection actually reads as a real disagreement rather than
boilerplate, whether the gate-catch moment is legible to someone watching
for the first time — these require a human actually reading the output,
not just checking that a test suite exited zero. Build in time for that
reading, especially right before the demo premise is finalized and right
before recording.

---

## Practical fallback if something in beats 1:00–2:00 or 2:20–2:40 proves
unreliable close to the deadline

Prefer pre-generating the demo world ahead of time and replaying the
recorded negotiation log at a controlled pace over attempting true live
generation during recording. This is honest — it is the same negotiation
that happened, not a fabrication — and it removes the risk of an
unrepeatable, premise-dependent moment (like the gate-catch) simply not
firing on the one take that gets recorded. Label it plainly on screen as
a replay of a real run, not as live generation, if this path is taken.
