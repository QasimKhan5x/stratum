// Local dev serves the frontend (python -m http.server, port 8090) and
// backend (uvicorn, port 8000) separately, so API calls need an explicit
// origin. In production (nginx reverse-proxying both under one origin —
// see the deployment's nginx site config) the frontend and API share an
// origin, so a relative base just works.
const API_BASE = location.port === "8090" ? "http://localhost:8000" : "";

// Fixed, deterministic hex grid — entries are placed at their real stored
// grid_position (clamped defensively), never an ad hoc layout. Rendered in
// full from the first paint so fog-of-war is a real territory, not a set
// of placeholder diamonds that only appears once something has happened
// there.
//
// Sized to 6x5 (30 cells) to match a typical run's real entry count (6-8
// seed entries + up to 4 scenes = ~10-12 total) — ponytail: this must stay
// in sync with the "0-5 by 0-4" bounds given to agents in
// backend/agents/prompts.py, seed.py, specialists.py, and arbiter.py's
// grid_position instructions. A 12x8=96 grid was tried first and left
// ~85-90% of the board permanently fog for an entire run, which read as a
// broken/empty map rather than "fog of war" — see the map-review findings.
// Upgrade path if runs ever produce meaningfully more entries: size this
// (and the matching backend bounds) to scene_count dynamically instead of
// a fixed constant.
const GRID_COLS = 6;
const GRID_ROWS = 5;
const HEX_SIZE = 34;

// ponytail: single-run-at-a-time client state, no persistence across page
// reloads. Upgrade path: a run picker backed by a "list runs" endpoint, if
// juggling multiple concurrent negotiations ever becomes a real need.
const state = {
  runId: null,
  eventSource: null,
  // Tracks the highest round any event has referenced so far. Used to cap
  // which world-bible entries the map renders (see refreshWorld) — without
  // this, replaying a finished run's full event history would show every
  // scene's hex instantly instead of progressively, since /api/world always
  // returns the run's *current* (i.e. final, for a finished run) state
  // regardless of how far the paced event replay has actually gotten.
  maxRoundSeen: 0,
  // How many admission-gate rejections a scene has already absorbed, so a
  // retry's fresh proposals/critiques/judging/synthesis are attributed to
  // "Round 2" (etc.) instead of being visually indistinguishable from a
  // clean first pass. The schema has no explicit attempt/revision id, so
  // this is inferred purely from event order: bumped only once, right
  // after logging a rejection, using nothing but scene + arrival order.
  sceneAttempt: new Map(),
  timelineScenes: new Map(),
  foundationCount: 0,
  humanInjectionCount: 0,
  foundationDividerShown: false,
  lastLoggedScene: null,
  currentScene: null,
  gateBannerTimer: null,
  disagreementBannerTimer: null,
  canonEntries: new Map(),
  gateCatchEntry: null,
  gateCatchSummary: null,
  metrics: null,
  baselineText: null,
  baselineReady: false,
  runComplete: false,
  // Demo-recording-only pacing params, captured once at load and stripped
  // from the visible URL (see stripReplayParamsFromUrl) so the address bar
  // stays clean during actual use.
  replayParams: {},
};

const AGENTS = {
  LOREKEEPER: { name: "Lorekeeper", glyph: "i-book", color: "var(--agent-lorekeeper)", roster: true },
  PROVOCATEUR: { name: "Provocateur", glyph: "i-bolt", color: "var(--agent-provocateur)", roster: true },
  HARMONIST: { name: "Harmonist", glyph: "i-fork", color: "var(--agent-harmonist)", roster: true },
  ARCHITECT: { name: "Architect", glyph: "i-compass", color: "var(--agent-architect)", roster: true },
  ARBITER: { name: "Arbiter", glyph: "i-seal", color: "var(--agent-arbiter)", roster: true },
  JUDGES: { name: "Judges' Panel", glyph: "i-scale", color: "var(--agent-judges)", roster: true },
  GATE: { name: "Admission Gate", glyph: "i-shield", color: "var(--agent-gate)", roster: true },
  HUMAN: { name: "Human", glyph: "i-hand", color: "var(--agent-human)" },
  SEED: { name: "Seed Agent", glyph: "i-sprout", color: "var(--agent-seed)" },
  BASELINE: { name: "Baseline", glyph: "i-baseline", color: "var(--agent-baseline)" },
  ILLUSTRATOR: { name: "Illustrator", glyph: "i-image", color: "var(--agent-illustrator)" },
};

const EVENT_STAGE = {
  proposal: "Propose",
  critique: "Critique",
  judge_score: "Judge",
  synthesis: "Synthesize",
  admission_result: "Gate",
};

// Event types with no per-scene negotiation lifecycle: seeding happens once
// before any negotiation, a human injection can land at any moment without
// belonging to a specialist/judge/arbiter round, baseline generation is a
// side channel, and run_complete is a terminal marker — none of these
// belong inside the "Scene N, Round M" grid (see trackTimelineEvent).
const NON_SCENE_EVENTS = new Set(["seed_entry", "human_injection", "baseline_ready", "run_complete"]);

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function domIdPart(value) {
  return String(value ?? "unknown").replace(/[^a-zA-Z0-9_-]/g, "-");
}

function glyphHtml(glyphId) {
  return `<svg class="glyph" aria-hidden="true"><use href="#${escapeHtml(glyphId || "i-baseline")}"></use></svg>`;
}

function agentKey(agent, eventType) {
  // ponytail: defensive client-side normalization for pre-B2 saved replay
  // logs that still carry un-normalized role strings like "THE HARMONIST"
  // straight from the model output. New runs are normalized at the source
  // (backend/agent_roles.py), but old saved runs aren't rewritten, so this
  // strips a leading "THE " here too rather than falling through to a
  // generic fallback icon for perfectly identifiable agents.
  const raw = String(agent || "").toUpperCase().replace(/^THE\s+/, "");
  if (AGENTS[raw]) return raw;
  if (eventType === "image_ready") return "ILLUSTRATOR";
  if (raw.startsWith("JUDGE") || eventType === "judge_score") return "JUDGES";
  if (eventType === "admission_result") return "GATE";
  if (eventType === "baseline_ready") return "BASELINE";
  if (eventType === "human_injection") return "HUMAN";
  if (eventType === "seed_entry") return "SEED";
  return raw || "GATE";
}

function agentMeta(agent, eventType) {
  const key = agentKey(agent, eventType);
  return AGENTS[key] || { name: agent || "System", glyph: "i-baseline", color: "var(--paper-faint)" };
}

function agentDisplayName(rawRole) {
  return agentMeta(rawRole).name || rawRole || "Someone";
}

function truncate(text, n = 220) {
  if (!text) return "";
  return text.length > n ? `${text.slice(0, n)}…` : text;
}

function entryTitle(entry) {
  return entry?.summary || entry?.full_text?.split("\n")[0] || "an unnamed entry";
}

// Every user-facing string must read the world, never its storage keys —
// raw ids like "scene-d0571fa3" mean nothing to someone watching a story
// get negotiated. Cited/conflicting ids always name an already-committed
// world-bible entry, so this resolves to its human summary, falling back
// to a generic phrase if that entry hasn't been indexed on the client yet.
function describeEntry(id) {
  if (!id) return "an earlier entry";
  const entry = state.canonEntries.get(id);
  if (entry) return truncate(entryTitle(entry), 90);
  return "an earlier entry";
}

async function checkConnection() {
  const statusEl = document.getElementById("connection-status");
  try {
    const res = await fetch(`${API_BASE}/health`);
    const body = await res.json();
    if (res.ok && body.status === "ok") {
      statusEl.textContent = "connected";
      statusEl.className = "seal seal--ok";
    } else {
      throw new Error("unexpected /health response");
    }
  } catch (err) {
    statusEl.textContent = "offline";
    statusEl.className = "seal seal--error";
    console.error("Stratum backend not reachable:", err);
  }
}

function setRunStatus(text, kind) {
  const el = document.getElementById("run-status");
  el.textContent = text;
  el.className = `seal seal--${kind}`;
}

