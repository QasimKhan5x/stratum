"""Generates docs/architecture.png: a static, professionally rendered
replacement for the README's old Mermaid flowchart.

PNG only, deliberately: Graphviz's SVG output embeds the Alibaba Cloud/
generic node icons via <image xlink:href="..."> pointing at their *absolute
local filesystem path* inside this repo's .venv, not inlined image data. An
SVG built here would render with broken icons for anyone else, so it's not a
portable artifact — don't resurrect it without first base64-inlining the
icon images into the SVG.

Built with the `diagrams` package (Graphviz under the hood) specifically so
the Alibaba Cloud pieces (ECS, OSS, Tablestore) can use real, official
provider icons instead of generic boxes — see README.md's Architecture
section and DEVPOST_SUBMISSION.md's Links section for why that credit
matters for hackathon judging. Every node/edge below mirrors the real
backend layout (verified against backend/main.py, orchestrator.py,
negotiation.py, admission_gate.py, world_bible.py, cloud_storage.py,
mcp_world_bible_server.py/_client.py, models_client.py, agents/*.py);
nothing invented.

Layout notes (v3 — rewritten after v2 still had long diagonal edges
crossing large empty regions to reach a far-flung AGENTS cluster and a fan
of near-duplicate edges converging on the LLM layer, which read as "arrows
into empty space"): agents now live *inside* the BACKEND cluster (they're
backend/agents/*.py in the real tree, so this isn't a stretch) instead of a
distant separate cluster, and the five separate "-> chat model" edges are
collapsed into one representative edge with a label naming all the callers.
That shortens every remaining cross-cluster edge to a short, direct hop.

Color notes: v1/v2 used the frontend's own dark "cyanotype" theme, but a
big diagram is not a small UI accent — the same near-black bg + neon edges
that work for the live app read as harsh/glary as one big image on a plain
white GitHub page, and thin edges against a dark busy background are hard
to track by eye regardless of how bright you make them. Switched to a
light, plain, high-contrast diagramming theme instead: dark line work reads
clearly against light fills at any size or zoom, which is why virtually
every standard cloud-architecture-diagram tool defaults to it.

Usage: source .venv/bin/activate && python scripts/generate_architecture_diagram.py
Requires the Graphviz system binary (`brew install graphviz` on macOS).
"""

from __future__ import annotations

import os

from diagrams import Cluster, Diagram, Edge
from diagrams.alibabacloud.compute import ECS
from diagrams.alibabacloud.storage import OSS, OTS
from diagrams.generic.compute import Rack
from diagrams.generic.database import SQL
from diagrams.programming.framework import FastAPI
from diagrams.programming.language import JavaScript, Python

INK = "#1a2333"  # near-black navy text/line ink, not pure #000 (softer)
CANVAS = "#fbfcfe"  # page background: barely-tinted white, not stark #fff
PANEL_OUTER = "#eef2f9"  # ECS/Frontend + Backend cluster fill
PANEL_INNER = "#e2e9f5"  # nested/satellite cluster fill (one step deeper)
BORDER = "#9fb1cf"  # quiet cluster borders
FLOW = "#2b6cd4"  # primary data-flow edges (the one saturated accent, used sparingly)
FLOW_SOFT = "#6b7fa3"  # secondary/less-central edges
DASHED = "#94a3bb"  # "concurrent, non-blocking" annotations
ALT_A = "#c1622a"  # Tablestore / MCP-fallback path (warm accent)
ALT_B = "#1f8f6e"  # OSS export path (second accent, kept distinct from ALT_A)

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

GRAPH_ATTR = {
    "bgcolor": CANVAS,
    "fontcolor": INK,
    "fontname": "Helvetica-Bold",
    "fontsize": "26",
    "label": "Stratum \u2014 multi-agent creative negotiation architecture",
    "labelloc": "t",
    "pad": "0.5",
    "nodesep": "0.6",
    "ranksep": "0.8",
    "splines": "spline",
    "concentrate": "false",
    "rankdir": "LR",
    "dpi": "110",
}
NODE_ATTR = {
    "fontname": "Helvetica",
    "fontsize": "13",
    "fontcolor": INK,
}
EDGE_ATTR = {
    "fontname": "Helvetica",
    "fontsize": "11",
    "fontcolor": FLOW_SOFT,
    "color": FLOW_SOFT,
    "penwidth": "1.8",
    "arrowsize": "0.9",
}


def _cluster_attr(bgcolor: str, fontsize: str = "13") -> dict:
    return {
        "bgcolor": bgcolor,
        "pencolor": BORDER,
        "fontcolor": INK,
        "fontname": "Helvetica-Bold",
        "fontsize": fontsize,
        "style": "rounded",
        "margin": "16",
    }


