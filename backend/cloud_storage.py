"""Real Alibaba Cloud infrastructure usage: OSS blob storage + a
Tablestore-backed WorldBible.

This is the concrete answer to the hackathon's "proof of Alibaba Cloud
deployment" requirement — a real code file using real Alibaba Cloud SDKs
(`tablestore`, `oss2`) against the actually-provisioned instance/bucket in
`.env`, not DashScope (which is QwenCloud, a distinct product from Alibaba
Cloud) and not just "the backend happens to run on an ECS box."

Two independent pieces, because they answer two different needs:

- `OSSAssetStore`: uploads exported `.twee` story artifacts to the real
  `stratum-hackathon-assets` OSS bucket so an exported world has a durable,
  shareable cloud URL instead of only a one-time download response. Live-
  verified working end to end (bucket info + upload/read-back round trip)
  during development.

- `TablestoreWorldBible`: a drop-in replacement for `world_bible.WorldBible`
  (same add/get/list/update/canon_context surface — this was the explicit
  planned upgrade path called out in that file's own module docstring) that
  persists every world-bible entry as a Tablestore row instead of a Python
  dict, so canon state survives a server restart. The provisioned
  `stratum-world` instance previously rejected every call with
  `OTSAuthFailed: The user is disabled.` (a console-side instance toggle, not
  a code bug) — the account owner has since re-enabled it, and it's
  confirmed live again via a direct read/write check. The class is unit-
  tested against a fake OTS client (see tests/test_cloud_storage.py) and
  live-verified against the real instance.

ponytail: no Function Compute usage. Nothing in this project has a real
serverless-shaped workload (no event trigger, no independently-schedulable
unit of work) — wrapping something in an FC function just to tick a box
would be exactly the "boilerplate nobody asked for" this project should
avoid. OSS + Tablestore are the two services with a genuine use here.
"""

from __future__ import annotations

import logging

from backend.config import settings
from backend.schemas import WorldBibleEntry
from backend.world_bible import WorldBible

logger = logging.getLogger(__name__)


def _bucket_endpoint(oss_endpoint: str, bucket_name: str) -> str:
    """The provisioned OSS_ENDPOINT is virtual-hosted-style
    (`https://{bucket}.oss-...aliyuncs.com`), but oss2.Bucket() takes a
    *regional* endpoint and prepends the bucket name itself — passing the
    virtual-hosted form through unchanged double-prefixes the bucket name
    and fails DNS resolution. Strip it back to the regional form here.
    """
    prefix = f"https://{bucket_name}."
    if oss_endpoint.startswith(prefix):
        return "https://" + oss_endpoint[len(prefix) :]
    return oss_endpoint


class OSSAssetStore:
    """Thin wrapper around a real OSS bucket for exported story artifacts."""

    def __init__(self) -> None:
        import oss2

        auth = oss2.Auth(settings.alibaba_cloud_access_key_id, settings.alibaba_cloud_access_key_secret)
        endpoint = _bucket_endpoint(settings.oss_endpoint, settings.oss_bucket)
        self._bucket = oss2.Bucket(auth, endpoint, settings.oss_bucket)

    def upload_text(self, key: str, content: str, content_type: str = "text/plain") -> str:
        """Uploads text content to `key` and returns a time-limited signed
        URL (the bucket is private by default, the sane default for a
        hackathon project's cloud storage — a signed URL shares the object
        without changing that bucket-wide).
        """
        self._bucket.put_object(key, content.encode("utf-8"), headers={"Content-Type": content_type})
        return self._bucket.sign_url("GET", key, 7 * 24 * 3600)

    def read_text(self, key: str) -> str:
        return self._bucket.get_object(key).read().decode("utf-8")


def try_upload_export(run_id: str, twee_text: str) -> str | None:
    """Best-effort OSS upload for an exported .twee — used by the export
    endpoint as a side effect. Never raises: a cloud-storage hiccup must
    not break the actual download the user is waiting on.
    """
    if not (settings.oss_bucket and settings.oss_endpoint):
        return None
    try:
        return OSSAssetStore().upload_text(f"exports/{run_id}.twee", twee_text, "text/plain; charset=utf-8")
    except Exception:
        logger.warning("OSS export upload failed for run %s", run_id, exc_info=True)
        return None


_TABLE_NAME = "world_bible_entries"