// --- Hex map ------------------------------------------------------------
// A fixed 12x8 grid renders in full from the first paint — every cell that
// hasn't been admitted into canon is genuinely dark, unrevealed territory,
// not a duller reuse of the lit style. Entries carry their real stored
// grid_position; out-of-range values are clamped defensively rather than
// silently dropped or laid out ad hoc.

function hexToPixel(x, y) {
  return {
    cx: HEX_SIZE * Math.sqrt(3) * (x + y / 2) + HEX_SIZE + 12,
    cy: HEX_SIZE * 1.5 * y + HEX_SIZE + 12,
  };
}

function hexPoints(cx, cy, size) {
  return Array.from({ length: 6 }, (_, i) => {
    const angle = (Math.PI / 180) * (60 * i - 30);
    return [cx + size * Math.cos(angle), cy + size * Math.sin(angle)].join(",");
  }).join(" ");
}

function clampGridPosition(pos) {
  if (!Array.isArray(pos) || pos.length < 2) return null;
  const x = Math.max(0, Math.min(GRID_COLS - 1, Math.round(Number(pos[0]) || 0)));
  const y = Math.max(0, Math.min(GRID_ROWS - 1, Math.round(Number(pos[1]) || 0)));
  return [x, y];
}

function cellClass(cell) {
  return `hex-cell hex-cell--${cell.entry ? cell.entry.status : "fog"}`;
}

function tooltipHtml(entry) {
  const title = entry.full_text?.split("\n")[0] || entry.summary || "Untitled scene";
  return `
    <div class="hex-tooltip__meta" style="--agent-color: ${agentMeta(entry.provenance_agent).color}">
      ${escapeHtml(agentDisplayName(entry.provenance_agent))} · round ${escapeHtml(entry.provenance_round)} · ${escapeHtml(entry.status)}
    </div>
    <strong>${escapeHtml(title)}</strong>
    <div class="hex-tooltip__summary">${escapeHtml(entry.summary)}</div>
  `;
}

function showHexTooltip(event, entry) {
  const tooltip = document.getElementById("hex-tooltip");
  const panel = document.querySelector(".stage__map");
  if (!tooltip || !panel) return;
  const panelRect = panel.getBoundingClientRect();
  const sourceRect = event.currentTarget.getBoundingClientRect();
  const x = sourceRect.left + sourceRect.width / 2 - panelRect.left;
  const y = sourceRect.top - panelRect.top;
  tooltip.innerHTML = tooltipHtml(entry);
  tooltip.hidden = false;
  tooltip.style.left = `${Math.max(12, Math.min(x + 12, panelRect.width - 280))}px`;
  tooltip.style.top = `${Math.max(12, y + 12)}px`;
}

function hideHexTooltip() {
  const tooltip = document.getElementById("hex-tooltip");
  if (tooltip) tooltip.hidden = true;
}

function renderHexMap(entries) {
  const container = d3.select("#hex-map");
  hideHexTooltip();

  // ponytail: last-write-wins on a grid-cell collision (two entries
  // clamping to the same [x, y], observed in real runs). A proper fix
  // would have the Architect specialist check occupancy before assigning
  // grid_position; upgrade path if collisions turn out to be common.
  const occupantByCell = new Map();
  const sorted = [...entries].sort((a, b) => (a.provenance_round ?? 0) - (b.provenance_round ?? 0));
  for (const entry of sorted) {
    const pos = clampGridPosition(entry.grid_position);
    if (!pos) continue;
    occupantByCell.set(`${pos[0]}:${pos[1]}`, entry);
  }

  const cells = [];
  for (let y = 0; y < GRID_ROWS; y++) {
    for (let x = 0; x < GRID_COLS; x++) {
      const key = `${x}:${y}`;
      cells.push({ key, x, y, entry: occupantByCell.get(key) || null });
    }
  }

  const { cx: maxCx, cy: maxCy } = hexToPixel(GRID_COLS - 1, GRID_ROWS - 1);
  const pad = HEX_SIZE * 1.6;

  let svg = container.select("svg");
  if (svg.empty()) {
    svg = container.append("svg");
    const defs = svg.append("defs");
    // Fog-of-war hatch: a diagonal-line pattern (a real drafting-table
    // convention for "unspecified/TBD" area) so unrevealed hexes read as
    // deliberately obscured territory, not just empty background with a
    // faint outline — the flat near-background fill alone didn't read as
    // "fog" in review screenshots even though the mechanism was real.
    const fogPattern = defs
      .append("pattern")
      .attr("id", "fog-hatch")
      .attr("patternUnits", "userSpaceOnUse")
      .attr("width", 10)
      .attr("height", 10)
      .attr("patternTransform", "rotate(45)");
    fogPattern.append("rect").attr("width", 10).attr("height", 10).attr("fill", "var(--blue-1)");
    fogPattern
      .append("line")
      .attr("x1", 0)
      .attr("y1", 0)
      .attr("x2", 0)
      .attr("y2", 10)
      .attr("stroke", "var(--line-soft)")
      .attr("stroke-width", 1.5);
  }
  svg.attr("viewBox", `0 0 ${maxCx + pad} ${maxCy + pad}`);
  const defs = svg.select("defs");

  const newlyRevealed = [];

  const groups = svg
    .selectAll("g.hex-cell")
    .data(cells, (d) => d.key)
    .join((enter) => enter.append("g").attr("class", cellClass));

  groups.each(function (d) {
    const g = d3.select(this);
    const wasRevealed = g.classed("hex-cell--canon") || g.classed("hex-cell--contested");
    const status = d.entry ? d.entry.status : "fog";
    const nowRevealed = status !== "fog";
    if (!wasRevealed && nowRevealed) newlyRevealed.push(d);

    g.attr("class", cellClass(d))
      .attr("tabindex", nowRevealed ? "0" : null)
      .attr("role", nowRevealed ? "button" : null)
      .attr("aria-label", nowRevealed ? `${status} scene, round ${d.entry.provenance_round}: ${d.entry.summary}` : null)
      .attr("aria-hidden", nowRevealed ? null : "true")
      .on("mouseenter.tip focus.tip", nowRevealed ? (event) => showHexTooltip(event, d.entry) : null)
      .on("mouseleave.tip blur.tip", nowRevealed ? hideHexTooltip : null);

    g.selectAll("*").remove();

    const { cx, cy } = hexToPixel(d.x, d.y);
    const points = hexPoints(cx, cy, HEX_SIZE - 2);

    if (d.entry?.image_url) {
      const patternId = `hex-image-${domIdPart(d.entry.id)}`;
      if (defs.select(`#${patternId}`).empty()) {
        defs
          .append("pattern")
          .attr("id", patternId)
          .attr("patternUnits", "userSpaceOnUse")
          .attr("x", cx - HEX_SIZE)
          .attr("y", cy - HEX_SIZE)
          .attr("width", HEX_SIZE * 2)
          .attr("height", HEX_SIZE * 2)
          .append("image")
          .attr("href", d.entry.image_url)
          .attr("width", HEX_SIZE * 2)
          .attr("height", HEX_SIZE * 2)
          .attr("preserveAspectRatio", "xMidYMid slice");
      }
      g.append("polygon").attr("class", "hex-cell__poly").attr("points", points).style("fill", `url(#${patternId})`);
    } else {
      g.append("polygon").attr("class", "hex-cell__poly").attr("points", points);
    }

    if (nowRevealed) {
      g.append("title").text(
        `[${agentDisplayName(d.entry.provenance_agent)} · round ${d.entry.provenance_round} · ${status}]\n${d.entry.summary}`
      );
      // Tucked into a corner with its own backdrop, not dead-center on the
      // hex, so the round-number label stays legible against a busy scene
      // illustration and doesn't visually collide with a neighboring hex's
      // label when several revealed hexes cluster tightly together.
      const labelX = cx - HEX_SIZE * 0.5;
      const labelY = cy - HEX_SIZE * 0.5;
      g.append("circle").attr("class", "hex-cell__label-backdrop").attr("cx", labelX).attr("cy", labelY).attr("r", 8);
      g.append("text")
        .attr("class", "hex-cell__label")
        .attr("text-anchor", "middle")
        .attr("x", labelX)
        .attr("y", labelY + 3)
        .text(d.entry.provenance_round ?? "");
    }
  });

  // Fog visibly recedes at the moment of admission rather than a static
  // swap: a brief brightness pulse on the hex itself plus a one-shot flash
  // burst radiating from its center.
  for (const d of newlyRevealed) {
    const g = svg.selectAll("g.hex-cell").filter((dd) => dd.key === d.key);
    g.classed("hex-cell--reveal", true);
    const { cx, cy } = hexToPixel(d.x, d.y);
    g.append("circle").attr("class", "hex-cell__flash").attr("cx", cx).attr("cy", cy).attr("r", HEX_SIZE * 0.85);
    window.setTimeout(() => g.classed("hex-cell--reveal", false), 900);
  }
}

