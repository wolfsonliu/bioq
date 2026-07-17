import io
import zipfile
import pytest
from pathlib import Path
from types import SimpleNamespace

from cli import commands
from cli.errors import JobFailedError, NoOutputError


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
                extract=True)
    base.update(kw)
    return SimpleNamespace(**base)


def test_submit_records_and_prints(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "default_registry_path", lambda: tmp_path / "j.json")
    c = _Client()
    code = commands.cmd_submit(c, _args(set=["num_seq_per_target=2"]))
    assert code == 0
    assert c.ran[0] == "proteinmpnn-server" and c.ran[3]["num_seq_per_target"] == 2


def test_run_wait_completed_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "default_registry_path", lambda: tmp_path / "j.json")
    c = _Client(status="completed")
    code = commands.cmd_run(c, _args(wait=True, out=str(tmp_path / "out")))
    assert code == 0
    assert (tmp_path / "out" / "seqs" / "x.fa").exists()


def test_run_wait_failed_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "default_registry_path", lambda: tmp_path / "j.json")
    c = _Client(status="failed")
    with pytest.raises(JobFailedError):
        commands.cmd_run(c, _args(wait=True))


def test_run_wait_completed_but_empty_zip_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "default_registry_path", lambda: tmp_path / "j.json")
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
    monkeypatch.setattr(commands, "default_registry_path", lambda: tmp_path / "j.json")
    c = _Client()
    commands.cmd_submit(c, _args(svc="proteinmpnn", set=["n=1"]))
    assert c.ran[0] == "proteinmpnn-server"
