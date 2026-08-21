import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from bioq import commands
from bioq.errors import JobFailedError, NoOutputError, UsageError


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


def test_extract_download_rejects_path_traversal(tmp_path):
    class C:
        def download(self, job_id, dest):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("../evil.txt", "x")
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(buf.getvalue())
            return dest

    with pytest.raises(NoOutputError):
        commands._extract_download(C(), "j1", tmp_path / "out")


def test_validate_job_id_accepts_hex_rejects_traversal():
    assert commands._validate_job_id("abc123_-") == "abc123_-"
    with pytest.raises(UsageError):
        commands._validate_job_id("../etc")
    with pytest.raises(UsageError):
        commands._validate_job_id("a/b")
    with pytest.raises(UsageError):
        commands._validate_job_id("")


def test_resolve_timeout_precedence_and_validation(monkeypatch):
    from bioq.errors import UsageError
    monkeypatch.setenv("BIOQ_X", "42")
    assert commands._resolve_timeout(_args(timeout=7.5),
                                     env_var="BIOQ_X", default=1.0) == 7.5
    assert commands._resolve_timeout(_args(), env_var="BIOQ_X", default=1.0) == 42.0
    monkeypatch.delenv("BIOQ_X", raising=False)
    assert commands._resolve_timeout(_args(), env_var="BIOQ_X", default=1.0) == 1.0
    with pytest.raises(UsageError):
        commands._resolve_timeout(_args(timeout=0), env_var="BIOQ_X", default=1.0)