async function refreshWorld() {
  if (!state.runId) return;
  const res = await fetch(`${API_BASE}/api/world/${state.runId}`);
  if (!res.ok) return;
  const body = await res.json();
  for (const entry of body.entries) {
    state.canonEntries.set(entry.id, { ...state.canonEntries.get(entry.id), ...entry });
  }
  renderCanonLedger();
  renderComparison();
  renderScorecard();
  renderHexMap(body.entries.filter((e) => e.provenance_round <= state.maxRoundSeen));
}

// --- Roster ---------------------------------------------------------------

function initRoster() {
  const list = document.getElementById("roster-list");
  if (!list) return;
  list.innerHTML = "";
  Object.entries(AGENTS)
    .filter(([, meta]) => meta.roster)
    .forEach(([key, meta]) => {
      const chip = document.createElement("li");
      chip.className = `roster-chip roster-chip--${key.toLowerCase()}`;
      chip.dataset.agent = key;
      chip.style.setProperty("--agent-color", meta.color);
      chip.innerHTML = `
        <span class="roster-chip__avatar" aria-hidden="true">${glyphHtml(meta.glyph)}</span>
        <span class="roster-chip__meta">
          <span class="roster-chip__name">${escapeHtml(meta.name)}</span>
          <span class="roster-chip__role">idle</span>
        </span>
      `;
      list.appendChild(chip);
    });
}

function setRosterStatus(agent, status, modifier) {
  const key = agentKey(agent);
  const chip = document.querySelector(`[data-agent="${key}"]`);
  if (!chip) return;
  document.querySelectorAll(".roster-chip--active").forEach((el) => el.classList.remove("roster-chip--active"));
  chip.classList.remove("roster-chip--reject", "roster-chip--admit");
  if (modifier) chip.classList.add(`roster-chip--${modifier}`);
  chip.classList.add("roster-chip--active");
  const role = chip.querySelector(".roster-chip__role");
  if (role) role.textContent = status;
}

function finishRoster(status) {
  document.querySelectorAll(".roster-chip").forEach((chip) => {
    chip.classList.remove("roster-chip--active", "roster-chip--reject", "roster-chip--admit");
    const role = chip.querySelector(".roster-chip__role");
    if (role) role.textContent = status;
  });
}

function updateRosterForEvent(eventType, payload, agent) {
  const byType = {
    proposal: [payload.role || agent, "proposing"],
    critique: [payload.critic_role || agent, "critiquing"],
    judge_score: ["JUDGES", "judging"],
    synthesis: ["ARBITER", "synthesizing"],
    admission_result: ["GATE", payload.admitted ? "admitted" : "rejected", payload.admitted ? "admit" : "reject"],
    human_injection: ["HUMAN", "injected"],
    scene_failed: ["ARBITER", "failed"],
  }[eventType];
  if (byType) setRosterStatus(...byType);
}

// --- Scene indicator + moment marquee -------------------------------------

function updateSceneIndicator(eventType, scene) {
  if (scene === undefined || scene === null) return;
  state.currentScene = scene;
  const el = document.getElementById("scene-indicator");
  if (!el) return;
  el.textContent = scene === 0 ? "Foundation" : `Scene ${scene}`;
}

function finishSceneIndicator(status) {
  const el = document.getElementById("scene-indicator");
  if (!el) return;
  const scenes = Array.from(state.timelineScenes.keys());
  const finalScene = scenes.length ? Math.max(...scenes) : state.currentScene;
  const prefix = finalScene || finalScene === 0 ? `Scene ${finalScene}` : "Replay";
  el.textContent = status === "done" ? `${prefix} · Complete` : `${prefix} · Failed`;
}

function updateMomentHeadline(eventType, payload = {}, meta = {}) {
  const el = document.getElementById("moment-headline");
  if (!el) return;
  let text = null;
  switch (eventType) {
    case "seed_entry":
      text = `The world bible gains its foundation: "${truncate(payload.summary, 120)}"`;
      break;
    case "proposal":
      text = `${agentDisplayName(payload.role)} proposes "${truncate(payload.scene_title || payload.summary, 110)}."`;
      break;
    case "critique":
      text = `${agentDisplayName(payload.critic_role)} objects to ${agentDisplayName(payload.target_role)}'s proposal${payload.hard_flag ? " — a hard flag." : "."}`;
      break;
    case "judge_score":
      text = `The ${payload.dimension} judge scores ${agentDisplayName(payload.role_scored)}'s proposal ${payload.score}/10.`;
      break;
    case "synthesis":
      text = `The Arbiter rules: ${truncate(payload.synthesis_notes, 140)}`;
      break;
    case "admission_result":
      text = payload.admitted
        ? `Scene ${meta.scene} is admitted into canon.`
        : `Contradiction caught — Scene ${meta.scene} is sent back for revision.`;
      break;
    case "human_injection":
      text = `A human constraint is woven into canon: "${truncate(payload.full_text, 120)}"`;
      break;
    case "scene_failed":
      text = `Scene ${meta.scene} could not converge after repeated revisions and was skipped.`;
      break;
    case "image_ready":
      text = `An illustration resolves for ${describeEntry(payload.entry_id)}.`;
      break;
    case "baseline_ready":
      text = "The single-shot baseline finishes, for comparison.";
      break;
    case "run_complete":
      text =
        payload.status === "done"
          ? "The negotiation concludes. The world is settled — for now."
          : `The run failed: ${payload.error || "an unknown error."}`;
      break;
    default:
      return;
  }
  el.textContent = text;
}

// --- Agent timeline: rounds within a scene, grouped and labeled ----------
//
// Real per-scene cardinality (see backend/negotiation.py): 4 specialist
// proposals, 4 cross-critiques, 4 dimension-judge calls (one real batched
// call per dimension, scoring all 4 proposals at once — the backend now
// emits this as a single judge_score event carrying all 16 scores, not 16
// separate events), 1 Arbiter synthesis, 1 gate check — per attempt. A
// rejection starts a genuinely new attempt with its own full set of those
// calls.
//
// Every DebateEvent now carries a real `attempt` field from the backend
// (see backend/schemas.py), so a NEW run's retries are tagged
// authoritatively rather than inferred. Saved replays from before that
// fix still parse fine but report `attempt: 1` for every event (Pydantic
// default) — for those, state.sceneAttempt's local inference (bumped by
// one right after an admission_result rejection is logged for a scene)
// is kept as a fallback so historical demo recordings still show their
// real retry structure. combineAttempt takes whichever signal is higher.

function currentAttempt(scene) {
  return state.sceneAttempt.get(scene) || 1;
}

function combineAttempt(backendAttempt, scene) {
  return Math.max(backendAttempt || 1, currentAttempt(scene));
}

function phaseTone(eventType, payload = {}) {
  if (eventType === "admission_result") return payload.admitted ? "admit" : "reject";
  if (eventType === "scene_failed") return "reject";
  if (eventType === "image_ready") return "image";
  return "active";
}

