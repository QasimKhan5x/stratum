"""Scene illustration via qwen-image-2.0-pro.

Per stratum-project-overview.md's "five distinct QwenCloud model roles"
claim and the locked demo script's "the illustration populates the hex"
beat (stratum-demo-and-verification.md, 1:00-2:00). One image per admitted
scene, not per proposal or per seed entry — kept to what the demo actually
shows, not maximized for its own sake.

Image generation is not exposed on DashScope's OpenAI-compatible endpoint
(backend.models_client) — it requires the native DashScope SDK's
MultiModalConversation. This is the one agent module in the codebase not
built on the OpenAI-compatible client for that reason.
"""

from __future__ import annotations

import dashscope
from dashscope import MultiModalConversation

from backend.config import settings

# Match the same Singapore/international region as models_client's
# DASHSCOPE_BASE_URL — the API key is region-specific, and the native SDK
# defaults to the China endpoint unless told otherwise.
dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"

_MODEL = "qwen-image-2.0-pro"

_STYLE_SUFFIX = (
    " Cyanotype blueprint style: monochrome deep-blue wash, white linework, "
    "high contrast, technical-illustration feel evoking old tide charts and "
    "ship blueprints."
)


def generate_scene_image(summary: str) -> str | None:
    """Generate one illustration for an admitted scene.

    Args:
        summary: the admitted WorldBibleEntry's summary — kept short
            deliberately, since the image prompt doesn't need the full
            scene text to produce a legible, on-theme illustration.

    Returns:
        The generated image's URL, or None if generation failed. None is a
        valid, expected outcome here (not raised as an exception): a failed
        illustration is not worth losing the scene or the run over — the
        negotiation and its admitted canon are the load-bearing output,
        the image is supplementary.
    """
    try:
        response = MultiModalConversation.call(
            api_key=settings.dashscope_api_key,
            model=_MODEL,
            messages=[{"role": "user", "content": [{"text": summary + _STYLE_SUFFIX}]}],
            result_format="message",
            stream=False,
            watermark=False,
            size="1328*1328",
        )
        content = response.output.choices[0].message.content
        for part in content:
            if isinstance(part, dict) and part.get("image"):
                return part["image"]
        return None
    except Exception:  # noqa: BLE001 - see docstring: a missing image is never fatal
        return None
