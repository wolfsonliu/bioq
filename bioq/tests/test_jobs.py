import pytest

from bioq.errors import GatewayError
from bioq.jobs import (TERMINAL, history_path, poll, read_history, record_job,
                       record_status, record_submit)


class _Client:
    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.calls = 0

    def get_job(self, job_id):
        self.calls += 1
        s = self._statuses.pop(0)
        if isinstance(s, Exception):
            raise s
        return {"job_id": job_id, "status": s}


def test_poll_returns_on_terminal():
    c = _Client(["running", "running", "completed"])
    out = poll(c, "j1", interval=0, timeout=10, max_transient=3)
    assert out["status"] == "completed"
    assert c.calls == 3


def test_poll_tolerates_transient_then_succeeds():
    c = _Client([GatewayError("429"), "completed"])
    out = poll(c, "j1", interval=0, timeout=10, max_transient=3)
    assert out["status"] == "completed"


def test_poll_bails_after_max_transient():
    c = _Client([GatewayError("x")] * 5)
    with pytest.raises(GatewayError):
        poll(c, "j1", interval=0, timeout=10, max_transient=3)


def test_terminal_set():
    assert TERMINAL == {"completed", "failed", "cancelled"}


def test_record_job_appends(tmp_path):
    reg = tmp_path / "jobs.json"
    record_job(reg, job_id="j1", svc="s", endpoint="e")
    record_job(reg, job_id="j2", svc="s", endpoint="e")
    import json
    rows = json.loads(reg.read_text())
    assert [r["job_id"] for r in rows] == ["j1", "j2"]


def test_submit_and_status_events_roundtrip(tmp_path):
    p = tmp_path / "jobs.jsonl"
    record_submit(p, job_id="j1", svc="s", endpoint="e", profile="prod",
                  params={"num_seq_per_target": 2, "long": "x" * 300},
                  files={"pdb": "x.pdb"})
    record_status(p, job_id="j1", status="completed", output_dir="out", n_files=3)
    events = read_history(p, limit=10)
    assert [e["type"] for e in events] == ["submit", "status"]
    submit = events[0]
    assert submit["job_id"] == "j1" and submit["svc"] == "s"
    assert submit["params"]["num_seq_per_target"] == 2
    assert submit["params"]["long"].endswith("…") and len(submit["params"]["long"]) <= 201
    assert submit["files"] == {"pdb": "x.pdb"}
    status = events[1]
    assert status["status"] == "completed" and status["files"] == 3
    assert status["output_dir"] == "out"


def test_read_history_tolerates_malformed_line(tmp_path):
    p = tmp_path / "jobs.jsonl"
    p.write_text('{"type": "submit", "job_id": "ok"}\nGARBAGE\n', encoding="utf-8")
    assert [e["job_id"] for e in read_history(p)] == ["ok"]


def test_read_history_missing_file_returns_empty(tmp_path):
    assert read_history(tmp_path / "missing.jsonl") == []


def test_history_path_uses_state_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert str(history_path()) == str(tmp_path / "bioq" / "jobs.jsonl")


def test_history_file_is_0600(tmp_path):
    p = tmp_path / "jobs.jsonl"
    record_submit(p, job_id="j1", svc="s", endpoint="e")
    assert (p.stat().st_mode & 0o777) == 0o600