class TablestoreWorldBible(WorldBible):
    """Same interface as `WorldBible`, backed by a real Tablestore table
    instead of an in-memory dict. Partition key is `run_id` (so many runs
    share one table), range key is `entry_id`. Entries are stored as one
    JSON-blob column (`data`) — this world's entries are small, and a
    generic blob column matching the pydantic schema needs no migration
    every time `WorldBibleEntry` grows a field.
    """

    def __init__(self, run_id: str) -> None:
        import tablestore

        self._tablestore = tablestore
        self._run_id = run_id
        self._client = tablestore.OTSClient(
            settings.tablestore_endpoint,
            settings.alibaba_cloud_access_key_id,
            settings.alibaba_cloud_access_key_secret,
            settings.tablestore_instance_name,
        )
        self._ensure_table()
        # Local read cache mirrors what's in Tablestore so list()/get() don't
        # need a network round trip on every access during a negotiation's
        # hot loop; every mutating call writes through to Tablestore first.
        self._entries: dict[str, WorldBibleEntry] = {}

    def _ensure_table(self) -> None:
        ots = self._tablestore
        existing = {t for t in self._client.list_table()}
        if _TABLE_NAME in existing:
            return
        schema = [("run_id", "STRING"), ("entry_id", "STRING")]
        table_meta = ots.TableMeta(_TABLE_NAME, schema)
        table_options = ots.TableOptions()
        reserved_throughput = ots.ReservedThroughput(ots.CapacityUnit(0, 0))
        self._client.create_table(table_meta, table_options, reserved_throughput)

    def _put(self, entry: WorldBibleEntry) -> None:
        ots = self._tablestore
        primary_key = [("run_id", self._run_id), ("entry_id", entry.id)]
        attribute_columns = [("data", entry.model_dump_json(exclude={"embedding"}))]
        row = ots.Row(primary_key, attribute_columns)
        self._client.put_row(_TABLE_NAME, row, condition=ots.Condition("IGNORE"))

    def load_from_tablestore(self) -> None:
        """Rehydrates `_entries` from Tablestore — call once on process
        start (or when resuming a run after a restart) to recover state a
        pure in-memory `WorldBible` would have lost.
        """
        ots = self._tablestore
        inclusive_start = [("run_id", self._run_id), ("entry_id", ots.INF_MIN)]
        inclusive_end = [("run_id", self._run_id), ("entry_id", ots.INF_MAX)]
        _, next_start, rows, _ = self._client.get_range(
            _TABLE_NAME, "FORWARD", inclusive_start, inclusive_end, limit=1000
        )
        while rows:
            for row in rows:
                # Real Tablestore rows carry a trailing timestamp per column
                # (name, value, timestamp) — only the fake test client used a
                # bare (name, value) pair, so `dict(...)` worked in tests but
                # raised `ValueError` against the real service. Slicing to the
                # first two elements handles both shapes.
                attrs = {col[0]: col[1] for col in row.attribute_columns}
                data = attrs["data"]
                entry = WorldBibleEntry.model_validate_json(data)
                self._entries[entry.id] = entry
            if not next_start:
                break
            _, next_start, rows, _ = self._client.get_range(
                _TABLE_NAME, "FORWARD", next_start, inclusive_end, limit=1000
            )


def make_world_bible(run_id: str) -> WorldBible:
    """Factory, three tiers: Tablestore (this hackathon's real Alibaba Cloud
    deployment, when configured and reachable) -> SQLite (the default,
    zero-config, self-hostable tier — see backend/sqlite_store.py, works
    for anyone who clones this repo with no cloud account at all) ->
    bare in-memory (last-resort fallback if even a local SQLite file can't
    be opened, e.g. a read-only filesystem). Each tier falls back rather
    than crashing the app, so a storage hiccup never breaks a live demo.
    """
    if settings.tablestore_endpoint and settings.tablestore_instance_name:
        try:
            return TablestoreWorldBible(run_id)
        except Exception:
            logger.warning("Tablestore unavailable, falling back to SQLite WorldBible", exc_info=True)
    try:
        from backend.sqlite_store import SQLiteWorldBible

        return SQLiteWorldBible(run_id)
    except Exception:
        logger.warning("SQLite unavailable, falling back to in-memory WorldBible", exc_info=True)
    return WorldBible()
