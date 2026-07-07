// Local dev serves the frontend (python -m http.server, port 8090) and
// backend (uvicorn, port 8000) separately, so API calls need an explicit
// origin. In production (nginx reverse-proxying both under one origin —
// see the deployment's nginx site config) the frontend and API share an
// origin, so a relative base just works.
const API_BASE = location.port === "8090" ? "http://localhost:8000" : "";

// ponytail: single-run-at-a-time client state, no persistence across page
// reloads. Upgrade path: a run picker backed by a "list runs" endpoint, if
// juggling multiple concurrent negotiations ever becomes a real need.
const state = {
  runId: null,
  eventSource: null,
  // Tracks the highest round any event has referenced so far. Used to cap
  // which world-bible entries the map renders (see refreshWorld) — without
  // this, replaying a finished run's full event history (see backend.main's
  // /api/stream replay-then-live design, and demo_recordings/ for
  // pre-generated runs used per stratum-demo-and-verification.md's
  // pre-generate-and-replay fallback) would show every scene's hex
  // instantly instead of progressively, since /api/world always returns
  // the run's *current* (i.e. final, for a finished run) state regardless
  // of how far the paced event replay has actually gotten.
  maxRoundSeen: 0,
  retryScenes: new Set(),
  scenePhases: new Map(),
  currentScene: null,
  lastLoggedScene: null,
  gateBannerTimer: null,
  timelineScenes: new Map(),
  canonEntries: new Map(),
  gateCatchEntry: null,
  gateCatchSummary: null,
  metrics: null,
  baselineReady: false,
  runComplete: false,
};

const AGENTS = {
  LOREKEEPER: { name: "Lorekeeper", short: "LO", color: "var(--agent-lorekeeper)", roster: true },
  PROVOCATEUR: { name: "Provocateur", short: "PR", color: "var(--agent-provocateur)", roster: true },
  HARMONIST: { name: "Harmonist", short: "HA", color: "var(--agent-harmonist)", roster: true },
  ARCHITECT: { name: "Architect", short: "AR", color: "var(--agent-architect)", roster: true },
  ARBITER: { name: "Arbiter", short: "AB", color: "var(--agent-arbiter)", roster: true },
  JUDGES: { name: "Judges", short: "JG", color: "var(--agent-judge)", roster: true },
  GATE: { name: "Gate", short: "GT", color: "var(--agent-gate)", roster: true },
  HUMAN: { name: "Human", short: "HU", color: "var(--agent-human)" },
  SEED: { name: "Seed", short: "SE", color: "var(--agent-seed)" },
  BASELINE: { name: "Baseline", short: "BL", color: "var(--agent-baseline)" },
};

const PHASE_BY_EVENT = {
  proposal: "Proposing",
  critique: "Critiquing",
  judge_score: "Judging",
  synthesis: "Synthesizing",
  admission_result: "Admission",
};

const TIMELINE_PHASES = [
  ["proposal", "Propose"],
  ["critique", "Critique"],
  ["judge_score", "Judge"],
  ["synthesis", "Synthesize"],
  ["admission_result", "Gate"],
];

const EVENT_STAGE = Object.fromEntries(TIMELINE_PHASES);

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

function agentKey(agent, eventType) {
  const raw = String(agent || "").toUpperCase();
  if (AGENTS[raw]) return raw;
  if (raw.startsWith("JUDGE") || eventType === "judge_score") return "JUDGES";
  if (eventType === "admission_result") return "GATE";
  if (eventType === "baseline_ready") return "BASELINE";
  if (eventType === "human_injection") return "HUMAN";
  if (eventType === "seed_entry") return "SEED";
  return raw || "GATE";
}

function agentMeta(agent, eventType) {
  const key = agentKey(agent, eventType);
  return AGENTS[key] || { name: agent || "System", short: (agent || "SY").slice(0, 2), color: "var(--text-tertiary)" };
}