function trackTimelineEvent(eventType, payload = {}, meta = {}) {
  if (NON_SCENE_EVENTS.has(eventType)) return;
  const scene = meta.scene;
  if ((!scene && scene !== 0) || scene === 0) return;
  const attempt = meta.attempt || 1;
  const agent = agentKey(meta.agent || payload.role || payload.critic_role, eventType);
  const sceneState = state.timelineScenes.get(scene) || { rounds: new Map(), retry: false, resolved: false, failed: false };
  const roundState = sceneState.rounds.get(attempt) || { events: [], dimensionsSeen: new Set() };

  if (eventType === "judge_score") {
    // One judge dimension = one real batched API call scoring all four
    // proposals at once — represent that call as a single badge, not four.
    if (roundState.dimensionsSeen.has(payload.dimension)) {
      sceneState.rounds.set(attempt, roundState);
      state.timelineScenes.set(scene, sceneState);
      return;
    }
    roundState.dimensionsSeen.add(payload.dimension);
  }

  if (eventType === "admission_result") {
    if (payload.admitted) sceneState.resolved = true;
    else sceneState.retry = true;
  }
  if (eventType === "scene_failed") sceneState.failed = true;

  // Specialist-vs-specialist disagreement, tracked per round so browsing
  // the timeline afterwards shows exactly where it happened — not just a
  // toast someone had to be watching live to catch. Two independent
  // signals: a Harmonist hard flag (a critique, before resolution) and an
  // Arbiter synthesis that names a real overruled_role (the resolution).
  // Either alone is worth flagging; a round can have both.
  if (eventType === "critique" && payload.hard_flag) {
    roundState.disagreement = true;
    roundState.disagreementReason = `${agentDisplayName(payload.critic_role)} hard-flags ${agentDisplayName(payload.target_role)}: ${payload.objection || ""}`;
  }
  if (eventType === "synthesis" && payload.overruled_role) {
    roundState.disagreement = true;
    roundState.disagreementReason = `Arbiter overruled ${agentDisplayName(payload.overruled_role)} in favor of ${agentDisplayName(payload.favored_role)}: ${payload.synthesis_notes || ""}`;
  }

  roundState.events.push({
    type: eventType,
    agent,
    stage: EVENT_STAGE[eventType] || eventType.replace(/_/g, " "),
    tone: phaseTone(eventType, payload),
  });
  sceneState.rounds.set(attempt, roundState);
  state.timelineScenes.set(scene, sceneState);
  renderTimeline();
}

function sceneStatusLabel(sceneState) {
  if (sceneState.failed) return { text: "could not converge — skipped", cls: "caught" };
  if (sceneState.retry && sceneState.resolved) return { text: "caught → resolved after retry", cls: "resolved" };
  if (sceneState.retry) return { text: "contradiction caught — retrying", cls: "caught" };
  if (sceneState.resolved) return { text: "admitted on first pass", cls: "resolved" };
  return { text: "negotiating", cls: "" };
}

function renderTimeline() {
  const timeline = document.getElementById("agent-timeline");
  if (!timeline) return;

  const blocks = [];

  if (state.foundationCount > 0) {
    const injected = state.humanInjectionCount
      ? ` · ${state.humanInjectionCount} human ${state.humanInjectionCount === 1 ? "constraint" : "constraints"} injected`
      : "";
    blocks.push(`
      <div class="agent-timeline__foundation">
        ${glyphHtml("i-sprout")}
        <span>Foundation — ${state.foundationCount} world-bible ${state.foundationCount === 1 ? "entry" : "entries"} seeded${injected}</span>
      </div>
    `);
  }

  if (state.timelineScenes.size === 0) {
    if (blocks.length === 0) {
      timeline.innerHTML = '<p class="agent-timeline__empty">Waiting for negotiation events.</p>';
      return;
    }
    timeline.innerHTML = blocks.join("");
    return;
  }

  const sceneBlocks = Array.from(state.timelineScenes.entries())
    .sort(([a], [b]) => a - b)
    .map(([scene, sceneState]) => {
      const status = sceneStatusLabel(sceneState);
      const rounds = Array.from(sceneState.rounds.entries())
        .sort(([a], [b]) => a - b)
        .map(([attempt, roundState]) => {
          const cells = roundState.events
            .map((event) => {
              const meta = agentMeta(event.agent, event.type);
              return `
                <span
                  class="agent-timeline__cell agent-timeline__cell--${escapeHtml(event.tone)}"
                  style="--agent-color: ${meta.color}"
                  title="${escapeHtml(meta.name)} · ${escapeHtml(event.stage)}"
                  role="img"
                  aria-label="${escapeHtml(meta.name)} ${escapeHtml(event.stage)}"
                >${glyphHtml(meta.glyph)}</span>
              `;
            })
            .join("");
          const label = attempt > 1 ? `Round ${attempt}` : "Round 1";
          const disagreementBadge = roundState.disagreement
            ? `<span class="agent-timeline__round-disagreement" title="${escapeHtml(roundState.disagreementReason || "Specialists disagreed this round.")}">⚔ disagreement</span>`
            : "";
          return `
            <div class="agent-timeline__round ${attempt > 1 ? "agent-timeline__round--retry" : ""}">
              <span class="agent-timeline__round-label">${escapeHtml(label)}</span>
              <span class="agent-timeline__cells">${cells}</span>
              ${disagreementBadge}
            </div>
          `;
        })
        .join("");
      return `
        <div class="agent-timeline__scene-block">
          <div class="agent-timeline__scene-head">
            <strong>Scene ${escapeHtml(scene)}</strong>
            <span class="agent-timeline__scene-status agent-timeline__scene-status--${status.cls}">${escapeHtml(status.text)}</span>
          </div>
          ${rounds}
        </div>
      `;
    })
    .join("");

  blocks.push(sceneBlocks);
  timeline.innerHTML = blocks.join("");
}

// --- World bible list/detail ----------------------------------------------

function rememberCanonEntry(entry, source = "admitted") {
  if (!entry?.id) return;
  state.canonEntries.set(entry.id, { ...state.canonEntries.get(entry.id), ...entry, ledger_source: source });
  renderCanonLedger();
  renderComparison();
  renderScorecard();
}

function markCanonImage(entryId, imageUrl) {
  if (!entryId) return;
  const existing = state.canonEntries.get(entryId);
  if (!existing) return;
  state.canonEntries.set(entryId, { ...existing, image_url: imageUrl || existing.image_url });
  renderCanonLedger();
}

async function refreshCanonEntry(entryId, attempts = 3) {
  if (!state.runId || !entryId) return;
  try {
    const res = await fetch(`${API_BASE}/api/world/${state.runId}`);
    if (!res.ok) return;
    const body = await res.json();
    const match = body.entries.find((entry) => entry.id === entryId);
    if (match) rememberCanonEntry(match);
  } catch (err) {
    console.error("Failed to refresh canon entry:", err);
  }
  if (attempts > 1 && !state.canonEntries.has(entryId)) {
    window.setTimeout(() => refreshCanonEntry(entryId, attempts - 1), 250);
  }
}

function renderCanonLedger() {
  const list = document.getElementById("canon-ledger-list");
  const count = document.getElementById("canon-ledger-count");
  if (!list || !count) return;
  const entries = Array.from(state.canonEntries.values()).sort((a, b) => (a.provenance_round ?? 0) - (b.provenance_round ?? 0));
  const canonCount = entries.filter((entry) => entry.status === "canon").length;
  count.textContent = `${canonCount} admitted`;
  if (entries.length === 0) {
    list.innerHTML = '<li class="canon-ledger__empty">Entries will accumulate here as the world is negotiated.</li>';
    return;
  }
  list.innerHTML = entries
    .map((entry) => {
      const meta = agentMeta(entry.provenance_agent);
      return `
        <li>
          <button type="button" class="canon-ledger__item" style="--agent-color: ${meta.color}" data-entry-id="${escapeHtml(entry.id)}">
            <span class="canon-ledger__round">S${escapeHtml(entry.provenance_round ?? 0)}</span>
            <span class="canon-ledger__body">
              <strong>${escapeHtml(truncate(entryTitle(entry), 88))}</strong>
              <span>${escapeHtml(agentDisplayName(entry.provenance_agent))} · ${escapeHtml(entry.status)}</span>
            </span>
          </button>
        </li>
      `;
    })
    .join("");
}

