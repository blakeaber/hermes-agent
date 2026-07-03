"""
tests/gateway/test_health_server.py — API-audit P6

Guards that the ECS *container* liveness probe targets the dependency-free
/healthz route (not the dependency-coupled /health), so a transient Neon/S3
blip cannot recycle an otherwise-healthy task.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_TF_MAIN = (
    Path(__file__).resolve().parents[2]
    / "infra" / "terraform" / "hermes-fargate" / "main.tf"
)


def test_ecs_healthcheck_targets_healthz():
    """The container healthCheck curls /healthz (pure liveness), not /health."""
    text = _TF_MAIN.read_text()
    # locate the healthCheck command line
    cmd_lines = [
        ln for ln in text.splitlines()
        if "curl" in ln and "localhost:8080" in ln
    ]
    assert cmd_lines, "no curl-based healthCheck command found in main.tf"
    joined = "\n".join(cmd_lines)
    assert "http://localhost:8080/healthz" in joined
    # must NOT target the dependency-coupled /health route
    assert "8080/health\"" not in joined
    assert "8080/health " not in joined


@pytest.mark.asyncio
async def test_healthz_is_pure_liveness():
    """/healthz returns 200 even if the dependency health_check blows up."""
    from gateway.health_server import _handle_healthz

    with patch(
        "gateway.health.health_check",
        new=AsyncMock(side_effect=Exception("neon down")),
    ):
        response = await _handle_healthz(MagicMock())

    assert response.status == 200
