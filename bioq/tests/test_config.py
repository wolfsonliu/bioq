import pytest

from bioq.config import load_config, write_profile
from bioq.errors import UsageError


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_flag_beats_env_and_profile(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    _write(cfg_file, '[profiles.prod]\ngateway_url = "https://from-profile"\n')
    monkeypatch.setenv("BIOQ_GATEWAY_URL", "https://from-env")
    cfg = load_config(profile="prod", gateway_url="https://from-flag",
                      config_path=cfg_file)
    assert cfg.gateway_url == "https://from-flag"


def test_env_beats_profile(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    _write(cfg_file, 'default_profile = "prod"\n[profiles.prod]\ngateway_url = "https://from-profile"\n')
    monkeypatch.setenv("BIOQ_GATEWAY_URL", "https://from-env")
    cfg = load_config(profile=None, gateway_url=None, config_path=cfg_file)
    assert cfg.gateway_url == "https://from-env"


def test_profile_used_when_no_flag_or_env(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_GATEWAY_URL", raising=False)
    cfg_file = tmp_path / "config.toml"
    _write(cfg_file, 'default_profile = "prod"\n[profiles.prod]\ngateway_url = "https://p"\n')
    cfg = load_config(profile=None, gateway_url=None, config_path=cfg_file)
    assert cfg.gateway_url == "https://p"


def test_default_auth_mode_is_none(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_GATEWAY_URL", raising=False)
    cfg_file = tmp_path / "config.toml"
    _write(cfg_file, '[profiles.prod]\ngateway_url = "https://p"\n')
    cfg = load_config(profile="prod", gateway_url=None, config_path=cfg_file)
    assert cfg.auth_mode == "none"          # no auth → VPC bypass
    assert cfg.oidc_issuer is None


def test_oidc_fields_load(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_GATEWAY_URL", raising=False)
    cfg_file = tmp_path / "config.toml"
    _write(cfg_file, '[profiles.prod]\ngateway_url = "https://p"\nauth_mode = "oidc"\n'
                     'oidc_issuer = "https://idp/realms/bioq"\noidc_client_id = "cid"\n')
    cfg = load_config(profile="prod", gateway_url=None, config_path=cfg_file)
    assert cfg.auth_mode == "oidc"
    assert cfg.oidc_issuer == "https://idp/realms/bioq"
    assert cfg.oidc_client_id == "cid"


def test_client_secret_env_beats_profile(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    _write(cfg_file, '[profiles.cc]\ngateway_url = "https://p"\nauth_mode = "client_credentials"\n'
                     'oidc_issuer = "https://idp"\noidc_client_id = "cid"\noidc_client_secret = "from-file"\n')
    monkeypatch.setenv("BIOQ_OIDC_CLIENT_SECRET", "from-env")
    cfg = load_config(profile="cc", gateway_url=None, config_path=cfg_file)
    assert cfg.oidc_client_secret == "from-env"


def test_write_profile_oidc_roundtrip_0600(tmp_path):
    cfg_file = tmp_path / "sub" / "config.toml"
    write_profile(cfg_file, profile="prod", gateway_url="https://gw",
                  auth_mode="oidc", oidc_issuer="https://idp", oidc_client_id="cid")
    cfg = load_config(profile="prod", gateway_url=None, config_path=cfg_file)
    assert cfg.gateway_url == "https://gw" and cfg.auth_mode == "oidc"
    assert cfg.oidc_issuer == "https://idp" and cfg.oidc_client_id == "cid"
    assert (cfg_file.stat().st_mode & 0o777) == 0o600


def test_write_profile_first_becomes_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_GATEWAY_URL", raising=False)
    cfg_file = tmp_path / "config.toml"
    write_profile(cfg_file, profile="prod", gateway_url="https://gw", auth_mode="oidc")
    cfg = load_config(profile=None, gateway_url=None, config_path=cfg_file)
    assert cfg.profile == "prod"


def test_missing_gateway_url_raises_usage(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_GATEWAY_URL", raising=False)
    with pytest.raises(UsageError):
        load_config(profile=None, gateway_url=None, config_path=tmp_path / "nope.toml")
