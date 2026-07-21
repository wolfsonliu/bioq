"""Contract smoke test: confirm bioq's GatewayClient still speaks the gateway's
/v1 API after the repo split. Opt-in — runs only when BIOQ_E2E_GATEWAY_URL is set,
so CI/offline runs skip it. Guards against silent drift between this repo and the
gateway (which now lives in a separate repo).

    BIOQ_E2E_GATEWAY_URL=https://<gateway> [BIOQ_API_KEY=<KEY>] \
        uv run python -m pytest bioq/tests/test_contract.py -v
"""
from __future__ import annotations

import os

import pytest

from bioq.client import GatewayClient

_URL = os.environ.get("BIOQ_E2E_GATEWAY_URL")

pytestmark = pytest.mark.skipif(
    not _URL, reason="set BIOQ_E2E_GATEWAY_URL to run the gateway contract test"
)


def test_list_services_returns_list():
    client = GatewayClient.from_url(_URL, os.environ.get("BIOQ_API_KEY"))
    try:
        services = client.list_services()
    finally:
        client.close()
    assert isinstance(services, list)
