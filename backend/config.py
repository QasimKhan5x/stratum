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
    alibaba_cloud_access_key_id: str
    alibaba_cloud_access_key_secret: str
    alibaba_cloud_region: str
    tablestore_instance_name: str
    tablestore_endpoint: str
    oss_bucket: str
    oss_endpoint: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
            alibaba_cloud_access_key_id=os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", ""),
            alibaba_cloud_access_key_secret=os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", ""),
            alibaba_cloud_region=os.environ.get("ALIBABA_CLOUD_REGION", ""),
            tablestore_instance_name=os.environ.get("TABLESTORE_INSTANCE_NAME", ""),
            tablestore_endpoint=os.environ.get("TABLESTORE_ENDPOINT", ""),
            oss_bucket=os.environ.get("OSS_BUCKET", ""),
            oss_endpoint=os.environ.get("OSS_ENDPOINT", ""),
        )


settings = Settings.from_env()
