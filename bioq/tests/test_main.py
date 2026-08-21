from bioq import main as mainmod
from bioq.config import Config
from bioq.errors import AuthError, ConflictError


def test_parser_run_accepts_nested_endpoint():
    ns = mainmod.build_parser().parse_args(
        ["run", "rfdiffusion-server", "generate/motif", "--set", "n=1"])
    assert ns.svc == "rfdiffusion-server"
    assert ns.endpoint == "generate/motif"
    assert ns.set == ["n=1"]


def test_parser_describe_accepts_wait_and_timeout():
    ns = mainmod.build_parser().parse_args(
        ["describe", "diffdock", "--wait", "--timeout", "42"])
    assert ns.svc == "diffdock"
    assert ns.wait is True
    assert ns.timeout == 42.0


def test_login_oidc_device_flow(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr("bioq.config.default_config_path", lambda: cfg)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # token cache lands here
    from bioq import oidc, tokens
    monkeypatch.setattr(oidc, "discover", lambda issuer: {
        "device_authorization_endpoint": "http://dev", "token_endpoint": "http://tok"})
    monkeypatch.setattr(oidc, "start_device", lambda dep, cid: {
        "device_code": "d", "user_code": "UC", "verification_uri": "http://v",
        "interval": 1, "expires_in": 600})
    monkeypatch.setattr(oidc, "poll_token", lambda *a, **k: {
        "access_token": "AT", "refresh_token": "RT", "expires_in": 300})
    saved = {}
    monkeypatch.setattr(tokens, "save_tokens",
                        lambda profile, tok, **kw: saved.update(profile=profile, tok=tok))
    code = mainmod.main(["--gateway-url", "https://gw", "login", "--oidc",
                         "--issuer", "https://idp", "--client-id", "cid"])
    assert code == 0
    assert cfg.exists() and (cfg.stat().st_mode & 0o777) == 0o600
    from bioq.config import load_config
    loaded = load_config(profile=None, gateway_url=None, config_path=cfg)
    assert loaded.gateway_url == "https://gw" and loaded.auth_mode == "oidc"
    assert loaded.oidc_issuer == "https://idp" and loaded.oidc_client_id == "cid"
    assert saved["tok"]["access_token"] == "AT"


def test_main_maps_clierror_to_exit_code(monkeypatch):
    monkeypatch.setattr(mainmod, "load_config",
                        lambda **kw: Config(gateway_url="https://gw", profile=None))

    class _C:
        def list_services(self): raise AuthError("no key")
        def close(self): pass
    monkeypatch.setattr(mainmod.GatewayClient, "from_url", classmethod(lambda cls, *a, **k: _C()))
    code = mainmod.main(["services"])
    assert code == 3  # EXIT_AUTH


def test_run_treats_409_as_already_submitted(monkeypatch, tmp_path):
    monkeypatch.setattr(mainmod, "load_config",
                        lambda **kw: Config(gateway_url="https://gw", profile=None))
    monkeypatch.setattr("bioq.commands.default_registry_path", lambda: tmp_path / "j.json")

    class _C:
        def prepare_upload(self, *a, **k): return {"exists": True, "put_url": None, "uri": "oss://x"}
        def run(self, *a, **k): raise ConflictError("exists")
        def get_job(self, job_id): return {"job_id": job_id, "status": "running"}
        def close(self): pass
    monkeypatch.setattr(mainmod.GatewayClient, "from_url", classmethod(lambda cls, *a, **k: _C()))
    code = mainmod.main(["submit", "svc", "ep"])
    assert code == 0


def test_409_on_status_is_gateway_error_not_ok(monkeypatch):
    monkeypatch.setattr(mainmod, "load_config",
                        lambda **kw: Config(gateway_url="https://gw", profile=None))

    class _C:
        def get_job(self, job_id): raise ConflictError("conflict")
        def close(self): pass
    monkeypatch.setattr(mainmod.GatewayClient, "from_url",
                        classmethod(lambda cls, *a, **k: _C()))
    code = mainmod.main(["status", "j1"])
    assert code == 7  # EXIT_GATEWAY — a 409 on `status` is NOT "already submitted"


def _fake_services(monkeypatch):
    monkeypatch.setattr(mainmod, "load_config",
                        lambda **kw: Config(gateway_url="https://gw", profile=None))

    class _C:
        def list_services(self): return ["svc-a"]
        def close(self): pass
    monkeypatch.setattr(mainmod.GatewayClient, "from_url", classmethod(lambda cls, *a, **k: _C()))


def test_output_json_after_subcommand(monkeypatch, capsys):
    _fake_services(monkeypatch)
    assert mainmod.main(["services", "--output", "json"]) == 0
    import json
    assert json.loads(capsys.readouterr().out) == ["svc-a"]


def test_output_json_before_subcommand(monkeypatch, capsys):
    _fake_services(monkeypatch)
    assert mainmod.main(["--output", "json", "services"]) == 0
    import json
    assert json.loads(capsys.readouterr().out) == ["svc-a"]


def test_default_output_is_pretty(monkeypatch, capsys):
    _fake_services(monkeypatch)
    assert mainmod.main(["services"]) == 0
    assert capsys.readouterr().out.strip() == "svc-a"


def test_gateway_url_after_subcommand():
    ns = mainmod.build_parser().parse_args(["services", "--gateway-url", "https://x"])
    assert ns.gateway_url == "https://x"


def test_login_client_credentials(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr("bioq.config.default_config_path", lambda: cfg)
    from bioq import oidc
    monkeypatch.setattr(oidc, "discover", lambda issuer: {"token_endpoint": "http://tok"})
    code = mainmod.main(["--gateway-url", "https://gw", "login", "--client-credentials",
                         "--issuer", "https://idp", "--client-id", "cid",
                         "--client-secret", "sec"])
    assert code == 0
    from bioq.config import load_config
    loaded = load_config(profile=None, gateway_url=None, config_path=cfg)
    assert loaded.auth_mode == "client_credentials" and loaded.oidc_client_id == "cid"