function showEntryDetail(entryId) {
  const entry = state.canonEntries.get(entryId);
  const panel = document.getElementById("entry-detail");
  if (!panel || !entry) return;
  const meta = agentMeta(entry.provenance_agent);
  panel.hidden = false;
  panel.innerHTML = `
    <div class="entry-detail__meta">${escapeHtml(agentDisplayName(entry.provenance_agent))} · round ${escapeHtml(entry.provenance_round ?? 0)} · ${escapeHtml(entry.status)}</div>
    <h4 style="color: ${meta.color}">${escapeHtml(entryTitle(entry))}</h4>
    <p>${escapeHtml(entry.full_text || entry.summary || "")}</p>
  `;
  panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// --- Debate log -------------------------------------------------------------

function appendSceneDivider(scene) {
  if (scene === undefined || scene === null) return;
  const log = document.getElementById("debate-log");
  if (scene === 0) {
    if (state.foundationDividerShown) return;
    state.foundationDividerShown = true;
    const divider = document.createElement("div");
    divider.className = "scene-divider foundation-divider";
    divider.textContent = "Foundation";
    log.appendChild(divider);
    return;
  }
  if (state.lastLoggedScene === scene) return;
  state.lastLoggedScene = scene;
  const divider = document.createElement("div");
  divider.className = "scene-divider";
  divider.textContent = `Scene ${scene}`;
  log.appendChild(divider);
}

function appendRoundDivider(scene, nextAttempt) {
  const log = document.getElementById("debate-log");
  const divider = document.createElement("div");
  divider.className = "round-divider";
  divider.textContent = `↻ Renegotiation — Scene ${scene}, Round ${nextAttempt}`;
  log.appendChild(divider);
  log.scrollTop = log.scrollHeight;
}

function detailsHtml(summary, text) {
  if (!text) return "";
  if (text.length < 180) return escapeHtml(text);
  return `<details><summary>${escapeHtml(summary)}</summary>${escapeHtml(text)}</details>`;
}

function chipHtml(label, tone = "") {
  if (!label) return "";
  const toneClass = tone ? ` entry__chip--${tone}` : "";
  return `<span class="entry__chip${toneClass}">${escapeHtml(label)}</span>`;
}

function entryChipsHtml(chips = []) {
  const body = chips
    .filter(Boolean)
    .map((chip) => (typeof chip === "string" ? chipHtml(chip) : chipHtml(chip.label, chip.tone)))
    .join("");
  return body ? `<div class="entry__chip-row" data-testid="entry-chip-row">${body}</div>` : "";
}

function appendDebateEntry(eventType, agent, bodyHtml, options = {}) {
  const log = document.getElementById("debate-log");
  appendSceneDivider(options.scene);
  const meta = agentMeta(agent, eventType);
  const entry = document.createElement("article");
  const admittedClass = eventType === "admission_result" ? ` entry--admission_result--${options.admitted}` : "";
  entry.className = `entry entry--${eventType}${admittedClass}`;
  entry.style.setProperty("--agent-color", meta.color);
  if (options.id) entry.id = options.id;
  if (options.focusable) entry.tabIndex = -1;

  const retryBadge = options.retry ? `<span class="entry__event-badge">↻ Retry</span>` : "";
  const sub =
    options.scene || options.scene === 0
      ? `<span class="entry__sub">${options.scene === 0 ? "foundation" : `scene ${escapeHtml(options.scene)}`}</span>`
      : "";
  entry.innerHTML = `
    <div class="entry__avatar" aria-hidden="true">${glyphHtml(meta.glyph)}</div>
    <div class="entry__body">
      <div class="entry__head">
        <span class="entry__agent-name">${escapeHtml(meta.name)}</span>
        <span class="entry__event-badge">${escapeHtml(eventType.replace(/_/g, " "))}</span>
        ${retryBadge}
        ${sub}
      </div>
      ${entryChipsHtml(options.chips)}
      <div class="entry__content">${bodyHtml}</div>
    </div>
  `;
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
  return entry;
}

// Judge scores stream in one-per-proposal, but one dimension judge makes
// exactly one real batched call per scene attempt (see backend/agents/
// judges.py — score_all scores all 4 proposals in a single chat_json
// call). Group by (scene, attempt, dimension) into a single,
// incrementally-updating transcript entry and timeline badge instead of
// exploding each of the 16 raw judge_score events into its own unit.
const judgeScoreAccumulator = new Map();

function accumulateJudgeScore(scene, attempt, dimension, scorePayload) {
  const key = `${scene}:${attempt}:${dimension}`;
  const scores = judgeScoreAccumulator.get(key) || [];
  scores.push(scorePayload);
  judgeScoreAccumulator.set(key, scores);
  return scores;
}

function judgeGroupBodyHtml(scores) {
  return scores
    .map(
      (s) => `
        <div class="judge-score-row">
          <span>${escapeHtml(agentDisplayName(s.role_scored))}</span>
          <span>${escapeHtml(s.score)}/10</span>
        </div>
        ${detailsHtml("Read rationale", s.rationale)}
      `
    )
    .join("");
}

function renderJudgeGroup(scene, attempt, dimension, scores) {
  const id = `judge-group-${domIdPart(`${scene}-${attempt}-${dimension}`)}`;
  const el = document.getElementById(id);
  const bodyHtml = judgeGroupBodyHtml(scores);
  if (el) {
    el.querySelector(".entry__content").innerHTML = bodyHtml;
    const badge = el.querySelectorAll(".entry__event-badge")[0];
    if (badge) badge.textContent = `${dimension} verdict · ${scores.length}/4 scored`;
    return;
  }
  const created = appendDebateEntry("judge_score", "JUDGES", bodyHtml, {
    scene,
    id,
    retry: attempt > 1,
    chips: [{ label: dimension, tone: "" }, attempt > 1 ? { label: `round ${attempt}`, tone: "warn" } : null],
  });
  const badge = created.querySelectorAll(".entry__event-badge")[0];
  if (badge) badge.textContent = `${dimension} verdict · ${scores.length}/4 scored`;
}

function showGateBanner(payload, scene) {
  const banner = document.getElementById("gate-banner");
  const title = document.getElementById("gate-banner-title");
  const detail = document.getElementById("gate-banner-detail");
  const icon = banner?.querySelector(".gate-banner__icon");
  const announcer = document.getElementById("live-announcer");
  if (!banner || !title || !detail || !icon) return;
  clearTimeout(state.gateBannerTimer);
  banner.hidden = false;
  banner.classList.remove("gate-banner--caught-toast");
  banner.classList.toggle("gate-banner--reject", !payload.admitted);
  banner.classList.toggle("gate-banner--admit", Boolean(payload.admitted));
  icon.textContent = payload.admitted ? "✓" : "✕";
  title.textContent = payload.admitted ? `Scene ${scene} admitted after review` : `Contradiction caught — Scene ${scene}`;
  detail.textContent = payload.admitted
    ? `Resolved through renegotiation. ${payload.reason || "The candidate no longer conflicts with canon."}`
    : `Conflicts with ${describeEntry(payload.conflicting_entry_id)}. ${payload.reason || "A contradiction was detected."} Specialists are already revising.`;
  if (announcer) announcer.textContent = `${title.textContent}. ${detail.textContent}`;

  if (payload.admitted) {
    state.gateBannerTimer = window.setTimeout(() => {
      banner.hidden = true;
      banner.classList.remove("gate-banner--admit");
    }, 2600);
  } else {
    // Genuinely screen-dominant for a few seconds — the single most
    // dramatic mechanic in the system — then recedes to a persistent
    // corner flag so the retry that follows is still visible underneath.
    state.gateBannerTimer = window.setTimeout(() => {
      banner.classList.remove("gate-banner--reject");
      banner.classList.add("gate-banner--caught-toast");
    }, 3400);
  }
}

function showDisagreementBanner(payload, scene) {
  // Fires on the Arbiter's own ruling (a real overruled_role), the moment
  // a specialist-vs-specialist clash actually gets resolved — the live
  // counterpart to the persistent "⚔ disagreement" timeline badge above.
  const banner = document.getElementById("disagreement-banner");
  const title = document.getElementById("disagreement-banner-title");
  const detail = document.getElementById("disagreement-banner-detail");
  const announcer = document.getElementById("live-announcer");
  if (!banner || !title || !detail) return;
  clearTimeout(state.disagreementBannerTimer);
  banner.hidden = false;
  title.textContent = `Scene ${scene} — Arbiter overrules ${agentDisplayName(payload.overruled_role)}`;
  detail.textContent = `Favored ${agentDisplayName(payload.favored_role)}. ${truncate(payload.synthesis_notes, 120)}`;
  if (announcer) announcer.textContent = `${title.textContent}. ${detail.textContent}`;
  state.disagreementBannerTimer = window.setTimeout(() => {
    banner.hidden = true;
  }, 4200);
}

function triggerStageTremor() {
  const stage = document.querySelector(".stage");
  if (!stage) return;
  stage.classList.remove("stage--tremor");
  void stage.getBoundingClientRect();
  stage.classList.add("stage--tremor");
  window.setTimeout(() => stage.classList.remove("stage--tremor"), 520);
}

function updateGateJump() {
  const jump = document.getElementById("jump-gate-catch");
  if (!jump) return;
  jump.hidden = !state.gateCatchEntry;
}

function jumpToGateCatch() {
  const target = state.gateCatchEntry;
  const banner = document.getElementById("gate-banner");
  if (!target) return;
  const entry = document.getElementById(target);
  if (entry) {
    entry.scrollIntoView({ block: "center", behavior: "smooth" });
    entry.focus({ preventScroll: true });
  } else if (banner && !banner.hidden) {
    banner.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

// --- Baseline comparison + scorecard ---------------------------------------

function renderComparison() {
  const stratumEl = document.getElementById("stratum-text");
  if (!stratumEl) return;
  const canonEntries = Array.from(state.canonEntries.values())
    .filter((entry) => entry.status === "canon")
    .sort((a, b) => (a.provenance_round ?? 0) - (b.provenance_round ?? 0));
  stratumEl.textContent = canonEntries.length
    ? canonEntries.map((entry) => entry.full_text || entry.summary).join("\n\n")
    : "Waiting for admitted scenes…";
}

// Renders the baseline column paragraph-by-paragraph so a self-contradiction
// is something a reader SEES (a flagged paragraph, the earlier paragraph it
// conflicts with, and the gate's real reason) rather than something they
// have to take on faith from an abstract contradiction_rate percentage. Per
// stratum-critical-review-checklist.md's "numbers won't interest judges"
// finding — this is the visual proof, backend.metrics.compute_comparison's
// contradiction_detail is the evidence behind it.
function renderBaselineText() {
  const el = document.getElementById("baseline-text");
  if (!el) return;
  if (!state.baselineText) {
    el.textContent = "Waiting for the baseline generation…";
    return;
  }
  const paragraphs = state.baselineText.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  const detail = state.metrics?.contradiction_detail?.baseline || [];
  const detailByIndex = new Map(detail.map((d) => [d.index, d]));

  el.innerHTML = paragraphs
    .map((paragraph, i) => {
      const flag = detailByIndex.get(i);
      if (!flag || !flag.contradicts) {
        return `<span class="comparison__paragraph">${escapeHtml(paragraph)}</span>`;
      }
      const conflictNote =
        flag.conflicts_with_index != null
          ? `Contradicts paragraph ${flag.conflicts_with_index + 1} above. ${flag.reason || ""}`
          : flag.reason || "Contradicts an earlier paragraph.";
      return `
        <span class="comparison__paragraph comparison__paragraph--contradiction" tabindex="0">
          ${escapeHtml(paragraph)}
          <span class="comparison__paragraph-flag">⚠ self-contradiction — ${escapeHtml(conflictNote)}</span>
        </span>
      `;
    })
    .join("");
}

function formatMetricValue(value) {
  if (typeof value !== "number") return value ?? "—";
  if (Number.isInteger(value)) return value.toLocaleString();
  return value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

const METRIC_META = {
  contradiction_rate: { label: "Contradiction rate", better: "lower" },
  divergence_score: { label: "Creative divergence", better: "higher" },
  provenance_depth: { label: "Provenance depth", better: "higher" },
  token_usage: { label: "Token usage", better: "captured" },
};

function metricLabel(name) {
  return METRIC_META[name]?.label || name.replace(/_/g, " ");
}

function metricDirection(name) {
  const better = METRIC_META[name]?.better;
  if (better === "lower") return "lower is better";
  if (better === "higher") return "higher is better";
  return "";
}

function isMissingTokenMetric(values) {
  return !values || Number(values.stratum || 0) === 0 || Number(values.baseline || 0) === 0;
}

function metricVerdict(name, values) {
  if (!values || name === "token_usage") return "";
  const better = METRIC_META[name]?.better;
  const stratum = Number(values.stratum);
  const baseline = Number(values.baseline);
  if (!Number.isFinite(stratum) || !Number.isFinite(baseline) || !better || stratum === baseline) return "mixed result";
  const stratumWins = better === "lower" ? stratum < baseline : stratum > baseline;
  return stratumWins ? "Stratum leads" : "baseline leads";
}

function metricSummaryText(name, values) {
  if (name === "token_usage" && isMissingTokenMetric(values)) return "not captured in this replay";
  const direction = metricDirection(name);
  const verdict = metricVerdict(name, values);
  const suffix = [direction, verdict].filter(Boolean).join("; ");
  return `Stratum ${formatMetricValue(values.stratum)} vs baseline ${formatMetricValue(values.baseline)}${suffix ? ` (${suffix})` : ""}`;
}

function renderMetricsList() {
  const list = document.getElementById("metrics-list");
  if (!list) return;
  list.innerHTML = "";
  if (!state.metrics || Object.keys(state.metrics).length === 0) {
    list.innerHTML = '<p class="metrics-list__empty">Metrics are not available yet.</p>';
    return;
  }
  for (const [name, values] of Object.entries(state.metrics)) {
    const row = document.createElement("div");
    row.className = "metric-row";
    const dt = document.createElement("dt");
    dt.textContent = metricLabel(name);
    const dd = document.createElement("dd");
    if (name === "token_usage" && isMissingTokenMetric(values)) {
      dd.innerHTML = '<span class="metric-note">not captured in this replay</span>';
    } else {
      const verdict = metricVerdict(name, values);
      dd.innerHTML = `
        <span class="v-stratum">Stratum ${escapeHtml(formatMetricValue(values.stratum))}</span>
        <span class="v-baseline">Baseline ${escapeHtml(formatMetricValue(values.baseline))}</span>
        ${verdict ? `<span class="metric-note">${escapeHtml(metricDirection(name))}; ${escapeHtml(verdict)}</span>` : ""}
      `;
    }
    row.append(dt, dd);
    list.append(row);
  }
}

function renderScorecard() {
  const panel = document.getElementById("judge-scorecard");
  const list = document.getElementById("scorecard-list");
  if (!panel || !list) return;
  const canonCount = Array.from(state.canonEntries.values()).filter((entry) => entry.status === "canon").length;
  const sceneStates = Array.from(state.timelineScenes.values());
  const caughtScenes = sceneStates.filter((scene) => scene.retry).length;
  const resolvedCaughtScenes = sceneStates.filter((scene) => scene.retry && scene.resolved).length;
  const items = [
    ["Scenes negotiated", `${state.timelineScenes.size || "—"}`],
    ["Contradictions caught", caughtScenes ? `${caughtScenes}${resolvedCaughtScenes ? `, ${resolvedCaughtScenes} resolved` : ""}` : "none observed yet"],
    ["Admitted scenes", `${canonCount}`],
    [".twee export", state.runId ? "ready to download" : "start or load a run"],
  ];
  if (state.gateCatchSummary) items.push(["Latest gate ruling", state.gateCatchSummary]);
  if (state.metrics?.contradiction_rate) items.push(["Contradiction metric", metricSummaryText("contradiction_rate", state.metrics.contradiction_rate)]);
  if (state.metrics?.token_usage) items.push(["Observed token cost", metricSummaryText("token_usage", state.metrics.token_usage)]);
  list.innerHTML = items
    .map(
      ([label, value]) => `
        <div class="scorecard-item">
          <strong>${escapeHtml(value)}</strong>
          <span>${escapeHtml(label)}</span>
        </div>
      `
    )
    .join("");
  panel.hidden = !(state.baselineReady || state.runComplete || state.metrics || state.runId);
}

// --- Main event dispatch -----------------------------------------------------

function renderEventToLog(eventType, payload, meta = {}) {
  const scene = meta.scene;
  const attempt = scene || scene === 0 ? combineAttempt(meta.attempt, scene) : 1;
  const fullMeta = { ...meta, attempt };

  updateRosterForEvent(eventType, payload, meta.agent);
  updateSceneIndicator(eventType, scene);
  updateMomentHeadline(eventType, payload, fullMeta);
  trackTimelineEvent(eventType, payload, fullMeta);

  const opts = { scene, attempt, retry: attempt > 1 };

  switch (eventType) {
    case "seed_entry":
      state.foundationCount += 1;
      rememberCanonEntry(payload, "seed");
      appendDebateEntry(
        eventType,
        "SEED",
        `<strong>${payload.status === "contested" ? "contested — " : ""}</strong>${escapeHtml(truncate(payload.summary))}`,
        opts
      );
      renderTimeline();
      refreshWorld();
      break;
    case "proposal":
      appendDebateEntry(
        eventType,
        payload.role,
        `<em>${escapeHtml(payload.scene_title || "")}</em> — ${escapeHtml(truncate(payload.summary))}`,
        opts
      );
      break;
    case "critique":
      appendDebateEntry(
        eventType,
        payload.critic_role,
        `<strong>Target: ${escapeHtml(agentDisplayName(payload.target_role))}.</strong> ${payload.hard_flag ? "<strong>Hard flag.</strong> " : ""}${detailsHtml("Read objection", payload.objection)} <span style="opacity:.6">(cites: ${escapeHtml(describeEntry(payload.cited_entry_id))})</span>`,
        opts
      );
      break;
    case "judge_score":
      // Handled directly in connectToStream's listener (needs the running
      // accumulator, not just this dispatcher) — see accumulateJudgeScore.
      break;
    case "synthesis":
      appendDebateEntry(eventType, "ARBITER", `${escapeHtml(truncate(payload.synthesis_notes))}`, {
        ...opts,
        chips: [
          payload.favored_role ? { label: `favored ${agentDisplayName(payload.favored_role)}`, tone: "ok" } : null,
          payload.overruled_role ? { label: `overruled ${agentDisplayName(payload.overruled_role)}`, tone: "warn" } : null,
          `scene ${scene}`,
          opts.retry ? { label: `round ${attempt} ruling`, tone: "warn" } : null,
        ],
      });
      if (payload.overruled_role) showDisagreementBanner(payload, scene);
      refreshWorld();
      break;
    case "admission_result": {
      const wasRetry = attempt > 1;
      if (payload.admitted) {
        showGateBanner(payload, scene);
        if (wasRetry) state.gateCatchSummary = `Scene ${scene} resolved after a gate catch and retry.`;
        refreshCanonEntry(payload.entry_id);
      } else {
        state.gateCatchSummary = `Scene ${scene} — a contradiction was caught and sent back for revision.`;
        showGateBanner(payload, scene);
        triggerStageTremor();
        state.gateCatchEntry = `gate-catch-${domIdPart(payload.entry_id || `${scene}-${meta.round}`)}`;
        updateGateJump();
      }
      appendDebateEntry(
        eventType,
        "GATE",
        payload.admitted
          ? `<strong>Admitted.</strong> ${escapeHtml(truncate(payload.reason, 160))}`
          : `<strong>Rejected.</strong> ${escapeHtml(truncate(payload.reason, 180))}`,
        {
          ...opts,
          admitted: payload.admitted,
          retry: wasRetry,
          id: !payload.admitted ? state.gateCatchEntry : null,
          focusable: !payload.admitted,
          chips: [
            { label: payload.admitted ? "admitted" : "contradiction caught", tone: payload.admitted ? "ok" : "danger" },
            !payload.admitted ? { label: `conflicts with ${describeEntry(payload.conflicting_entry_id)}`, tone: "danger" } : null,
            wasRetry ? { label: `round ${attempt}`, tone: "warn" } : null,
            `scene ${scene}`,
          ],
        }
      );
      if (!payload.admitted) {
        state.sceneAttempt.set(scene, attempt + 1);
        appendRoundDivider(scene, attempt + 1);
      }
      renderScorecard();
      refreshWorld();
      break;
    }
    case "human_injection":
      state.humanInjectionCount += 1;
      rememberCanonEntry(payload, "human");
      appendDebateEntry(eventType, "HUMAN", `Constraint injected: "${escapeHtml(truncate(payload.full_text))}"`, opts);
      renderTimeline();
      refreshWorld();
      break;
    case "scene_failed":
      appendDebateEntry(eventType, "ARBITER", `Scene could not converge after retries — skipped. ${escapeHtml(truncate(payload.reason, 160))}`, opts);
      break;
    case "image_ready":
      markCanonImage(payload.entry_id, payload.image_url);
      appendDebateEntry(eventType, "ILLUSTRATOR", `An illustration resolves for <strong>${escapeHtml(describeEntry(payload.entry_id))}</strong>.`, opts);
      refreshWorld();
      break;
    case "baseline_ready":
      state.baselineReady = true;
      appendDebateEntry(eventType, "BASELINE", "The single-shot baseline generation completes.", {
        ...opts,
        chips: [{ label: "baseline", tone: "warn" }, "single-shot", "no negotiation"],
      });
      document.getElementById("baseline-panel").hidden = false;
      state.baselineText = payload.text;
      renderBaselineText();
      renderComparison();
      renderScorecard();
      loadMetrics();
      break;
    case "run_complete":
      state.runComplete = true;
      appendDebateEntry(eventType, "ARBITER", payload.status === "done" ? "Negotiation complete." : `Run failed: ${escapeHtml(payload.error)}`, {
        ...opts,
        chips: [
          { label: payload.status === "done" ? "run complete" : "run failed", tone: payload.status === "done" ? "ok" : "danger" },
          "scorecard ready",
        ],
      });
      {
        const isReplay = new URLSearchParams(window.location.search).has("run");
        const label = payload.status === "done" ? (isReplay ? "replay complete" : "run complete") : "run failed";
        setRunStatus(label, payload.status === "done" ? "ok" : "error");
      }
      finishRoster(payload.status === "done" ? "complete" : "failed");
      finishSceneIndicator(payload.status);
      renderScorecard();
      loadMetrics();
      refreshWorld();
      // The server closes its end of the stream right after this event, but
      // EventSource treats that as a dropped connection and auto-reconnects
      // by default — which would replay the entire history again from
      // scratch and duplicate every entry in the log. Closing explicitly is
      // what actually stops that.
      if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
      }
      break;
    default:
      appendDebateEntry(eventType, null, escapeHtml(JSON.stringify(payload)), opts);
  }
}

async function loadMetrics() {
  if (!state.runId) return;
  try {
    const res = await fetch(`${API_BASE}/api/metrics/${state.runId}`);
    if (!res.ok) return;
    const metrics = await res.json();
    state.metrics = metrics;
    document.getElementById("baseline-panel").hidden = false;
    renderMetricsList();
    renderBaselineText();
    renderScorecard();
  } catch (err) {
    console.error("Failed to load metrics:", err);
  }
}

// Demo-safe URL handling: pacing/debug params only matter for pre-recorded
// replay demos (see backend.main's _stream_run) and should never sit in a
// URL someone might screenshot, bookmark, or share. Captured once here and
// kept in memory (state.replayParams) so replay pacing still works even
// after the address bar is cleaned up.
function stripReplayParamsFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const pacingKeys = ["pace", "slow_from", "slow_to", "slow_pace", "grace"];
  let found = false;
  for (const key of pacingKeys) {
    if (params.has(key)) {
      state.replayParams[key] = params.get(key);
      found = true;
    }
  }
  if (!found) return;
  const clean = new URLSearchParams(window.location.search);
  for (const key of pacingKeys) clean.delete(key);
  const qs = clean.toString();
  const newUrl = `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`;
  window.history.replaceState({}, "", newUrl);
}

function connectToStream(runId) {
  if (state.eventSource) state.eventSource.close();

  state.maxRoundSeen = 0;
  state.sceneAttempt.clear();
  state.timelineScenes.clear();
  state.foundationCount = 0;
  state.humanInjectionCount = 0;
  state.foundationDividerShown = false;
  state.lastLoggedScene = null;
  state.currentScene = null;
  state.canonEntries.clear();
  state.gateCatchEntry = null;
  state.gateCatchSummary = null;
  state.metrics = null;
  state.baselineReady = false;
  state.runComplete = false;
  judgeScoreAccumulator.clear();

  document.getElementById("debate-log").innerHTML = "";
  document.getElementById("baseline-panel").hidden = true;
  document.getElementById("judge-scorecard").hidden = true;
  state.baselineText = null;
  document.getElementById("gate-banner").hidden = true;
  document.getElementById("gate-banner").className = "gate-banner";
  document.getElementById("disagreement-banner").hidden = true;
  clearTimeout(state.disagreementBannerTimer);
  document.getElementById("scene-indicator").textContent = "—";
  document.getElementById("moment-headline").textContent = "The negotiation is beginning…";
  document.getElementById("entry-detail").hidden = true;
  renderTimeline();
  renderCanonLedger();
  renderComparison();
  updateGateJump();
  hideHexTooltip();
  renderHexMap([]);

  // pace/slow_from/slow_to/slow_pace/grace (see backend.main's _stream_run)
  // pace a finished run's replay to look like it's unfolding live, with an
  // optional slower window (e.g. the gate-catch) — for demo recording only.
  // Captured once at load and kept in memory (see stripReplayParamsFromUrl)
  // rather than re-read from the (now-clean) address bar.
  const replayParams = new URLSearchParams();
  for (const [key, value] of Object.entries(state.replayParams)) replayParams.set(key, value);
  const qs = replayParams.toString();
  const streamUrl = `${API_BASE}/api/stream/${runId}${qs ? `?${qs}` : ""}`;
  const es = new EventSource(streamUrl);
  es.onopen = () => {
    const isReplay = new URLSearchParams(window.location.search).has("run");
    setRunStatus(isReplay ? `replay ${runId} — streaming…` : `run ${runId} — negotiating…`, "pending");
  };
  const eventTypes = [
    "seed_entry",
    "proposal",
    "critique",
    "judge_score",
    "synthesis",
    "admission_result",
    "human_injection",
    "baseline_ready",
    "scene_failed",
    "image_ready",
    "run_complete",
  ];
  for (const type of eventTypes) {
    es.addEventListener(type, (e) => {
      const parsed = JSON.parse(e.data);
      // run_complete is sent as a bare {status, error} dict; every other
      // event type is a full DebateEvent envelope whose actual content
      // lives in .payload (see backend/schemas.py's DebateEvent).
      if (type !== "run_complete") {
        state.maxRoundSeen = Math.max(state.maxRoundSeen, parsed.round);
      } else {
        state.maxRoundSeen = Infinity; // run finished: show everything
      }
      const meta = {
        round: type === "run_complete" ? state.maxRoundSeen : parsed.round,
        scene: type === "run_complete" ? state.currentScene : parsed.scene,
        agent: type === "run_complete" ? "ARBITER" : parsed.agent,
        // Real backend-tagged attempt/phase (backend/schemas.py). Absent
        // only for the synthetic run_complete type, which isn't a real
        // DebateEvent.
        attempt: type === "run_complete" ? undefined : parsed.attempt,
        phase: type === "run_complete" ? "negotiation" : parsed.phase,
      };
      const payload = type === "run_complete" ? parsed : parsed.payload;

      if (type === "judge_score") {
        // Judge scores need the running per-dimension accumulator (not
        // just the generic dispatcher) so the transcript/timeline can
        // represent "one dimension = one badge" instead of one badge per
        // raw event. See the comment above judgeScoreAccumulator.
        //
        // New runs (backend fix B5) emit one judge_score event per attempt
        // carrying all 16 scores as payload.scores. Saved replays from
        // before that fix still have one event per individual score, with
        // the score fields directly on payload. Normalize both into the
        // same per-item loop so nothing downstream needs to know which
        // shape it got.
        const attempt = combineAttempt(meta.attempt, meta.scene);
        const fullMeta = { ...meta, attempt };
        const scoreItems = Array.isArray(payload.scores) ? payload.scores : [payload];
        for (const scoreItem of scoreItems) {
          updateRosterForEvent(type, scoreItem, meta.agent);
          updateSceneIndicator(type, meta.scene);
          updateMomentHeadline(type, scoreItem, fullMeta);
          trackTimelineEvent(type, scoreItem, fullMeta);
          const scores = accumulateJudgeScore(meta.scene, attempt, scoreItem.dimension, scoreItem);
          renderJudgeGroup(meta.scene, attempt, scoreItem.dimension, scores);
        }
        return;
      }
      renderEventToLog(type, payload, meta);
    });
  }
  es.onerror = () => {
    // EventSource auto-retries; once the server sends run_complete we close
    // it ourselves, so a lingering error after that point is expected, not
    // a real failure.
    if (state.eventSource === es) {
      console.warn("SSE connection dropped for run", runId);
    }
  };
  state.eventSource = es;
}

async function generate(premise) {
  setRunStatus("starting…", "pending");
  const res = await fetch(`${API_BASE}/api/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ premise }),
  });
  if (!res.ok) {
    setRunStatus("failed to start", "error");
    return;
  }
  const { run_id } = await res.json();
  state.runId = run_id;
  setRunStatus(`run ${run_id} — negotiating…`, "pending");
  connectToStream(run_id);
}

async function injectConstraint(text) {
  if (!state.runId) {
    alert("Start a generation first.");
    return;
  }
  await fetch(`${API_BASE}/api/inject/${state.runId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

function downloadExport() {
  if (!state.runId) {
    alert("Start a generation first.");
    return;
  }
  window.open(`${API_BASE}/api/export/${state.runId}`, "_blank");
}

function openTwine() {
  // ponytail: no in-house Twee->HTML compiler — Twine itself already does
  // this ("Publish to File") once the exported .twee is imported. Standing
  // up a duplicate compiler here would violate YAGNI for zero added value.
  window.open("https://twinery.org", "_blank");
}

document.addEventListener("DOMContentLoaded", () => {
  stripReplayParamsFromUrl();
  initRoster();
  checkConnection();
  renderHexMap([]);

  document.getElementById("canon-ledger-list").addEventListener("click", (e) => {
    const button = e.target.closest(".canon-ledger__item");
    if (button?.dataset.entryId) showEntryDetail(button.dataset.entryId);
  });

  // Resume an existing run via ?run=<id> — reconnecting the SSE stream
  // replays everything already emitted (see backend/main.py's _stream_run)
  // before continuing live, so this also works for a run that already
  // finished, not just one still in progress.
  const resumeRunId = new URLSearchParams(window.location.search).get("run");
  if (resumeRunId) {
    state.runId = resumeRunId;
    setRunStatus(`replay ${resumeRunId} — loading…`, "pending");
    const announcer = document.getElementById("live-announcer");
    if (announcer) announcer.textContent = "Loading saved Stratum replay.";
    renderScorecard();
    refreshWorld();
    connectToStream(resumeRunId);
  }

  document.getElementById("premise-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const premise = document.getElementById("premise-input").value.trim();
    if (premise) generate(premise);
  });

  document.getElementById("constraint-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("constraint-input");
    const text = input.value.trim();
    if (text) {
      injectConstraint(text);
      input.value = "";
    }
  });

  document.getElementById("export-twee").addEventListener("click", downloadExport);
  document.getElementById("export-html").addEventListener("click", openTwine);
  document.getElementById("scorecard-export-twee").addEventListener("click", downloadExport);
  document.getElementById("jump-gate-catch").addEventListener("click", jumpToGateCatch);
});