async function checkConnection() {
  const statusEl = document.getElementById("connection-status");
  try {
    const res = await fetch(`${API_BASE}/health`);
    const body = await res.json();
    if (res.ok && body.status === "ok") {
      statusEl.textContent = "connected";
      statusEl.className = "status-pill status-pill--ok";
    } else {
      throw new Error("unexpected /health response");
    }
  } catch (err) {
    statusEl.textContent = "offline";
    statusEl.className = "status-pill status-pill--error";
    console.error("Stratum backend not reachable:", err);
  }
}

function setRunStatus(text, kind) {
  const el = document.getElementById("run-status");
  el.textContent = text;
  el.className = `status-pill status-pill--${kind}`;
}

// --- Hex map ------------------------------------------------------------
// Per stratum-architecture-plan.md's "why a hex grid, not a free-form node
// graph": entries carry an axial [x, y] grid_position assigned by the
// Architect specialist; this just lays that grid out with a standard
// pointy-top axial-to-pixel conversion and colors each cell by status.
const HEX_SIZE = 42;

function hexToPixel(x, y) {
  return {
    cx: HEX_SIZE * Math.sqrt(3) * (x + y / 2) + 220,
    cy: HEX_SIZE * 1.5 * y + 100,
  };
}

function hexPoints(cx, cy, size) {
  return Array.from({ length: 6 }, (_, i) => {
    const angle = (Math.PI / 180) * (60 * i - 30);
    return [cx + size * Math.cos(angle), cy + size * Math.sin(angle)].join(",");
  }).join(" ");
}

function shortHexLabel(entry) {
  const round = entry.provenance_round ?? "?";
  const glyph = entry.status === "canon" ? "◆" : entry.status === "rejected" ? "×" : "!";
  return `${glyph}${round}`;
}

function tooltipHtml(entry) {
  const title = entry.full_text?.split("\n")[0] || entry.summary || "Untitled scene";
  return `
    <div class="hex-tooltip__meta" style="--agent-color: ${agentMeta(entry.provenance_agent).color}">
      ${escapeHtml(entry.provenance_agent)} · round ${escapeHtml(entry.provenance_round)} · ${escapeHtml(entry.status)}
    </div>
    <strong>${escapeHtml(title)}</strong>
    <div class="hex-tooltip__summary">${escapeHtml(entry.summary)}</div>
  `;
}

function showHexTooltip(event, entry) {
  const tooltip = document.getElementById("hex-tooltip");
  const panel = document.querySelector(".map-panel");
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
  container.selectAll("svg").remove();
  hideHexTooltip();

  const positioned = entries.filter((e) => Array.isArray(e.grid_position));
  if (positioned.length === 0) return;

  const svg = container.append("svg").attr("viewBox", "0 0 900 700");
  const defs = svg.append("defs");

  const cells = svg
    .selectAll("g.hex-cell")
    .data(positioned, (d) => d.id)
    .join("g")
    .attr("class", (d) => `hex-cell hex-cell--${d.status}`)
    .attr("tabindex", "0")
    .attr("role", "button")
    .attr("aria-label", (d) => `${d.status} scene, round ${d.provenance_round}: ${d.summary}`);

  cells.each(function (d) {
    const g = d3.select(this);
    const [x, y] = d.grid_position;
    const { cx, cy } = hexToPixel(x, y);
    const points = hexPoints(cx, cy, HEX_SIZE);

    // A scene with a generated illustration (backend.agents.illustrator)
    // fills its hex with the image via an SVG pattern instead of the flat
    // status color — per the demo script's "the illustration populates the
    // hex" beat. Falls back to the plain colored hex otherwise, so a scene
    // whose image failed or hasn't arrived yet (image generation runs
    // concurrently, see backend/orchestrator.py) still renders normally.
    if (d.image_url) {
      const patternId = `hex-image-${d.id}`;
      defs
        .append("pattern")
        .attr("id", patternId)
        .attr("patternUnits", "userSpaceOnUse")
        .attr("x", cx - HEX_SIZE)
        .attr("y", cy - HEX_SIZE)
        .attr("width", HEX_SIZE * 2)
        .attr("height", HEX_SIZE * 2)
        .append("image")
        .attr("href", d.image_url)
        .attr("width", HEX_SIZE * 2)
        .attr("height", HEX_SIZE * 2)
        .attr("preserveAspectRatio", "xMidYMid slice");

      g.append("polygon")
        .attr("class", "hex-cell__poly")
        .attr("points", points)
        // .style(), not .attr(): an SVG presentation attribute like
        // fill="..." loses to any matching CSS class rule (e.g.
        // .hex-cell--canon .hex-cell__poly's fill in style.css), but an
        // inline style wins — needed here so the image pattern actually
        // replaces the status color instead of being silently overridden.
        .style("fill", `url(#${patternId})`);
    } else {
      g.append("polygon").attr("class", "hex-cell__poly").attr("points", points);
    }

    g.append("title").text(`[${d.provenance_agent} · round ${d.provenance_round} · ${d.status}]\n${d.summary}`);

    g.append("text")
      .attr("class", "hex-cell__label")
      .attr("text-anchor", "middle")
      .attr("x", cx)
      .attr("y", cy + 4)
      .text(shortHexLabel(d));

    g.on("mouseenter focus", (event) => showHexTooltip(event, d)).on("mouseleave blur", hideHexTooltip);
  });
}

