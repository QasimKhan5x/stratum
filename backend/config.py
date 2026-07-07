"""Loads environment variables into a single Settings object.

Reads from a `.env` file at the repo root (via python-dotenv) plus the
real process environment. `.env` is never committed (see .gitignore).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    dashscope_api_key: str
    # Both default to the DashScope (QwenCloud) endpoint this project ships
    # with — see backend/models_client.py's docstring — but any OpenAI-
    # compatible provider (OpenAI itself, a local vLLM/Ollama server, etc.)
    # works by overriding these two env vars; nothing else in the codebase
    # is DashScope-specific.
    llm_base_url: str
    llm_api_key: str
    alibaba_cloud_access_key_id: str
    alibaba_cloud_access_key_secret: str
    alibaba_cloud_region: str
    tablestore_instance_name: str
    tablestore_endpoint: str
    oss_bucket: str
    oss_endpoint: str

    @classmethod
    def from_env(cls) -> "Settings":
        dashscope_api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        return cls(
            dashscope_api_key=dashscope_api_key,
            llm_base_url=os.environ.get(
                "LLM_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            ),
            # Falls back to DASHSCOPE_API_KEY so every existing .env keeps
            # working unchanged; set LLM_API_KEY instead when pointing
            # LLM_BASE_URL at a different provider.
            llm_api_key=os.environ.get("LLM_API_KEY", dashscope_api_key),
            alibaba_cloud_access_key_id=os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", ""),
            alibaba_cloud_access_key_secret=os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", ""),
            alibaba_cloud_region=os.environ.get("ALIBABA_CLOUD_REGION", ""),
            tablestore_instance_name=os.environ.get("TABLESTORE_INSTANCE_NAME", ""),
            tablestore_endpoint=os.environ.get("TABLESTORE_ENDPOINT", ""),
            oss_bucket=os.environ.get("OSS_BUCKET", ""),
            oss_endpoint=os.environ.get("OSS_ENDPOINT", ""),
        )


settings = Settings.from_env()
