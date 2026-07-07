"""Thin wrapper around the `openai` SDK pointed at DashScope's
OpenAI-compatible endpoint.

DashScope (QwenCloud) exposes an OpenAI-compatible `compatible-mode/v1`
API — the standard `openai` Python SDK works unmodified by swapping
`base_url` and `api_key`. No DashScope-specific SDK is used.
"""

from __future__ import annotations

import contextvars
import json
from contextlib import contextmanager

from openai import OpenAI

from backend.config import settings

DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# Confirmed-live QwenCloud model names, mapped to the role that calls them.
# See stratum-architecture-plan.md for why each role uses this specific model.
MODEL_ROLES: dict[str, str] = {
    "seed": "qwen3.7-max",
    "arbiter": "qwen3.7-max",
    "specialist": "qwen3.7-plus",
    "judge": "qwen3.6-flash",
    "image": "qwen-image-2.0-pro",
    "embedding": "text-embedding-v4",
}

# Thinking mode only matters for the two roles doing deep reasoning
# (seed's world-foundation step, arbiter's final synthesis).
_THINKING_CAPABLE_ROLES = {"seed", "arbiter"}

# A hard timeout matters here: with no bound, a stalled DashScope request
# blocks its worker thread (and therefore that step of the negotiation)
# indefinitely instead of failing fast enough to retry or surface an error.
# 180s, not a tighter value: observed real latencies during testing ranged
# up to ~180s for a single legitimate (non-hung) seed/synthesis call under
# load, so anything much lower produces false-positive timeouts on slow-but-
# healthy requests. max_retries=1 (down from the SDK's default of 2) bounds
# the worst case for one call to two attempts (~6 minutes) rather than three.
_client = OpenAI(
    base_url=DASHSCOPE_BASE_URL,
    api_key=settings.dashscope_api_key,
    timeout=180.0,
    max_retries=1,
)

# Token/call accounting, attributed back to whichever Run is currently
# "active" without threading a Run object through every specialist/judge/
# arbiter/baseline call site — chat()/chat_json() is the one chokepoint
# every model call already passes through. Relies on asyncio.to_thread
# copying the current context into its worker thread, so this stays
# correctly scoped even with multiple runs in flight concurrently.
_current_run: contextvars.ContextVar = contextvars.ContextVar("current_run", default=None)
_usage_bucket: contextvars.ContextVar[str] = contextvars.ContextVar("usage_bucket", default="stratum")


@contextmanager
def track_run(run, bucket: str = "stratum"):
    """Attribute every chat()/chat_json() call made inside this block to
    `run`'s token/call counters (see backend.runs.Run), split into the
    "stratum" or "baseline" bucket. Used by backend.orchestrator to scope
    the negotiation loop and the concurrent baseline call separately.
    """
    run_token = _current_run.set(run)
    bucket_token = _usage_bucket.set(bucket)
    try:
        yield
    finally:
        _usage_bucket.reset(bucket_token)
        _current_run.reset(run_token)


def _record_usage(response) -> None:
    run = _current_run.get()
    if run is None:  # e.g. calls made outside any tracked run (health checks, tests)
        return
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "total_tokens", 0) or 0
    if _usage_bucket.get() == "baseline":
        run.baseline_tokens += tokens
        run.baseline_calls += 1
    else:
        run.total_tokens += tokens
        run.total_calls += 1


def chat(role: str, messages: list[dict], thinking: bool = False) -> str:
    """Send a chat completion request for the given agent role.

    Args:
        role: one of MODEL_ROLES's keys, selects which model handles the call.
        messages: OpenAI-style chat messages (list of {"role", "content"} dicts).
        thinking: request DashScope's thinking mode. Only has an effect for
            roles in _THINKING_CAPABLE_ROLES ("seed", "arbiter"); silently
            ignored otherwise, since not every model on this endpoint supports it.

    Returns:
        The assistant's reply text (message.content of the first choice).
    """
    if role not in MODEL_ROLES:
        raise ValueError(f"Unknown model role '{role}'. Expected one of {list(MODEL_ROLES)}.")

    model = MODEL_ROLES[role]
    kwargs: dict = {"model": model, "messages": messages}
    if thinking and role in _THINKING_CAPABLE_ROLES:
        kwargs["extra_body"] = {"enable_thinking": True}

    response = _client.chat.completions.create(**kwargs)
    _record_usage(response)
    return response.choices[0].message.content or ""


def chat_json(role: str, messages: list[dict], thinking: bool = False) -> dict:
    """Like `chat`, but requests DashScope's JSON-object response mode and
    parses the result into a dict.

    Every agent in the negotiation loop needs structured output (a proposal,
    a critique, a score, a synthesized entry) rather than free text, so this
    is the primary entry point agent-logic code should call.

    DashScope does not support thinking mode together with structured JSON
    response_format, so `thinking` is accepted for call-site compatibility
    but deliberately ignored here. Free-text chat() remains the only wrapper
    that may request thinking.
    """
    if role not in MODEL_ROLES:
        raise ValueError(f"Unknown model role '{role}'. Expected one of {list(MODEL_ROLES)}.")

    model = MODEL_ROLES[role]
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }

    response = _client.chat.completions.create(**kwargs)
    _record_usage(response)
    raw = response.choices[0].message.content or "{}"
    return _parse_json(raw)


def _parse_json(raw: str) -> dict:
    """Parse a model's JSON reply, tolerating a stray markdown code fence
    even though every prompt instructs 'JSON only, no code fences' — models
    occasionally add one anyway, and failing hard on that would be a needless
    single-point-of-failure for the whole negotiation loop.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model response was not valid JSON: {raw[:500]!r}") from exc


def embed(text: str) -> list[float]:
    """Compute an embedding vector for `text` via the "embedding" model role
    (text-embedding-v4). Used both to populate WorldBibleEntry.embedding at
    creation time and by the admission gate's similarity screen.
    """
    response = _client.embeddings.create(model=MODEL_ROLES["embedding"], input=text)
    return response.data[0].embedding


def list_models() -> list[str]:
    """List model IDs visible to this API key. Used by the /api/models health check."""
    response = _client.models.list()
    return [model.id for model in response.data]