async function refreshWorld() {
  if (!state.runId) return;
  const res = await fetch(`${API_BASE}/api/world/${state.runId}`);
  if (!res.ok) return;
  const body = await res.json();
  renderHexMap(body.entries.filter((e) => e.provenance_round <= state.maxRoundSeen));
}

// --- Debate log -----------------------------------------------------------

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
        <span class="roster-chip__avatar" aria-hidden="true">${escapeHtml(meta.short)}</span>
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
    seed_entry: ["GATE", "seeded"],
    proposal: [payload.role || agent, "proposing"],
    critique: [payload.critic_role || agent, "critiquing"],
    judge_score: ["JUDGES", "judging"],
    synthesis: ["ARBITER", "synthesizing"],
    admission_result: ["GATE", payload.admitted ? "admitted" : "rejected", payload.admitted ? "admit" : "reject"],
    human_injection: ["HUMAN", "injected"],
    baseline_ready: ["JUDGES", "scored"],
    scene_failed: ["ARBITER", "failed"],
    image_ready: ["GATE", "illustrated"],
    run_complete: ["ARBITER", payload.status === "done" ? "complete" : "failed"],
  }[eventType];
  if (byType) setRosterStatus(...byType);
}

function updateSceneIndicator(eventType, scene) {
  if (!scene && scene !== 0) return;
  state.currentScene = scene;
  const phase = PHASE_BY_EVENT[eventType];
  if (phase) {
    const phases = state.scenePhases.get(scene) || [];
    if (!phases.includes(phase)) phases.push(phase);
    state.scenePhases.set(scene, phases);
  }
  const el = document.getElementById("scene-indicator");
  if (!el) return;
  const phases = state.scenePhases.get(scene) || [];
  el.textContent = phases.length ? `Scene ${scene} · ${phases.join(" → ")}` : `Scene ${scene}`;
}

function finishSceneIndicator(status) {
  const el = document.getElementById("scene-indicator");
  if (!el) return;
  const scenes = Array.from(state.timelineScenes.keys()).filter((scene) => scene || scene === 0);
  const finalScene = scenes.length ? Math.max(...scenes) : state.currentScene;
  const prefix = finalScene || finalScene === 0 ? `Scene ${finalScene}` : "Replay";
  el.textContent = status === "done" ? `${prefix} · Complete` : `${prefix} · Failed`;
}

function phaseTone(eventType, payload = {}) {
  if (eventType === "admission_result") return payload.admitted ? "admit" : "reject";
  if (eventType === "scene_failed") return "reject";
  if (eventType === "image_ready") return "image";
  return "active";
}

