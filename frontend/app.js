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
};

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

function renderHexMap(entries) {
  const container = d3.select("#hex-map");
  container.selectAll("svg").remove();

  const positioned = entries.filter((e) => Array.isArray(e.grid_position));
  if (positioned.length === 0) return;

  const svg = container.append("svg").attr("viewBox", "0 0 900 700");
  const defs = svg.append("defs");

  const cells = svg
    .selectAll("g.hex-cell")
    .data(positioned, (d) => d.id)
    .join("g")
    .attr("class", (d) => `hex-cell hex-cell--${d.status}`);

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

    g.append("title").text(
      `[${d.provenance_agent} · round ${d.provenance_round} · ${d.status}]\n${d.summary}`
    );

    // A single unwrapped line routinely overran the hex width and bled into
    // neighbors on dense clusters, so this wraps into up to 3 short lines
    // that actually fit — dominant-baseline is unreliable across browsers
    // for multi-line <text>, hence the manual per-tspan y offset instead.
    const lines = wrapLabel(d.summary);
    const lineHeight = 10;
    const startY = cy - ((lines.length - 1) * lineHeight) / 2;
    const label = g.append("text").attr("class", "hex-cell__label").attr("text-anchor", "middle");
    lines.forEach((line, i) => {
      label
        .append("tspan")
        .attr("x", cx)
        .attr("y", startY + i * lineHeight)
        .text(line);
    });
  });
}

function wrapLabel(summary, maxLines = 3, maxCharsPerLine = 14) {
  const words = summary.split(" ");
  const lines = [];
  let current = "";
  let consumedWords = 0;
  for (const word of words) {
    if (lines.length === maxLines) break;
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length > maxCharsPerLine && current) {
      lines.push(current);
      current = word;
    } else {
      current = candidate;
    }
    consumedWords += 1;
  }
  if (lines.length < maxLines && current) lines.push(current);
  if (consumedWords < words.length) {
    lines[lines.length - 1] = `${lines[lines.length - 1]}…`;
  }
  return lines;
}

async function refreshWorld() {
  if (!state.runId) return;
  const res = await fetch(`${API_BASE}/api/world/${state.runId}`);
  if (!res.ok) return;
  const body = await res.json();
  renderHexMap(body.entries.filter((e) => e.provenance_round <= state.maxRoundSeen));
}

// --- Debate log -----------------------------------------------------------

function appendDebateEntry(eventType, agent, bodyHtml, modifierClass) {
  const log = document.getElementById("debate-log");
  const entry = document.createElement("div");
  entry.className = `debate-entry debate-entry--${eventType}${modifierClass ? ` debate-entry--${eventType}--${modifierClass}` : ""}`;

  const meta = document.createElement("div");
  meta.className = "debate-entry__meta";
  meta.innerHTML = `<span>${eventType.replace(/_/g, " ")}</span><span>${agent || ""}</span>`;

  const body = document.createElement("div");
  body.className = "debate-entry__body";
  body.innerHTML = bodyHtml;

  entry.append(meta, body);
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
}

function truncate(text, n = 220) {
  if (!text) return "";
  return text.length > n ? `${text.slice(0, n)}…` : text;
}

function renderEventToLog(eventType, payload) {
  switch (eventType) {
    case "seed_entry":
      appendDebateEntry(eventType, "SEED", `<strong>${payload.status === "contested" ? "⚠ contested — " : ""}</strong>${truncate(payload.summary)}`);
      refreshWorld();
      break;
    case "proposal":
      appendDebateEntry(eventType, payload.role, `<em>${payload.scene_title || ""}</em> — ${truncate(payload.summary)}`);
      break;
    case "critique":
      appendDebateEntry(
        eventType,
        `${payload.critic_role} → ${payload.target_role}`,
        `${payload.hard_flag ? "🚩 " : ""}${truncate(payload.objection)} <span style="opacity:.6">(cites ${payload.cited_entry_id})</span>`
      );
      break;
    case "judge_score":
      appendDebateEntry(eventType, `${payload.dimension} on ${payload.role_scored}`, `${payload.score}/10 — ${truncate(payload.rationale, 120)}`);
      break;
    case "synthesis":
      appendDebateEntry(
        eventType,
        "ARBITER",
        `favored <strong>${payload.favored_role || "—"}</strong>, overruled <strong>${payload.overruled_role || "none"}</strong><br>${truncate(payload.synthesis_notes)}`
      );
      refreshWorld();
      break;
    case "admission_result":
      appendDebateEntry(
        eventType,
        payload.entry_id,
        payload.admitted ? `✓ admitted — ${truncate(payload.reason, 120)}` : `✗ rejected (conflicts with ${payload.conflicting_entry_id}) — ${truncate(payload.reason, 120)}`,
        String(payload.admitted)
      );
      refreshWorld();
      break;
    case "human_injection":
      appendDebateEntry(eventType, "HUMAN", `constraint injected: “${truncate(payload.full_text)}”`);
      refreshWorld();
      break;
    case "scene_failed":
      appendDebateEntry(eventType, "ARBITER", `⚠ scene could not converge after retries — skipped. ${truncate(payload.reason, 160)}`);
      break;
    case "image_ready":
      appendDebateEntry(eventType, payload.entry_id, "illustration ready.");
      refreshWorld();
      break;
    case "baseline_ready":
      appendDebateEntry(eventType, "BASELINE", "single-shot baseline generation complete.");
      document.getElementById("baseline-panel").hidden = false;
      document.getElementById("baseline-text").textContent = payload.text;
      loadMetrics();
      break;
    case "run_complete":
      appendDebateEntry(eventType, null, payload.status === "done" ? "Negotiation complete." : `Run failed: ${payload.error}`);
      setRunStatus(payload.status, payload.status === "done" ? "ok" : "error");
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
      appendDebateEntry(eventType, null, JSON.stringify(payload));
  }
}

async function loadMetrics() {
  if (!state.runId) return;
  try {
    const res = await fetch(`${API_BASE}/api/metrics/${state.runId}`);
    if (!res.ok) return;
    const metrics = await res.json();
    const list = document.getElementById("metrics-list");
    list.innerHTML = "";
    for (const [name, values] of Object.entries(metrics)) {
      const dt = document.createElement("dt");
      dt.textContent = name.replace(/_/g, " ");
      const dd = document.createElement("dd");
      dd.textContent = `stratum ${values.stratum} · baseline ${values.baseline}`;
      list.append(dt, dd);
    }
  } catch (err) {
    console.error("Failed to load metrics:", err);
  }
}

function connectToStream(runId) {
  if (state.eventSource) state.eventSource.close();

  state.maxRoundSeen = 0;
  document.getElementById("debate-log").innerHTML = "";
  document.getElementById("baseline-panel").hidden = true;

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
      renderEventToLog(type, type === "run_complete" ? parsed : parsed.payload);
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
  checkConnection();

  // Resume an existing run via ?run=<id> — reconnecting the SSE stream
  // replays everything already emitted (see backend/main.py's _stream_run)
  // before continuing live, so this also works for a run that already
  // finished, not just one still in progress.
  const resumeRunId = new URLSearchParams(window.location.search).get("run");
  if (resumeRunId) {
    state.runId = resumeRunId;
    setRunStatus(`run ${resumeRunId} — resuming…`, "pending");
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
});
