"""Contract smoke test: confirm bioq's GatewayClient still speaks the gateway's
/v1 API after the repo split. Opt-in — runs only when BIOQ_E2E_GATEWAY_URL is set,
so CI/offline runs skip it. Guards against silent drift between this repo and the
gateway (which now lives in a separate repo).

Auth comes from the logged-in profile (run `bioq login --oidc` or
`bioq login --client-credentials` first) or `auth_mode = "none"` for a
localhost / VPC-bypass gateway.

    BIOQ_E2E_GATEWAY_URL=https://<gateway> \
        uv run python -m pytest bioq/tests/test_contract.py -v
"""
from __future__ import annotations

import os

import pytest

from bioq.client import GatewayClient
from bioq.config import load_config

_URL = os.environ.get("BIOQ_E2E_GATEWAY_URL")

pytestmark = pytest.mark.skipif(
    not _URL, reason="set BIOQ_E2E_GATEWAY_URL to run the gateway contract test"
)


def test_list_services_returns_list():
    cfg = load_config(profile=None, gateway_url=_URL)
    client = GatewayClient.from_url(cfg.gateway_url, cfg)
    try:
        services = client.list_services()
    finally:
        client.close()
    assert isinstance(services, list)