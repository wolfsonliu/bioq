from cli import main as mainmod
from cli.config import Config
from cli.errors import AuthError, ConflictError


def test_parser_run_accepts_nested_endpoint():
    ns = mainmod.build_parser().parse_args(
        ["run", "rfdiffusion-server", "generate/motif", "--set", "n=1"])
    assert ns.svc == "rfdiffusion-server"
    assert ns.endpoint == "generate/motif"
    assert ns.set == ["n=1"]


def test_login_writes_config_0600(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr("cli.config.default_config_path", lambda: cfg)
    monkeypatch.delenv("BIOQ_API_KEY", raising=False)
    code = mainmod.main(["--gateway-url", "https://gw", "login", "--api-key", "k"])
    assert code == 0
    assert cfg.exists() and (cfg.stat().st_mode & 0o777) == 0o600
    from cli.config import load_config
    loaded = load_config(profile=None, gateway_url=None, config_path=cfg)
    assert loaded.gateway_url == "https://gw" and loaded.api_key == "k"


def test_main_maps_clierror_to_exit_code(monkeypatch):
    monkeypatch.setattr(mainmod, "load_config",
                        lambda **kw: Config(gateway_url="https://gw", api_key="k", profile=None))

    class _C:
        def list_services(self): raise AuthError("no key")
        def close(self): pass
    monkeypatch.setattr(mainmod.GatewayClient, "from_url", classmethod(lambda cls, *a, **k: _C()))
    code = mainmod.main(["services"])
    assert code == 3  # EXIT_AUTH


def test_run_treats_409_as_already_submitted(monkeypatch, tmp_path):
    monkeypatch.setattr(mainmod, "load_config",
                        lambda **kw: Config(gateway_url="https://gw", api_key="k", profile=None))
    monkeypatch.setattr("cli.commands.default_registry_path", lambda: tmp_path / "j.json")

    class _C:
        def presign(self, *a, **k): return {"exists": True, "url": None, "uri": "oss://x"}
        def run(self, *a, **k): raise ConflictError("exists")
        def get_job(self, job_id): return {"job_id": job_id, "status": "running"}
        def close(self): pass
    monkeypatch.setattr(mainmod.GatewayClient, "from_url", classmethod(lambda cls, *a, **k: _C()))
    code = mainmod.main(["submit", "svc", "ep"])
    assert code == 0
