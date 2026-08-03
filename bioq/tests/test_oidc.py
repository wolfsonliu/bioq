import pytest
from bioq import oidc
from bioq.errors import AuthError


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body

    def json(self):
        return self._b


def test_start_device(monkeypatch):
    monkeypatch.setattr(oidc.httpx, "post", lambda url, **kw: _Resp(
        200, {"device_code": "d", "user_code": "UC", "verification_uri": "http://v",
              "interval": 5, "expires_in": 600}))
    out = oidc.start_device("http://dev", "cid")
    assert out["user_code"] == "UC"


def test_start_device_error(monkeypatch):
    monkeypatch.setattr(oidc.httpx, "post", lambda url, **kw: _Resp(400, {}))
    with pytest.raises(AuthError):
        oidc.start_device("http://dev", "cid")


def test_poll_token_pending_then_success(monkeypatch):
    seq = [_Resp(400, {"error": "authorization_pending"}),
           _Resp(200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 300})]
    calls = {"i": 0}

    def post(url, **kw):
        r = seq[calls["i"]]
        calls["i"] += 1
        return r

    monkeypatch.setattr(oidc.httpx, "post", post)
    monkeypatch.setattr(oidc.time, "sleep", lambda s: None)
    out = oidc.poll_token("http://tok", "cid", "dc", interval=1, expires_in=600)
    assert out["access_token"] == "AT"


def test_poll_token_error(monkeypatch):
    monkeypatch.setattr(oidc.httpx, "post", lambda url, **kw: _Resp(400, {"error": "access_denied"}))
    monkeypatch.setattr(oidc.time, "sleep", lambda s: None)
    with pytest.raises(AuthError):
        oidc.poll_token("http://tok", "cid", "dc", expires_in=600)


def test_client_credentials(monkeypatch):
    monkeypatch.setattr(oidc.httpx, "post", lambda url, **kw: _Resp(
        200, {"access_token": "CC", "expires_in": 300}))
    assert oidc.client_credentials("http://tok", "cid", "sec")["access_token"] == "CC"


def test_client_credentials_error(monkeypatch):
    monkeypatch.setattr(oidc.httpx, "post", lambda url, **kw: _Resp(401, {}))
    with pytest.raises(AuthError):
        oidc.client_credentials("http://tok", "cid", "bad")


def test_refresh(monkeypatch):
    monkeypatch.setattr(oidc.httpx, "post", lambda url, **kw: _Resp(
        200, {"access_token": "NEW", "expires_in": 300}))
    assert oidc.refresh("http://tok", "cid", "rt")["access_token"] == "NEW"


def test_refresh_error(monkeypatch):
    monkeypatch.setattr(oidc.httpx, "post", lambda url, **kw: _Resp(401, {}))
    with pytest.raises(AuthError):
        oidc.refresh("http://tok", "cid", "rt")


def test_discover(monkeypatch):
    monkeypatch.setattr(oidc.httpx, "get", lambda url, **kw: _Resp(
        200, {"token_endpoint": "http://tok", "device_authorization_endpoint": "http://dev"}))
    meta = oidc.discover("http://idp/realms/bioq")
    assert meta["token_endpoint"] == "http://tok"
