"""Fire-and-forget postback of a finished/failed job result to the FE.

Called from the worker (jobs.run_extraction) the moment a job completes. By design
this NEVER raises: a dead or in-progress FE endpoint must not break extraction.
The result is always still retrievable via GET /jobs/{id} regardless of callback
success.

Config (env, read at call time so tests/redeploys can override without restart):
  CALLBACK_URL      target endpoint. Empty/unset = callback disabled (skip silently).
                    Set it in deploy/.env to the FE endpoint to enable postback.
  CALLBACK_TOKEN    if set, sent as the `X-Callback-Token` header. Empty = no header.
  CALLBACK_TIMEOUT_S  per-request timeout in seconds (default 10).
"""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("extractor-callback")


def _config() -> tuple[str, str, float]:
    # No hardcoded default: callback is opt-in via the CALLBACK_URL env var.
    url = os.getenv("CALLBACK_URL", "").strip()
    token = os.getenv("CALLBACK_TOKEN", "").strip()
    timeout = float(os.getenv("CALLBACK_TIMEOUT_S", "10"))
    return url, token, timeout


def post_result(payload: dict) -> None:
    """POST `payload` (the full job result) to the FE callback. Fire-and-forget."""
    url, token, timeout = _config()
    if not url:
        log.debug("CALLBACK_URL empty — callback disabled, skipping job %s", payload.get("job_id"))
        return

    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Callback-Token"] = token

    # Fire-and-forget: ONE POST, log the outcome, swallow every failure so a dead
    # or in-progress FE endpoint can never disrupt the worker / job completion.
    job_id = payload.get("job_id")
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            # Delivered but rejected (e.g. FE endpoint still in-progress → 404/503).
            log.warning("callback to %s returned %s for job %s", url, resp.status_code, job_id)
        else:
            log.info("callback delivered to %s (%s) for job %s", url, resp.status_code, job_id)
    except Exception as e:
        # Not delivered at all (DNS/TLS/timeout/connection refused). Intentionally
        # broad: nothing from the network layer may propagate to the worker.
        log.warning("callback to %s failed for job %s: %s", url, job_id, e)
