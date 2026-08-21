import json
import pytest
from types import SimpleNamespace

from bioq import describe
from bioq.errors import UsageError


def _args(**kw):
    base = dict(svc="proteinmpnn-server", endpoint="design", file=[], set=[],
                set_json=[], wait=False, output="json", out=None, job_id="j1",
                timeout=None)
    base.update(kw)
    return SimpleNamespace(**base)


_DESCRIBE = {
    "service": "proteinmpnn-server",
    "manifest": {"endpoints": [
        {"path": "/api/design", "summary": "sync", "request_fields": []},
        {"path": "/api/tasks/design", "summary": "Sequence design", "request_fields": [
            {"name": "pdb", "type": "file", "is_file": True, "required": False, "default": None},
            {"name": "pdb_uri", "type": "string", "is_file": False, "required": False, "default": None},
            {"name": "num_seq_per_target", "type": "integer", "is_file": False,
             "required": False, "default": 8},
        ]},
    ]},
    "openapi": {},
}


class _DescClient:
    def describe(self, svc): return _DESCRIBE


def test_describe_pretty_is_cli_shaped(capsys):
    describe.cmd_describe(_DescClient(), _args(svc="proteinmpnn", output="pretty", endpoint=None))
    out = capsys.readouterr().out
    assert "--file pdb=<path>" in out
    assert "--set num_seq_per_target=<integer>" in out
    assert "pdb_uri" not in out
    assert "bioq run proteinmpnn design" in out
    assert "/api/tasks" not in out


def test_describe_json_is_raw(capsys):
    describe.cmd_describe(_DescClient(), _args(svc="proteinmpnn", output="json", endpoint=None))
    assert json.loads(capsys.readouterr().out) == _DESCRIBE


def test_describe_endpoint_filter(capsys):
    describe.cmd_describe(_DescClient(),
                          _args(svc="proteinmpnn", output="pretty", endpoint="design"))
    out = capsys.readouterr().out
    assert "design" in out and "--file pdb=<path>" in out


def test_describe_unknown_endpoint(capsys):
    describe.cmd_describe(_DescClient(),
                          _args(svc="proteinmpnn", output="pretty", endpoint="nope"))
    assert "unknown endpoint 'nope'" in capsys.readouterr().out


def test_describe_empty_manifest_prints_cold_start_hint(capsys):
    class C:
        def describe(self, svc):
            return {"service": svc, "manifest": {}}
    describe.cmd_describe(C(), _args(svc="proteinmpnn", output="pretty", endpoint=None))
    out = capsys.readouterr().out
    assert "no runnable task endpoints" in out
    assert "cold-start" in out
    assert "--wait" in out


def test_describe_wait_polls_until_endpoints(capsys, monkeypatch):
    monkeypatch.setattr(describe, "DESCRIBE_WAIT_INTERVAL_S", 0.0)
    calls = []

    class C:
        def describe(self, svc):
            calls.append(svc)
            return _DESCRIBE if len(calls) > 1 else {"service": svc, "manifest": {}}

    describe.cmd_describe(C(), _args(svc="proteinmpnn", output="pretty",
                                     endpoint=None, wait=True, timeout=5.0))
    assert len(calls) == 2
    assert "--file pdb=<path>" in capsys.readouterr().out


def test_describe_wait_timeout_returns_last_and_hints(capsys, monkeypatch):
    monkeypatch.setattr(describe, "DESCRIBE_WAIT_INTERVAL_S", 0.0)

    class C:
        def describe(self, svc):
            return {"service": svc, "manifest": {}}

    code = describe.cmd_describe(C(), _args(svc="proteinmpnn", output="pretty",
                                             endpoint=None, wait=True, timeout=0.05))
    assert code == 0
    out = capsys.readouterr().out
    assert "no runnable task endpoints" in out
    assert "--wait" in out


def test_describe_json_ignores_wait_single_fetch(capsys):
    calls = []

    class C:
        def describe(self, svc):
            calls.append(svc)
            return _DESCRIBE

    describe.cmd_describe(C(), _args(svc="proteinmpnn", output="json",
                                     endpoint=None, wait=True, timeout=5.0))
    assert len(calls) == 1


# --- _describe_timeout precedence + validation ---

def test_describe_timeout_defaults_to_module_constant(monkeypatch):
    monkeypatch.delenv("BIOQ_DESCRIBE_TIMEOUT", raising=False)
    assert describe._describe_timeout(_args()) == describe.DESCRIBE_WAIT_TIMEOUT_S


def test_describe_timeout_env_overrides_default(monkeypatch):
    monkeypatch.setenv("BIOQ_DESCRIBE_TIMEOUT", "42")
    assert describe._describe_timeout(_args()) == 42.0


def test_describe_timeout_cli_beats_env(monkeypatch):
    monkeypatch.setenv("BIOQ_DESCRIBE_TIMEOUT", "42")
    assert describe._describe_timeout(_args(timeout=7.5)) == 7.5


def test_describe_timeout_nonpositive_raises_usage_error():
    with pytest.raises(UsageError):
        describe._describe_timeout(_args(timeout=0))
    with pytest.raises(UsageError):
        describe._describe_timeout(_args(timeout=-1))
