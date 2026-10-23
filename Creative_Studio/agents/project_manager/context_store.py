# Written by Anju for the Multi-Agent Creative Studio capstone (new file, not part
# of the original starter).
"""Shared context store (SPEC.md section 5A).

Single-writer, write-once JSON files in the project's GCS bucket.
Each agent folder gets an identical copy of this file; only AGENT_NAME differs.
"""
import datetime
import json
import os
import re

from google.api_core import exceptions as gexc
from google.cloud import storage

AGENT_NAME = "project_manager"  # the ONLY line that differs per agent

_PREFIX = "context"
_MAX_WORDS = int(os.getenv("CONTEXT_SUMMARY_MAX_WORDS", "150"))
_MAX_BYTES = 256 * 1024
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_client = None


def _bucket_name() -> str:
    name = os.getenv("GCS_IMAGES_BUCKET")
    if not name:
        raise RuntimeError("GCS_IMAGES_BUCKET is not set")
    return name


def _bucket():
    global _client
    if _client is None:
        _client = storage.Client()
    return _client.bucket(_bucket_name())


def save_context(content: str, summary: str, run_id: str = "dev", revision: int = 0) -> dict:
    """Saves this agent's complete output to its own context file.

    Call this exactly once, after finishing your work.

    Args:
        content: Your complete output text, exactly as you would normally write it.
        summary: A short plain-text summary (at most 150 words) of what the next step needs to know.
        run_id: The RUN_ID given in the request. Use "dev" if none was given.
        revision: 0 for the first version, 1 for the first revision, and so on.

    Returns:
        A dict with status ("ok" or "error"), and on success the context_uri and the saved summary.
    """
    try:
        revision = int(revision)
        if not run_id or run_id == "dev":
            run_id = "dev-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        if not _RUN_ID_RE.match(run_id):
            return {"status": "error", "error": "run_id may only contain letters, digits, '-' and '_'"}

        words = summary.split()
        if len(words) > _MAX_WORDS:
            summary = " ".join(words[:_MAX_WORDS]) + " ..."

        doc = {
            "agent": AGENT_NAME,
            "run_id": run_id,
            "revision": revision,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "read_from": [],
            "content": content,
            "summary": summary,
        }
        data = json.dumps(doc, ensure_ascii=False)
        if len(data.encode("utf-8")) > _MAX_BYTES:
            return {"status": "error", "error": "content is too large for a context file"}

        path = f"{_PREFIX}/{run_id}/{AGENT_NAME}/rev{revision}.json"
        blob = _bucket().blob(path)
        try:
            # write-once: fails if the file already exists
            blob.upload_from_string(data, content_type="application/json", if_generation_match=0)
        except gexc.PreconditionFailed:
            existing = json.loads(blob.download_as_text())
            if existing.get("content") != content:
                return {"status": "error",
                        "error": f"revision {revision} already exists with different content; use the next revision number"}
            # identical content: a retried call, treat as success

        return {
            "status": "ok",
            "context_uri": f"gs://{_bucket_name()}/{path}",
            "run_id": run_id,
            "revision": revision,
            "summary": summary,
        }
    except Exception as e:  # never crash the agent; report it
        return {"status": "error", "error": str(e)}


def read_context(uri: str, run_id: str) -> dict:
    """Reads another agent's saved context file (read-only).

    Args:
        uri: The context_uri given to you (gs://<bucket>/context/<run_id>/<agent>/rev<n>.json).
        run_id: The RUN_ID of the current run. The file must belong to this run.

    Returns:
        A dict with status and, on success, the file contents under "file".
    """
    try:
        bucket_prefix = f"gs://{_bucket_name()}/"
        allowed = f"{bucket_prefix}{_PREFIX}/{run_id}/"
        if (not _RUN_ID_RE.match(run_id) or not uri.startswith(allowed)
                or ".." in uri or not uri.endswith(".json")):
            return {"status": "error", "error": "this URI is not allowed for the current run"}
        blob = _bucket().blob(uri[len(bucket_prefix):])
        return {"status": "ok", "file": json.loads(blob.download_as_text())}
    except gexc.NotFound:
        return {"status": "error", "error": "context file not found"}
    except Exception as e:
        return {"status": "error", "error": str(e)}