function trackTimelineEvent(eventType, payload = {}, meta = {}) {
  const scene = meta.scene;
  if (!scene && scene !== 0) return;
  const agent = agentKey(meta.agent || payload.role || payload.critic_role, eventType);
  const sceneState = state.timelineScenes.get(scene) || { events: [], retry: false, resolved: false };
  if (eventType === "admission_result" && !payload.admitted) sceneState.retry = true;
  if (eventType === "admission_result" && payload.admitted) sceneState.resolved = true;
  sceneState.events.push({
    type: eventType,
    agent,
    stage: EVENT_STAGE[eventType] || eventType.replace(/_/g, " "),
    tone: phaseTone(eventType, payload),
  });
  state.timelineScenes.set(scene, sceneState);
  renderTimeline();
}

function renderTimeline() {
  const timeline = document.getElementById("agent-timeline");
  if (!timeline) return;
  if (state.timelineScenes.size === 0) {
    timeline.innerHTML = '<p class="agent-timeline__empty">Waiting for negotiation events.</p>';
    return;
  }

  // ponytail: timeline is client event-order only; upgrade path is backend
  // attempt IDs/timestamps if cross-tab replay fidelity becomes important.
  timeline.innerHTML = Array.from(state.timelineScenes.entries())
    .sort(([a], [b]) => a - b)
    .map(([scene, sceneState]) => {
      const cells = sceneState.events
        .slice(-18)
        .map((event) => {
          const meta = agentMeta(event.agent, event.type);
          return `
            <span
              class="agent-timeline__cell agent-timeline__cell--${escapeHtml(event.tone)}"
              style="--agent-color: ${meta.color}"
              title="${escapeHtml(meta.name)} · ${escapeHtml(event.stage)}"
              aria-label="${escapeHtml(meta.name)} ${escapeHtml(event.stage)}"
            >${escapeHtml(meta.short)}</span>
          `;
        })
        .join("");
      const status = sceneState.retry
        ? sceneState.resolved
          ? "caught → resolved"
          : "gate catch"
        : sceneState.resolved
          ? "admitted"
          : "negotiating";
      return `
        <div class="agent-timeline__row">
          <div class="agent-timeline__scene">
            <strong>Scene ${escapeHtml(scene)}</strong>
            <span>${escapeHtml(status)}</span>
          </div>
          <div class="agent-timeline__cells">${cells}</div>
        </div>
      `;
    })
    .join("");
}

function entryTitle(entry) {
  return entry.summary || entry.full_text?.split("\n")[0] || entry.id || "Untitled entry";
}

function rememberCanonEntry(entry, source = "admitted") {
  if (!entry?.id) return;
  state.canonEntries.set(entry.id, { ...state.canonEntries.get(entry.id), ...entry, ledger_source: source });
  renderCanonLedger();
  renderScorecard();
}

function markCanonImage(entryId, imageUrl) {
  if (!entryId) return;
  const existing = state.canonEntries.get(entryId);
  if (!existing) return;
  state.canonEntries.set(entryId, { ...existing, image_url: imageUrl || existing.image_url });
  renderCanonLedger();
  renderScorecard();
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
  const entries = Array.from(state.canonEntries.values())
    .filter((entry) => entry.status === "canon")
    .sort((a, b) => (a.provenance_round ?? 0) - (b.provenance_round ?? 0));
  count.textContent = `${entries.length} admitted`;
  if (entries.length === 0) {
    list.innerHTML = '<li class="canon-ledger__empty">Admitted scenes will accumulate here.</li>';
    return;
  }
  list.innerHTML = entries
    .map((entry) => {
      const meta = agentMeta(entry.provenance_agent);
      const markers = [
        entry.image_url ? "image" : null,
        entry.ledger_source === "seed" ? "seed" : "canon",
      ].filter(Boolean);
      return `
        <li class="canon-ledger__item" style="--agent-color: ${meta.color}">
          <span class="canon-ledger__round">S${escapeHtml(entry.provenance_round ?? 0)}</span>
          <div class="canon-ledger__body">
            <strong>${escapeHtml(truncate(entryTitle(entry), 88))}</strong>
            <span>${escapeHtml(meta.name)} · ${markers.map(escapeHtml).join(" · ")}</span>
          </div>
        </li>
      `;
    })
    .join("");
}

