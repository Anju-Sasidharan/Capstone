# Written by Anju for the Multi-Agent Creative Studio capstone (new file, not part
# of the original starter).
"""Local tools for the Creative Director.

start_run       creates the run ID and stores it in the session state.
get_run_state   rebuilds the run's latest context-file URIs and image URIs from
                the bucket (read-only), so the orchestrator never has to rely on
                its conversation memory, which event compaction may have
                summarized away.
read_context    read-only access to one context file of the current run.
"""
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from google.adk.tools import ToolContext

try:
    from . import context_store as _cs
except ImportError:  # direct execution fallback
    import context_store as _cs

logger = logging.getLogger("ai_creative_studio.run_tools")

_NAME_RE = re.compile(r"^context/(?P<run>[^/]+)/(?P<agent>[^/]+)/rev(?P<rev>\d+)\.json$")
_IMAGE_RE = re.compile(r"IMAGE\s+(\d+)\s*:\s*(gs://\S+)")


def start_run(tool_context: ToolContext) -> dict:
    """Create the run ID for this campaign. Call it exactly once, at the start."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = f"run-{stamp}-{uuid.uuid4().hex[:4]}"
    tool_context.state["run_id"] = run_id
    return {"run_id": run_id}


def read_context(uri: str, run_id: str) -> dict:
    """Read one context file of the current run (read-only).

    Args:
        uri: gs:// URI of a context file for this run.
        run_id: the current run ID.
    """
    return _cs.read_context(uri, run_id)


def latest_by_agent(object_names):
    """Pure helper: {agent: (revision, object_name)} for the highest revision of each agent."""
    latest = {}
    for name in object_names:
        m = _NAME_RE.match(name)
        if not m:
            continue
        agent, rev = m.group("agent"), int(m.group("rev"))
        if agent not in latest or rev > latest[agent][0]:
            latest[agent] = (rev, name)
    return latest


def parse_images(text: str) -> dict:
    """Pure helper: {"1": "gs://...", ...} from the 'IMAGE n: gs://...' lines (last one wins)."""
    return {n: uri for n, uri in _IMAGE_RE.findall(text or "")}


def get_run_state(tool_context: ToolContext, run_id: str = "") -> dict:
    """Return the current run's ID, the latest context-file URI and revision of every
    agent, and the current image URIs. Use it whenever you cannot see these in your
    history, and always before the final steps. Never ask the user for them.

    Args:
        run_id: optional; defaults to the run ID stored when start_run was called.
    """
    run_id = run_id or tool_context.state.get("run_id", "")
    if not run_id:
        return {"status": "error", "error": "No run_id in the session. Call start_run first."}
    bucket_name = os.getenv("GCS_IMAGES_BUCKET", "")
    if not bucket_name:
        return {"status": "error", "error": "GCS_IMAGES_BUCKET is not set."}
    try:
        from google.cloud import storage

        client = storage.Client()
        names = [b.name for b in client.list_blobs(bucket_name, prefix=f"context/{run_id}/")]
        latest = latest_by_agent(names)
        result = {
            "status": "ok",
            "run_id": run_id,
            "latest": {a: f"gs://{bucket_name}/{n}" for a, (_, n) in latest.items()},
            "revisions": {a: r for a, (r, _) in latest.items()},
            "images": {},
        }
        if "designer" in latest:
            import json

            blob = client.bucket(bucket_name).blob(latest["designer"][1])
            data = json.loads(blob.download_as_text())
            result["images"] = parse_images(data.get("content", ""))
        return result
    except Exception as exc:  # never crash the run; tell the model what failed
        logger.warning("get_run_state failed: %s", exc)
        return {"status": "error", "error": f"Could not read the run state: {exc}"}
