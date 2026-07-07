"""Sync client for the local `mcp_world_bible_server.py` stdio MCP server.

The one caller (backend.admission_gate) needs a plain synchronous function
it can call from a worker thread (it's already invoked via
`asyncio.to_thread` from backend.negotiation) — this module hides the
async MCP session machinery behind `call_tool()`.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_SERVER_SCRIPT = str(Path(__file__).resolve().with_name("mcp_world_bible_server.py"))

# Generous relative to the sub-millisecond math the server actually does,
# but tight relative to the rest of the negotiation pipeline (LLM calls in
# this same code path routinely take tens of seconds) — this exists to
# fail fast on a genuinely wedged subprocess rather than hang a scene.
_CALL_TIMEOUT_SECONDS = 15.0


class McpToolError(RuntimeError):
    """Raised for any failure calling an MCP tool: the server process
    failed to start, the call timed out, or it returned an error/malformed
    response. Callers should catch this and fall back rather than let it
    propagate — see admission_gate._embedding_screen.
    """


async def _call_tool_async(tool_name: str, arguments: dict) -> list[dict]:
    params = StdioServerParameters(command=sys.executable, args=[_SERVER_SCRIPT])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                tool_name,
                arguments,
                read_timeout_seconds=timedelta(seconds=_CALL_TIMEOUT_SECONDS),
            )
            if result.isError:
                raise McpToolError(f"MCP tool '{tool_name}' returned an error: {result.content!r}")
            if result.structuredContent is None:
                raise McpToolError(f"MCP tool '{tool_name}' returned no structured content.")
            # FastMCP wraps a bare list return value as {"result": [...]}.
            return result.structuredContent.get("result", [])


def call_tool(tool_name: str, arguments: dict) -> list[dict]:
    """Synchronously call `tool_name` on the world-bible MCP server,
    spawning a fresh stdio subprocess for this one call.

    ponytail: one fresh subprocess per call (instead of one persistent
    session reused across calls) trades ~100-200ms of process-startup
    latency per admission check for zero session-lifecycle/concurrency
    bookkeeping — negligible next to the multi-second-to-minutes LLM calls
    already in this path, and safe when multiple runs negotiate
    concurrently (backend.runs._RUNS can hold several at once). Upgrade
    path if per-call latency ever actually matters: one persistent
    subprocess per backend process, guarded by a lock.

    Raises McpToolError on any failure. Callers must handle that (see
    admission_gate._embedding_screen's fallback).
    """
    try:
        return asyncio.run(_call_tool_async(tool_name, arguments))
    except McpToolError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize every failure mode (spawn, transport, timeout) to one type
        raise McpToolError(f"MCP call to '{tool_name}' failed: {exc}") from exc
