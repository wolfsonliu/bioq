import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from bioq import commands
from bioq.errors import JobFailedError, NoOutputError


class _Client:
    def __init__(self, **overrides):
        self._o = overrides
        self.ran = None

    def list_services(self): return ["proteinmpnn-server"]
    def describe(self, svc): return {"service": svc, "manifest": {}}
    def run(self, svc, ep, job_id, body):
        self.ran = (svc, ep, job_id, body)
        return {"job_id": job_id, "status": "running"}
    def get_job(self, job_id):
        return {"job_id": job_id, "status": self._o.get("status", "completed")}
    def cancel(self, job_id): return {"job_id": job_id, "status": "cancelled"}
    def download(self, job_id, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("seqs/x.fa", ">a\nMK\n")
        Path(dest).write_bytes(buf.getvalue())
        return dest


def _args(**kw):
    base = dict(svc="proteinmpnn-server", endpoint="design", file=[], set=[],
                set_json=[], wait=False, output="json", out=None, job_id="j1",
                timeout=None, extract=True)
    base.update(kw)
    return SimpleNamespace(**base)


def test_submit_records_and_prints(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "history_path", lambda: tmp_path / "jobs.jsonl")
    c = _Client()
    code = commands.cmd_submit(c, _args(set=["num_seq_per_target=2"]))
    assert code == 0
    assert c.ran[0] == "proteinmpnn-server" and c.ran[3]["num_seq_per_target"] == 2


def test_run_wait_completed_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "history_path", lambda: tmp_path / "jobs.jsonl")
    c = _Client(status="completed")
    code = commands.cmd_run(c, _args(wait=True, out=str(tmp_path / "out")))
    assert code == 0
    assert (tmp_path / "out" / "seqs" / "x.fa").exists()


def test_run_wait_failed_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "history_path", lambda: tmp_path / "jobs.jsonl")
    c = _Client(status="failed")
    with pytest.raises(JobFailedError):
        commands.cmd_run(c, _args(wait=True))


def test_run_wait_completed_but_empty_zip_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "history_path", lambda: tmp_path / "jobs.jsonl")
    c = _Client(status="completed")
    def _empty(job_id, dest):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(buf.getvalue())
        return dest
    c.download = _empty
    with pytest.raises(NoOutputError):
        commands.cmd_run(c, _args(wait=True, out=str(tmp_path / "out")))


def test_canonical_svc_appends_suffix():
    assert commands._canonical_svc("proteinmpnn") == "proteinmpnn-server"
    assert commands._canonical_svc("proteinmpnn-server") == "proteinmpnn-server"


def test_services_strips_server_suffix(capsys):
    import json

    class _C:
        def list_services(self): return ["proteinmpnn-server", "ensemble-server"]
    commands.cmd_services(_C(), _args(output="json"))
    assert json.loads(capsys.readouterr().out) == ["proteinmpnn", "ensemble"]


def test_run_normalizes_short_svc(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "history_path", lambda: tmp_path / "jobs.jsonl")
    c = _Client()
    commands.cmd_submit(c, _args(svc="proteinmpnn", set=["n=1"]))
    assert c.ran[0] == "proteinmpnn-server"


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
    commands.cmd_describe(_DescClient(), _args(svc="proteinmpnn", output="pretty", endpoint=None))
    out = capsys.readouterr().out
    assert "--file pdb=<path>" in out
    assert "--set num_seq_per_target=<integer>" in out
    assert "pdb_uri" not in out                    # companion field hidden
    assert "bioq run proteinmpnn design" in out    # copy-paste example
    assert "/api/tasks" not in out                 # not a raw path dump


def test_describe_json_is_raw(capsys):
    import json
    commands.cmd_describe(_DescClient(), _args(svc="proteinmpnn", output="json", endpoint=None))
    assert json.loads(capsys.readouterr().out) == _DESCRIBE


def test_describe_endpoint_filter(capsys):
    commands.cmd_describe(_DescClient(),
                          _args(svc="proteinmpnn", output="pretty", endpoint="design"))
    out = capsys.readouterr().out
    assert "design" in out and "--file pdb=<path>" in out


def test_describe_unknown_endpoint(capsys):
    commands.cmd_describe(_DescClient(),
                          _args(svc="proteinmpnn", output="pretty", endpoint="nope"))
    assert "unknown endpoint 'nope'" in capsys.readouterr().out


def test_describe_empty_manifest_prints_cold_start_hint(capsys):
    class C:
        def describe(self, svc):
            return {"service": svc, "manifest": {}}
    commands.cmd_describe(C(), _args(svc="proteinmpnn", output="pretty", endpoint=None))
    out = capsys.readouterr().out
    assert "no runnable task endpoints" in out
    assert "cold-start" in out
    assert "--wait" in out


def test_describe_wait_polls_until_endpoints(capsys, monkeypatch):
    monkeypatch.setattr(commands, "DESCRIBE_WAIT_INTERVAL_S", 0.0)
    calls = []

    class C:
        def describe(self, svc):
            calls.append(svc)
            return _DESCRIBE if len(calls) > 1 else {"service": svc, "manifest": {}}

    commands.cmd_describe(C(), _args(svc="proteinmpnn", output="pretty",
                                     endpoint=None, wait=True, timeout=5.0))
    assert len(calls) == 2
    assert "--file pdb=<path>" in capsys.readouterr().out


