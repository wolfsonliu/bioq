import time

import pytest

from bioq import auth
from bioq.config import Config
from bioq.errors import AuthError


def _cfg(**kw):
    base = {"gateway_url": "https://gw", "profile": "default", "auth_mode": "none"}
    base.update(kw)
    return Config(**base)


def test_none_mode_returns_none():
    assert auth.resolve_bearer(_cfg(auth_mode="none")) is None


def test_oidc_not_logged_in_raises(monkeypatch):
    monkeypatch.setattr(auth.tokens, "load_tokens", lambda p: None)
    with pytest.raises(AuthError):
        auth.resolve_bearer(_cfg(auth_mode="oidc"))


def test_oidc_valid_cache_returns_access_token(monkeypatch):
    monkeypatch.setattr(auth.tokens, "load_tokens", lambda p: {
        "access_token": "AT", "expires_at": time.time() + 100})
    monkeypatch.setattr(auth.tokens, "is_expired", lambda t: False)
    assert auth.resolve_bearer(_cfg(auth_mode="oidc")) == "AT"


def test_oidc_expired_refreshes(monkeypatch):
    monkeypatch.setattr(auth.tokens, "load_tokens", lambda p: {
        "access_token": "OLD", "refresh_token": "RT",
        "token_endpoint": "http://tok", "client_id": "cid", "expires_at": 0})
    monkeypatch.setattr(auth.tokens, "is_expired", lambda t: True)
    monkeypatch.setattr(auth.oidc, "refresh",
                        lambda te, cid, rt: {"access_token": "NEW", "expires_in": 300})
    saved = {}
    monkeypatch.setattr(auth.tokens, "save_tokens",
                        lambda p, tok, **kw: saved.update(tok=tok))
    assert auth.resolve_bearer(_cfg(auth_mode="oidc")) == "NEW"
    assert saved["tok"]["access_token"] == "NEW"


def test_oidc_expired_no_refresh_token_raises(monkeypatch):
    monkeypatch.setattr(auth.tokens, "load_tokens", lambda p: {"access_token": "OLD"})
    monkeypatch.setattr(auth.tokens, "is_expired", lambda t: True)
    with pytest.raises(AuthError):
        auth.resolve_bearer(_cfg(auth_mode="oidc"))


def test_client_credentials_mints_token(monkeypatch):
    monkeypatch.setattr(auth.oidc, "discover", lambda iss: {"token_endpoint": "http://tok"})
    monkeypatch.setattr(auth.oidc, "client_credentials",
                        lambda te, cid, sec, **kw: {"access_token": "CC"})
    cfg = _cfg(auth_mode="client_credentials", oidc_issuer="https://idp",
               oidc_client_id="cid", oidc_client_secret="sec")
    assert auth.resolve_bearer(cfg) == "CC"


def test_client_credentials_missing_config_raises():
    cfg = _cfg(auth_mode="client_credentials", oidc_issuer="https://idp")
    with pytest.raises(AuthError):
        auth.resolve_bearer(cfg)
