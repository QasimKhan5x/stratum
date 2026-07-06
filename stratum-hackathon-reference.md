# Stratum — Hackathon Reference

## The hackathon and track

QwenCloud Hackathon, hosted on Devpost. Deadline: **July 9, 2026.**

**Track 3: Agent Society.** Verbatim theme: "Design a multi-agent
collaboration system where multiple Agents with distinct capabilities
work together through task division, dialogue, and negotiation to
accomplish complex tasks. Participants should showcase: how Agents
decompose tasks and assign roles, how they resolve disagreements and
execution conflicts, and a measurable efficiency gain over single-agent
baselines."

The organizers' own example project ideas for this track: a simulated
marketplace where buyer and seller agents negotiate; a multi-agent debate
platform where agents argue positions and a judge evaluates; cooperative
problem-solving swarms that divide tasks and coordinate. These are
illustrative of the *interaction pattern* expected (visible negotiation,
visible disagreement, visible resolution) — not a constraint on subject
matter. Stratum's domain (worldbuilding) is a legitimate instantiation of
the same pattern class.

## Judging criteria, verbatim

- **Technical Depth & Engineering (30%)** — sophisticated use of
  QwenCloud APIs (custom skills, MCP integrations); algorithmic or
  engineering innovation through novel solutions, custom components, or
  performance optimization.
- **Innovation & AI Creativity (30%)** — high-quality architecture with
  strong modularity, scalability, and error handling; clean code and
  non-trivial logic; sophisticated tech stack via advanced patterns and
  thoughtful adoption.
- **Problem Value & Impact (25%)** — real-world relevance solving an
  authentic technical or business pain point; scalability potential for
  productization or open-source community adoption.
- **Presentation & Documentation (15%)** — clear technical demo with key
  logic visualized effectively; clear documentation including
  architecture docs describing the project.

## Submission requirements

- A demo video (aim for 3 minutes; check the exact platform limit before
  finalizing).
- A blog post describing the project (separate from and complementary to
  the demo — this is where the fuller research-foundations narrative and
  honest value framing belong, since the demo itself has no room for it).
- An architecture diagram.
- The codebase, public and accessible to judges.
- **Proof of Alibaba Cloud deployment** — explicitly required. The
  rules ask for a link to a code file in the repository that demonstrates
  use of Alibaba Cloud services and APIs, alongside evidence the backend
  is genuinely running on Alibaba Cloud infrastructure, not merely
  calling QwenCloud's model API from an arbitrary host. This is a
  distinct requirement from "uses QwenCloud models" — both must be true
  and both must be demonstrable.

## QwenCloud vs. Alibaba Cloud — the distinction that matters for setup

These are the same parent company but functionally two different
products requiring separate account activation:

**QwenCloud** (`home.qwencloud.com`, docs at `docs.qwencloud.com`) is the
model-API layer only — text generation, image/video generation, audio,
embeddings, tool calling, structured output, fine-tuning. A QwenCloud API
key is sufficient on its own to build and fully test Stratum's entire
negotiation/agent layer, with zero dependency on the Alibaba Cloud
console. The API endpoint is the standard DashScope international
endpoint and is OpenAI-SDK compatible.

**Alibaba Cloud** (`alibabacloud.com`, `account.alibabacloud.com`) is the
general cloud infrastructure account — Tablestore, OSS, Function Compute,
ECS, API Gateway. This is what the hackathon's deployment-proof
requirement is actually asking about, and it requires its own signup,
identity verification (including SMS-based phone verification), and
billing setup, separate from a QwenCloud API key.

**Practical implication:** it is entirely possible, and expected, to
build and validate most of Stratum — every agent prompt, the full
negotiation loop, the admission gate, schema validation, local
end-to-end runs — using only a QwenCloud key, before the Alibaba Cloud
infrastructure account is fully set up. The infrastructure account only
becomes a blocker for the final deployment and demo-recording phase, not
for the majority of the build. If Alibaba Cloud phone verification is
delayed or failing, this is not a reason to pause development — continue
building against QwenCloud directly and running the system locally
(storing state in memory rather than Tablestore) until the account
issue resolves.

**Getting Alibaba Cloud SMS verification unstuck, if it recurs:**
double-check the phone number format entered matches the selected
country code exactly; retry after the resend cooldown rather than
repeatedly retrying immediately; if it continues failing, use Alibaba
Cloud's live chat support widget (visible on the verification page
itself) or file a support ticket explicitly describing SMS non-delivery
for the entered number, which is a known and generally resolvable issue
for international numbers rather than a fundamental account problem.

## Hackathon-provided resources

The hackathon offers a credits coupon (report says roughly $40 in
QwenCloud credits) via a short request form — worth claiming immediately
on signup regardless of which account (QwenCloud, Alibaba Cloud, or both)
is furthest along, since it applies to model usage costs either way.

## Bonus consideration: the "journey" angle

The hackathon rewards showing the building journey, not only the final
artifact — worth keeping lightweight notes or screenshots through the
build (a prompt that failed and had to be rewritten, the admission gate
catching its first real contradiction, the moment the baseline comparison
numbers came back) for use in the blog post, rather than reconstructing
this narrative from memory at the end.
