import httpx
import pytest
from bioq.client import GatewayClient
from bioq.errors import AuthError, NotFoundError, GatewayError, ConflictError


def _client(handler, token="k"):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="https://gw", transport=transport)
    return GatewayClient(http=http, token=token)


def test_list_services():
    def handler(req):
        assert req.headers["authorization"] == "Bearer k"
        assert "x-api-key" not in req.headers
        return httpx.Response(200, json={"services": ["a", "b"]})
    assert _client(handler).list_services() == ["a", "b"]


def test_no_token_sends_no_auth_header():
    def handler(req):
        assert "authorization" not in req.headers
        return httpx.Response(200, json={"services": []})
    assert _client(handler, token=None).list_services() == []


def test_run_returns_job():
    def handler(req):
        assert req.headers["x-bioagent-job-id"] == "j1"
        return httpx.Response(202, json={"job_id": "j1", "status": "running"})
    out = _client(handler).run("svc", "generate/motif", "j1", {"n": 1})
    assert out["job_id"] == "j1"


def test_run_409_raises_conflict():
    def handler(req):
        return httpx.Response(409, json={"detail": "exists"})
    with pytest.raises(ConflictError):
        _client(handler).run("svc", "ep", "j1", {})


def test_401_raises_auth():
    def handler(req):
        return httpx.Response(401, json={"detail": "no key"})
    with pytest.raises(AuthError):
        _client(handler).list_services()


def test_404_raises_notfound():
    def handler(req):
        return httpx.Response(404, json={"detail": "nope"})
    with pytest.raises(NotFoundError):
        _client(handler).describe("nope")


def test_5xx_raises_gateway():
    def handler(req):
        return httpx.Response(502, json={"detail": "downstream"})
    with pytest.raises(GatewayError):
        _client(handler).get_job("j1")
