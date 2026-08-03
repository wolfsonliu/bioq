import time

from bioq import tokens


def test_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    tokens.save_tokens("default",
                       {"access_token": "AT", "refresh_token": "RT", "expires_in": 300},
                       token_endpoint="http://tok", client_id="cid")
    p = tokens.tokens_path("default")
    assert p.exists()
    assert (p.stat().st_mode & 0o777) == 0o600
    t = tokens.load_tokens("default")
    assert t["access_token"] == "AT"
    assert t["refresh_token"] == "RT"
    assert t["token_endpoint"] == "http://tok"
    assert t["client_id"] == "cid"
    assert not tokens.is_expired(t)
    tokens.clear_tokens("default")
    assert tokens.load_tokens("default") is None


def test_is_expired():
    assert tokens.is_expired({"expires_at": time.time() - 1})
    assert tokens.is_expired({})  # missing expiry -> treated as expired
    assert not tokens.is_expired({"expires_at": time.time() + 100})
