import pytest
from cli.config import load_config
from cli.errors import UsageError


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


def test_api_key_env_beats_config(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOQ_API_KEY", "from-env")
    cfg_file = tmp_path / "config.toml"
    _write(cfg_file, '[profiles.prod]\ngateway_url = "https://p"\napi_key = "from-config"\n')
    cfg = load_config(profile="prod", gateway_url=None, config_path=cfg_file)
    assert cfg.api_key == "from-env"


def test_api_key_from_config_when_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_API_KEY", raising=False)
    cfg_file = tmp_path / "config.toml"
    _write(cfg_file, '[profiles.prod]\ngateway_url = "https://p"\napi_key = "from-config"\n')
    cfg = load_config(profile="prod", gateway_url=None, config_path=cfg_file)
    assert cfg.api_key == "from-config"


def test_write_profile_roundtrip_sets_0600(tmp_path):
    from cli.config import write_profile
    cfg_file = tmp_path / "sub" / "config.toml"
    write_profile(cfg_file, profile="prod", gateway_url="https://gw", api_key="k")
    cfg = load_config(profile="prod", gateway_url=None, config_path=cfg_file)
    assert cfg.gateway_url == "https://gw" and cfg.api_key == "k"
    assert (cfg_file.stat().st_mode & 0o777) == 0o600


def test_write_profile_first_becomes_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_API_KEY", raising=False)
    from cli.config import write_profile
    cfg_file = tmp_path / "config.toml"
    write_profile(cfg_file, profile="prod", gateway_url="https://gw", api_key="k")
    cfg = load_config(profile=None, gateway_url=None, config_path=cfg_file)
    assert cfg.profile == "prod"


def test_missing_gateway_url_raises_usage(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_GATEWAY_URL", raising=False)
    with pytest.raises(UsageError):
        load_config(profile=None, gateway_url=None, config_path=tmp_path / "nope.toml")


def test_remove_api_key_drops_key_keeps_url_and_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_API_KEY", raising=False)
    from cli.config import write_profile, remove_api_key
    cfg_file = tmp_path / "config.toml"
    write_profile(cfg_file, profile="prod", gateway_url="https://gw", api_key="k")
    remove_api_key(cfg_file, "prod")
    cfg = load_config(profile=None, gateway_url=None, config_path=cfg_file)
    assert cfg.gateway_url == "https://gw"   # url kept
    assert cfg.api_key is None               # key gone
    assert cfg.profile == "prod"             # default kept
    assert (cfg_file.stat().st_mode & 0o777) == 0o600


def test_remove_api_key_noop_when_missing(tmp_path):
    from cli.config import remove_api_key
    remove_api_key(tmp_path / "nope.toml", "prod")  # must not raise