def build(outformat: str) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with Diagram(
        name="",
        filename=os.path.join(OUT_DIR, "architecture"),
        outformat=outformat,
        show=False,
        graph_attr=GRAPH_ATTR,
        node_attr=NODE_ATTR,
        edge_attr=EDGE_ATTR,
    ):
        with Cluster("ALIBABA CLOUD ECS  (ecs.e-c1m1.large, ap-southeast-1)", graph_attr=_cluster_attr(PANEL_OUTER)):
            ecs = ECS("nginx + uvicorn\n(systemd-managed)")
            ui = JavaScript("frontend/\nCyanotype hex map +\ndebate panel (D3.js over SSE)")
            ecs >> Edge(color=FLOW_SOFT, style="dashed", label="serves") >> ui

        # Agents live *inside* Backend (they're backend/agents/*.py for real)
        # so every edge here is a short, direct hop instead of a long-haul
        # line out to a separate, distant cluster.
        with Cluster("BACKEND  \u2014  FastAPI app (backend/)", graph_attr=_cluster_attr(PANEL_OUTER)):
            api = FastAPI("main.py\nAPI layer")
            orch = Python("orchestrator.py\nscene loop")
            seed = Python("seed.py\nworld foundation")
            neg = Python("negotiation.py\nthesis \u2192 antithesis \u2192\njudging \u2192 synthesis")
            gate = Python("admission_gate.py\nembedding screen +\nLLM contradiction check")
            side_tasks = Python("baseline.py + illustrator.py")
            mcp_client = Python("mcp_world_bible_client.py")

            api >> Edge(color=FLOW) >> orch
            orch >> Edge(color=FLOW) >> seed >> Edge(color=FLOW) >> neg
            neg >> Edge(color=FLOW) >> gate >> Edge(color=FLOW, label="check_contradiction") >> mcp_client
            orch >> Edge(color=DASHED, style="dashed", label="concurrent") >> side_tasks

        with Cluster("LOCAL MCP SERVER  \u2014  stdio subprocess", graph_attr=_cluster_attr(PANEL_INNER)):
            mcp_server = Python("mcp_world_bible_server.py\ncheck_contradiction \u00b7 search_world_bible")

        with Cluster("CANON STORAGE  \u2014  world_bible.py", graph_attr=_cluster_attr(PANEL_INNER)):
            sqlite = SQL("SQLite (default)")
            tablestore = OTS("Alibaba Cloud Tablestore\n(when configured)")

        with Cluster("OBJECT STORAGE  \u2014  export uploads", graph_attr=_cluster_attr(PANEL_INNER)):
            oss = OSS("Alibaba Cloud OSS\nstratum-hackathon-assets\n.twee exports, signed URL")

        with Cluster(
            "LLM LAYER  \u2014  any OpenAI-compatible provider\n(defaults to DashScope / QwenCloud)",
            graph_attr=_cluster_attr(PANEL_OUTER),
        ):
            # Rack stands in for "external API service" here — there's no
            # neutral AI/LLM icon in this icon set, and using an Alibaba- or
            # OpenAI-specific one would misrepresent this cluster's whole
            # point: it's any OpenAI-compatible provider, DashScope is only
            # the default.
            chat = Rack("chat model(s)\nqwen3.7-max / qwen3.7-plus /\nqwen3.6-flash via openai SDK")
            embed = Rack("embedding model\ntext-embedding-v4")
            image = Rack("qwen-image-2.0-pro\n(native DashScope SDK \u2014\nnot provider-swappable)")

        # --- cross-cluster wiring: every remaining line is a short, direct hop ---
        ui >> Edge(color=FLOW, label="SSE: DebateEvent stream", dir="both") >> api
        mcp_client >> Edge(color=FLOW) >> mcp_server
        mcp_client >> Edge(color=ALT_A, style="dashed", label="fallback: in-process") >> gate
        gate >> Edge(color=FLOW, label="default") >> sqlite
        gate >> Edge(color=ALT_A, label="when configured") >> tablestore
        api >> Edge(color=ALT_B, label="GET /api/export") >> oss

        neg >> Edge(color=FLOW, label="specialists, judges, arbiter,\nseed, baseline all call") >> chat
        gate >> Edge(color=FLOW_SOFT, label="check_contradiction") >> embed
        side_tasks >> Edge(color=FLOW_SOFT, label="illustrator") >> image


if __name__ == "__main__":
    build("png")
    print(f"Wrote {OUT_DIR}/architecture.png")