def test_describe_wait_timeout_returns_last_and_hints(capsys, monkeypatch):
    monkeypatch.setattr(commands, "DESCRIBE_WAIT_INTERVAL_S", 0.0)

    class C:
        def describe(self, svc):
            return {"service": svc, "manifest": {}}

    code = commands.cmd_describe(C(), _args(svc="proteinmpnn", output="pretty",
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

    commands.cmd_describe(C(), _args(svc="proteinmpnn", output="json",
                                     endpoint=None, wait=True, timeout=5.0))
    assert len(calls) == 1


# --- _poll_timeout precedence + validation ---

def test_poll_timeout_defaults_to_module_constant(monkeypatch):
    monkeypatch.delenv("BIOQ_POLL_TIMEOUT", raising=False)
    assert commands._poll_timeout(_args()) == commands.POLL_TIMEOUT_S


def test_poll_timeout_env_overrides_default(monkeypatch):
    monkeypatch.setenv("BIOQ_POLL_TIMEOUT", "42")
    assert commands._poll_timeout(_args()) == 42.0


def test_poll_timeout_cli_beats_env(monkeypatch):
    monkeypatch.setenv("BIOQ_POLL_TIMEOUT", "42")
    assert commands._poll_timeout(_args(timeout=7.5)) == 7.5


def test_poll_timeout_nonpositive_raises_usage_error():
    from bioq.errors import UsageError
    with pytest.raises(UsageError):
        commands._poll_timeout(_args(timeout=0))
    with pytest.raises(UsageError):
        commands._poll_timeout(_args(timeout=-1))


# --- _describe_timeout precedence + validation ---

def test_describe_timeout_defaults_to_module_constant(monkeypatch):
    monkeypatch.delenv("BIOQ_DESCRIBE_TIMEOUT", raising=False)
    assert commands._describe_timeout(_args()) == commands.DESCRIBE_WAIT_TIMEOUT_S


def test_describe_timeout_env_overrides_default(monkeypatch):
    monkeypatch.setenv("BIOQ_DESCRIBE_TIMEOUT", "42")
    assert commands._describe_timeout(_args()) == 42.0


def test_describe_timeout_cli_beats_env(monkeypatch):
    monkeypatch.setenv("BIOQ_DESCRIBE_TIMEOUT", "42")
    assert commands._describe_timeout(_args(timeout=7.5)) == 7.5


def test_describe_timeout_nonpositive_raises_usage_error():
    from bioq.errors import UsageError
    with pytest.raises(UsageError):
        commands._describe_timeout(_args(timeout=0))
    with pytest.raises(UsageError):
        commands._describe_timeout(_args(timeout=-1))


# --- cmd_status --timeout wiring ---

def test_cmd_status_no_timeout_is_single_shot(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_POLL_TIMEOUT", raising=False)
    called_poll = []
    monkeypatch.setattr(commands, "poll",
                        lambda *a, **k: called_poll.append((a, k)) or {})
    c = _Client(status="running")
    commands.cmd_status(c, _args(job_id="j1"))
    assert called_poll == []  # no polling when timeout unset


def test_cmd_status_timeout_polls_when_not_terminal(tmp_path, monkeypatch):
    monkeypatch.delenv("BIOQ_POLL_TIMEOUT", raising=False)
    monkeypatch.setattr(commands, "history_path", lambda: tmp_path / "jobs.jsonl")
    poll_calls = []

    def fake_poll(client, job_id, *, interval, timeout):
        poll_calls.append((job_id, timeout))
        return {"job_id": job_id, "status": "completed"}

    monkeypatch.setattr(commands, "poll", fake_poll)
    c = _Client(status="running")
    commands.cmd_status(c, _args(job_id="j1", timeout=30.0))
    assert poll_calls == [("j1", 30.0)]


def test_cmd_status_timeout_skips_poll_when_already_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "history_path", lambda: tmp_path / "jobs.jsonl")
    called_poll = []
    monkeypatch.setattr(commands, "poll",
                        lambda *a, **k: called_poll.append((a, k)) or {})
    c = _Client(status="completed")
    commands.cmd_status(c, _args(job_id="j1", timeout=30.0))
    assert called_poll == []  # already terminal → don't poll


def test_submit_records_history_event(tmp_path, monkeypatch):
    import json
    p = tmp_path / "jobs.jsonl"
    monkeypatch.setattr(commands, "history_path", lambda: p)
    c = _Client()
    commands.cmd_submit(c, _args(set=["num_seq_per_target=2"]))
    events = [json.loads(ln) for ln in p.read_text().splitlines()]
    assert events[0]["type"] == "submit"
    assert events[0]["svc"] == "proteinmpnn-server"
    assert events[0]["params"] == {"num_seq_per_target": 2}


def test_run_wait_completed_records_status_event(tmp_path, monkeypatch):
    import json
    p = tmp_path / "jobs.jsonl"
    monkeypatch.setattr(commands, "history_path", lambda: p)
    c = _Client(status="completed")
    commands.cmd_run(c, _args(wait=True, out=str(tmp_path / "out")))
    events = [json.loads(ln) for ln in p.read_text().splitlines()]
    assert events[-1]["type"] == "status"
    assert events[-1]["status"] == "completed"
    assert events[-1]["output_dir"] == str(tmp_path / "out")
    assert events[-1]["files"] == 1


def test_cmd_recent_pretty_and_json(tmp_path, monkeypatch, capsys):
    import json
    p = tmp_path / "jobs.jsonl"
    monkeypatch.setattr(commands, "history_path", lambda: p)
    commands.cmd_submit(_Client(), _args(set=["n=1"]))
    # pretty
    commands.cmd_recent(_args(output="pretty"))
    out = capsys.readouterr().out
    assert "submit" in out and "proteinmpnn-server" in out
    # json
    commands.cmd_recent(_args(output="json"))
    events = json.loads(capsys.readouterr().out)
    assert isinstance(events, list) and events[0]["type"] == "submit"
