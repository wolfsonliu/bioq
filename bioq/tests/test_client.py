from dataclasses import dataclass

import httpx
import pytest

import bioq.client as client_mod
from bioq.client import GatewayClient, _BioqAuth
from bioq.errors import AuthError, ConflictError, GatewayError, NotFoundError


@dataclass
class _Cfg:
    auth_mode: str = "oidc"
    profile: str | None = "default"


def _client(monkeypatch, handler, *, token="k", auth_mode="oidc", resolve=None):
    """Build a GatewayClient wired through _BioqAuth using a MockTransport.

    Tests actually exercise the auth flow (unlike a manual header injection).
    Pass ``resolve`` for a stateful callable when a test needs the token to
    change between calls (e.g. 401 → refresh → retry).
    """
    cfg = _Cfg(auth_mode=auth_mode)
    fn = resolve if resolve is not None else (lambda _c: token)
    monkeypatch.setattr(client_mod, "resolve_bearer", fn)
    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="https://gw", transport=transport,
                        auth=_BioqAuth(cfg))
    return GatewayClient(http=http)


def test_list_services(monkeypatch):
    def handler(req):
        assert req.headers["authorization"] == "Bearer k"
        assert "x-api-key" not in req.headers
        return httpx.Response(200, json={"services": ["a", "b"]})
    assert _client(monkeypatch, handler).list_services() == ["a", "b"]


def test_no_token_sends_no_auth_header(monkeypatch):
    def handler(req):
        assert "authorization" not in req.headers
        return httpx.Response(200, json={"services": []})
    assert _client(monkeypatch, handler, token=None,
                   auth_mode="none").list_services() == []


def test_run_returns_job(monkeypatch):
    def handler(req):
        assert req.headers["x-bioagent-job-id"] == "j1"
        return httpx.Response(202, json={"job_id": "j1", "status": "running"})
    out = _client(monkeypatch, handler).run("svc", "generate/motif", "j1", {"n": 1})
    assert out["job_id"] == "j1"


def test_run_409_raises_conflict(monkeypatch):
    def handler(req):
        return httpx.Response(409, json={"detail": "exists"})
    with pytest.raises(ConflictError):
        _client(monkeypatch, handler).run("svc", "ep", "j1", {})


def test_404_raises_notfound(monkeypatch):
    def handler(req):
        return httpx.Response(404, json={"detail": "nope"})
    with pytest.raises(NotFoundError):
        _client(monkeypatch, handler).describe("nope")


def test_5xx_raises_gateway(monkeypatch):
    def handler(req):
        return httpx.Response(502, json={"detail": "downstream"})
    with pytest.raises(GatewayError):
        _client(monkeypatch, handler).get_job("j1")


# --- _BioqAuth auth-flow coverage ----------------------------------------

def test_bioq_auth_oidc_401_triggers_mark_expired_and_retries(monkeypatch):
    """oidc mode: first 401 → mark_expired(profile) + resolve_bearer again +
    retry once. Retry sends the new token; second response (200) is returned."""
    marked: list[str] = []
    monkeypatch.setattr("bioq.client.tokens.mark_expired", marked.append)
    tokens_seen: list[str] = []

    # First resolve_bearer call → "OLD"; second (after 401) → "NEW".
    it = iter(["OLD", "NEW"])

    def resolve(_c):
        return next(it)

    calls = []

    def handler(req):
        calls.append(req.headers.get("authorization"))
        tokens_seen.append(req.headers.get("authorization"))
        if len(calls) == 1:
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json={"services": ["ok"]})

    c = _client(monkeypatch, handler, resolve=resolve, auth_mode="oidc")
    assert c.list_services() == ["ok"]
    assert marked == ["default"]                # mark_expired called once
    assert tokens_seen == ["Bearer OLD", "Bearer NEW"]  # retry uses fresh token


def test_bioq_auth_oidc_double_401_raises_auth_error(monkeypatch):
    """oidc mode: if the retry also 401s, don't loop — bubble AuthError."""
    marked: list[str] = []
    monkeypatch.setattr("bioq.client.tokens.mark_expired", marked.append)

    def handler(req):
        return httpx.Response(401, json={"detail": "denied"})

    c = _client(monkeypatch, handler, token="tok", auth_mode="oidc")
    with pytest.raises(AuthError):
        c.list_services()
    # mark_expired was called once (between the two 401s); we don't retry twice
    assert marked == ["default"]


def test_bioq_auth_none_mode_does_not_retry_on_401(monkeypatch):
    """auth_mode=none: 401 is not retried (no credentials to refresh)."""
    marked: list[str] = []
    monkeypatch.setattr("bioq.client.tokens.mark_expired", marked.append)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(401, json={"detail": "denied"})

    c = _client(monkeypatch, handler, token=None, auth_mode="none")
    with pytest.raises(AuthError):
        c.list_services()
    assert len(calls) == 1        # single request, no retry
    assert marked == []           # mark_expired not touched


def test_bioq_auth_200_does_not_call_mark_expired(monkeypatch):
    """Happy path: successful response does not trigger the refresh branch."""
    marked: list[str] = []
    monkeypatch.setattr("bioq.client.tokens.mark_expired", marked.append)
    resolve_calls = []

    def resolve(_c):
        resolve_calls.append(1)
        return "AT"

    def handler(req):
        assert req.headers["authorization"] == "Bearer AT"
        return httpx.Response(200, json={"services": []})

    c = _client(monkeypatch, handler, resolve=resolve, auth_mode="oidc")
    assert c.list_services() == []
    # exactly one resolve per request (no unexpected extra calls)
    assert len(resolve_calls) == 1
    assert marked == []
