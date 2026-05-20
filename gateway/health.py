"""
gateway/health.py — SaaS-mode dependency health checks.

Returns a structured health dict consumed by:
  - gateway/health_server.py  (HTTP GET /health response body)
  - ECS container healthcheck (via curl -sf http://localhost:8080/health)
  - ALB target group health checks

Response schema:
  {
    "status": "ok" | "degraded",
    "storage": "neon" | "error",
    "skills": "s3" | "error",
    "details": {                  # present only on "degraded"
      "storage_error": "<msg>",
      "skills_error": "<msg>"
    }
  }

Design decisions:
  - Both checks run concurrently (asyncio.gather) to keep the /health response
    fast (<1s target) even when one dependency is slow.
  - Each check has a hard 5s timeout so a hung Neon or S3 endpoint can't block
    an ALB health check for the full 10s ALB timeout window.
  - Errors are caught and reported as "degraded" — never crash the health server.
  - boto3 is lazy-imported: this module is safe to import in non-SaaS mode where
    boto3 may not be installed. The skill check simply reports "s3_skipped" when
    HERMES_MODE is not "saas".
  - The NeonBackend ping uses a lightweight SELECT 1 via the existing connection
    pool. It does NOT call get_backend() (which initialises a full pool) — it
    uses a fresh single connection with a short timeout to avoid pool state
    bleed between health probes.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Hard timeout for each dependency check in seconds.
_CHECK_TIMEOUT = 5.0


async def _check_neon() -> dict[str, Any]:
    """
    Check Neon PostgreSQL reachability.

    Opens a single asyncpg connection using the same DSN resolution as
    NeonBackend (env var → Secrets Manager). Does not initialise the
    application-level connection pool — this is a lightweight probe only.

    Returns: {"storage": "neon"} on success, {"storage": "error", "storage_error": msg} on failure.
    """
    try:
        import asyncpg  # noqa: PLC0415

        from hermes_storage.neon_backend import _resolve_dsn  # noqa: PLC0415

        dsn = _resolve_dsn(os.environ.get("NEON_DATABASE_URL"))
        # Use a single throw-away connection — not the app pool.
        conn = await asyncio.wait_for(
            asyncpg.connect(dsn, command_timeout=_CHECK_TIMEOUT),
            timeout=_CHECK_TIMEOUT,
        )
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        return {"storage": "neon"}
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}"
        logger.warning("health: Neon check failed — %s", msg)
        return {"storage": "error", "storage_error": msg}


def _check_s3_sync() -> dict[str, Any]:
    """
    Check S3 skills bucket reachability (synchronous — runs in a thread).

    Uses head_bucket to verify the bucket exists and is accessible via the
    task role credentials. Does not list or read objects — read-only metadata
    probe only.

    Returns: {"skills": "s3"} on success, {"skills": "error", "skills_error": msg} on failure.
    """
    bucket = os.environ.get("S3_SKILLS_BUCKET", "hermes-saas-skills")
    try:
        import boto3  # noqa: PLC0415
        from botocore.config import Config  # noqa: PLC0415

        s3 = boto3.client(
            "s3",
            region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            config=Config(
                connect_timeout=int(_CHECK_TIMEOUT),
                read_timeout=int(_CHECK_TIMEOUT),
                retries={"max_attempts": 1},
            ),
        )
        s3.head_bucket(Bucket=bucket)
        return {"skills": "s3"}
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}"
        logger.warning("health: S3 check failed (bucket=%s) — %s", bucket, msg)
        return {"skills": "error", "skills_error": msg}


async def health_check() -> dict[str, Any]:
    """
    Run Neon + S3 health checks concurrently.

    Returns a health dict with "status" = "ok" | "degraded".
    Called by gateway/health_server.py on every GET /health request.
    """
    mode = os.environ.get("HERMES_MODE", "local")

    if mode != "saas":
        # Non-SaaS mode: skip cloud checks, always report healthy.
        return {"status": "ok", "storage": "sqlite", "skills": "local"}

    # Run both checks concurrently with individual timeouts.
    neon_task = asyncio.create_task(_check_neon())
    s3_task = asyncio.create_task(
        asyncio.to_thread(_check_s3_sync)
    )

    neon_result, s3_result = await asyncio.gather(neon_task, s3_task)

    result: dict[str, Any] = {}
    result.update(neon_result)
    result.update(s3_result)

    # Aggregate status: "ok" only when all checks pass.
    errors = {k: v for k, v in result.items() if k.endswith("_error")}
    result["status"] = "degraded" if errors else "ok"

    if errors:
        result["details"] = errors

    return result