function appendSceneDivider(scene) {
  if (!scene || state.lastLoggedScene === scene) return;
  state.lastLoggedScene = scene;
  const log = document.getElementById("debate-log");
  const divider = document.createElement("div");
  divider.className = "scene-divider";
  divider.textContent = `Scene ${scene}`;
  log.appendChild(divider);
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
  const sub = options.scene ? `<span class="entry__sub">scene ${escapeHtml(options.scene)}</span>` : "";
  entry.innerHTML = `
    <div class="entry__avatar" aria-hidden="true">${escapeHtml(meta.short)}</div>
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
}

function truncate(text, n = 220) {
  if (!text) return "";
  return text.length > n ? `${text.slice(0, n)}…` : text;
}

function retrying(scene, eventType) {
  return state.retryScenes.has(scene) && ["proposal", "critique", "synthesis", "judge_score"].includes(eventType);
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
  banner.classList.toggle("gate-banner--reject", !payload.admitted);
  banner.classList.toggle("gate-banner--admit", Boolean(payload.admitted));
  icon.textContent = payload.admitted ? "✓" : "!";
  title.textContent = payload.admitted ? `Scene ${scene} admitted after review` : `Scene ${scene} contradiction caught`;
  detail.textContent = payload.admitted
    ? `Resolved through renegotiation. ${payload.reason || "Candidate no longer conflicts with canon."}`
    : `${payload.conflicting_entry_id ? `Conflicts with ${payload.conflicting_entry_id}. ` : ""}${payload.reason || "Contradiction detected."} Specialists will retry this scene.`;
  if (announcer) announcer.textContent = `${title.textContent}. ${detail.textContent}`;
  const panel = document.querySelector(".map-panel");
  panel?.classList.toggle("map-panel--flash", !payload.admitted);
  panel?.classList.toggle("map-panel--settle", Boolean(payload.admitted));
  window.setTimeout(() => panel?.classList.remove("map-panel--flash", "map-panel--settle"), 700);
  if (payload.admitted) {
    state.gateBannerTimer = window.setTimeout(() => {
      banner.hidden = true;
      banner.classList.remove("gate-banner--admit");
    }, 2400);
  }
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

function shakeContestedHexes() {
  document.querySelectorAll(".hex-cell--contested, .hex-cell--rejected").forEach((cell) => {
    cell.classList.remove("hex-cell--shake");
    void cell.getBoundingClientRect();
    cell.classList.add("hex-cell--shake");
    window.setTimeout(() => cell.classList.remove("hex-cell--shake"), 700);
  });
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
  const gateScenes = Array.from(state.timelineScenes.values()).filter((scene) => scene.retry).length;
  const resolvedGateScenes = Array.from(state.timelineScenes.values()).filter((scene) => scene.retry && scene.resolved).length;
  const items = [
    ["Scenes negotiated", `${state.timelineScenes.size || "—"} lanes`],
    ["Contradictions caught", gateScenes ? `${gateScenes}${resolvedGateScenes ? `, ${resolvedGateScenes} resolved` : ""}` : "none observed yet"],
    ["Retries triggered", `${state.retryScenes.size || gateScenes || 0}`],
    ["Admitted scenes", `${canonCount} entries`],
    [".twee ready", state.runId ? "download export available" : "start or load a run"],
    ["Qwen + MCP path", "Qwen agents, MCP admission screen"],
  ];
  if (state.gateCatchSummary) {
    items.push(["Conflict caught and resolved", state.gateCatchSummary]);
  }
  if (state.metrics?.contradiction_rate) {
    items.push([
      "Contradiction metric",
      metricSummaryText("contradiction_rate", state.metrics.contradiction_rate),
    ]);
  }
  if (state.metrics?.token_usage) {
    items.push([
      "Observed token cost",
      metricSummaryText("token_usage", state.metrics.token_usage),
    ]);
  }
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

function renderEventToLog(eventType, payload, meta = {}) {
  updateRosterForEvent(eventType, payload, meta.agent);
  updateSceneIndicator(eventType, meta.scene);
  trackTimelineEvent(eventType, payload, meta);
  const opts = {
    scene: meta.scene,
    retry: retrying(meta.scene, eventType),
  };
  switch (eventType) {
    case "seed_entry":
      rememberCanonEntry(payload, "seed");
      appendDebateEntry(
        eventType,
        "SEED",
        `<strong>${payload.status === "contested" ? "contested — " : ""}</strong>${escapeHtml(truncate(payload.summary))}`,
        opts
      );
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
        `<strong>Target: ${escapeHtml(payload.target_role || "—")}.</strong> ${payload.hard_flag ? "<strong>Hard flag.</strong> " : ""}${detailsHtml("Read objection", payload.objection)} <span style="opacity:.6">(cites ${escapeHtml(payload.cited_entry_id)})</span>`,
        opts
      );
      break;
    case "judge_score":
      appendDebateEntry(
        eventType,
        "JUDGES",
        `<strong>${escapeHtml(payload.dimension)} on ${escapeHtml(payload.role_scored)}: ${escapeHtml(payload.score)}/10</strong> — ${detailsHtml("Read rationale", payload.rationale)}`,
        opts
      );
      break;
    case "synthesis":
      appendDebateEntry(
        eventType,
        "ARBITER",
        `${escapeHtml(truncate(payload.synthesis_notes))}`,
        {
          ...opts,
          chips: [
            payload.favored_role ? { label: `favored ${payload.favored_role}`, tone: "ok" } : null,
            payload.overruled_role ? { label: `overruled ${payload.overruled_role}`, tone: "warn" } : null,
            payload.entry_id ? `candidate ${payload.entry_id}` : null,
            meta.scene ? `scene ${meta.scene}` : null,
            meta.round ? `round ${meta.round}` : null,
            opts.retry ? { label: "retry arbitration", tone: "warn" } : null,
            "arbiter ruling",
          ],
        }
      );
      refreshWorld();
      break;
    case "admission_result":
      // ponytail: retry state is scene-scoped because rejected revisions mint
      // fresh entry IDs. Upgrade path: backend emits a stable revision group ID.
      if (payload.admitted) {
        showGateBanner(payload, meta.scene);
        state.retryScenes.delete(meta.scene);
        if (state.timelineScenes.get(meta.scene)?.retry) {
          state.gateCatchSummary = `Scene ${meta.scene} resolved after gate retry`;
        }
        refreshCanonEntry(payload.entry_id);
      } else {
        state.retryScenes.add(meta.scene);
        state.gateCatchSummary = `Scene ${meta.scene} conflict caught; retry queued`;
        showGateBanner(payload, meta.scene);
        shakeContestedHexes();
      }
      if (!payload.admitted) {
        state.gateCatchEntry = `gate-catch-${domIdPart(payload.entry_id || `${meta.scene}-${meta.round}`)}`;
        updateGateJump();
      }
      appendDebateEntry(
        eventType,
        "GATE",
        payload.admitted
          ? `<strong>admitted</strong> — ${escapeHtml(truncate(payload.reason, 160))}`
          : `<strong>rejected</strong>${payload.conflicting_entry_id ? ` against <strong>${escapeHtml(payload.conflicting_entry_id)}</strong>` : ""} — ${escapeHtml(truncate(payload.reason, 180))}`,
        {
          ...opts,
          admitted: payload.admitted,
          retry: !payload.admitted || opts.retry,
          id: !payload.admitted ? state.gateCatchEntry : null,
          focusable: !payload.admitted,
          chips: [
            { label: payload.admitted ? "gate admitted" : "gate rejected", tone: payload.admitted ? "ok" : "danger" },
            payload.entry_id ? `candidate ${payload.entry_id}` : null,
            payload.conflicting_entry_id ? { label: `conflict ${payload.conflicting_entry_id}`, tone: "danger" } : null,
            !payload.admitted ? { label: "retry queued", tone: "warn" } : state.timelineScenes.get(meta.scene)?.retry ? { label: "resolved", tone: "ok" } : null,
            meta.scene ? `scene ${meta.scene}` : null,
          ],
        }
      );
      renderScorecard();
      refreshWorld();
      break;
    case "human_injection":
      rememberCanonEntry(payload, "human");
      appendDebateEntry(eventType, "HUMAN", `constraint injected: "${escapeHtml(truncate(payload.full_text))}"`, opts);
      refreshWorld();
      break;
    case "scene_failed":
      appendDebateEntry(eventType, "ARBITER", `scene could not converge after retries — skipped. ${escapeHtml(truncate(payload.reason, 160))}`, opts);
      break;
    case "image_ready":
      markCanonImage(payload.entry_id, payload.image_url);
      appendDebateEntry(eventType, "GATE", `illustration ready for <strong>${escapeHtml(payload.entry_id)}</strong>.`, opts);
      refreshWorld();
      break;
    case "baseline_ready":
      state.baselineReady = true;
      appendDebateEntry(eventType, "BASELINE", "single-shot baseline generation complete.", {
        ...opts,
        chips: [
          { label: "baseline", tone: "warn" },
          "single-shot",
          "no negotiation",
        ],
      });
      document.getElementById("baseline-panel").hidden = false;
      document.getElementById("baseline-text").textContent = payload.text;
      renderScorecard();
      loadMetrics();
      break;
    case "run_complete":
      state.runComplete = true;
      appendDebateEntry(
        eventType,
        "ARBITER",
        payload.status === "done" ? "Negotiation complete." : `Run failed: ${escapeHtml(payload.error)}`,
        {
          ...opts,
          chips: [
            { label: payload.status === "done" ? "run complete" : "run failed", tone: payload.status === "done" ? "ok" : "danger" },
            "scorecard ready",
          ],
        }
      );
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
    renderScorecard();
  } catch (err) {
    console.error("Failed to load metrics:", err);
  }
}

function connectToStream(runId) {
  if (state.eventSource) state.eventSource.close();

  state.maxRoundSeen = 0;
  state.retryScenes.clear();
  state.scenePhases.clear();
  state.currentScene = null;
  state.lastLoggedScene = null;
  state.timelineScenes.clear();
  state.canonEntries.clear();
  state.gateCatchEntry = null;
  state.gateCatchSummary = null;
  state.metrics = null;
  state.baselineReady = false;
  state.runComplete = false;
  document.getElementById("debate-log").innerHTML = "";
  document.getElementById("baseline-panel").hidden = true;
  document.getElementById("judge-scorecard").hidden = true;
  document.getElementById("gate-banner").hidden = true;
  document.getElementById("scene-indicator").textContent = "—";
  renderTimeline();
  renderCanonLedger();
  updateGateJump();
  hideHexTooltip();

  // ?pace=<seconds>[&slow_from=<i>&slow_to=<i>&slow_pace=<seconds>] (see
  // backend.main's _stream_run) paces a finished run's replay to look like
  // it's unfolding live, with an optional slower window (e.g. the
  // gate-catch) — for demo recording only, meaningless for a run that's
  // still actually generating.
  const params = new URLSearchParams(window.location.search);
  const replayParams = new URLSearchParams();
  for (const key of ["pace", "slow_from", "slow_to", "slow_pace", "grace"]) {
    if (params.has(key)) replayParams.set(key, params.get(key));
  }
  const qs = replayParams.toString();
  const streamUrl = `${API_BASE}/api/stream/${runId}${qs ? `?${qs}` : ""}`;
  const es = new EventSource(streamUrl);
  es.onopen = () => {
    const isReplay = new URLSearchParams(window.location.search).has("run");
    setRunStatus(isReplay ? `replay ${runId} — streaming…` : `run ${runId} — streaming…`, "pending");
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
      renderEventToLog(type, type === "run_complete" ? parsed : parsed.payload, {
        round: type === "run_complete" ? state.maxRoundSeen : parsed.round,
        scene: type === "run_complete" ? state.currentScene : parsed.scene,
        agent: type === "run_complete" ? "ARBITER" : parsed.agent,
      });
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
  window.open("https://twinejs.org", "_blank");
}

document.addEventListener("DOMContentLoaded", () => {
  initRoster();
  checkConnection();

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
