import pytest

from bioq.errors import GatewayError
from bioq.jobs import (TERMINAL, history_path, poll, read_history,
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


def test_append_event_caps_to_history_max(tmp_path, monkeypatch):
    import bioq.jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "_HISTORY_MAX_EVENTS", 3)
    p = tmp_path / "jobs.jsonl"
    for i in range(5):
        record_submit(p, job_id=f"j{i}", svc="s", endpoint="e")
    assert [e["job_id"] for e in read_history(p, limit=100)] == ["j2", "j3", "j4"]


def test_read_history_limit_zero_returns_empty(tmp_path):
    p = tmp_path / "jobs.jsonl"
    record_submit(p, job_id="j1", svc="s", endpoint="e")
    assert read_history(p, limit=0) == []
    assert len(read_history(p, limit=1)) == 1


def test_read_history_skips_non_object_lines(tmp_path):
    p = tmp_path / "jobs.jsonl"
    p.write_text('{"type": "submit", "job_id": "ok"}\n123\n[1,2]\n', encoding="utf-8")
    assert [e["job_id"] for e in read_history(p)] == ["ok"]


def test_truncate_structured_values_show_ellipsis():
    from bioq.jobs import _truncate
    assert _truncate([1, 2, 3]) == "[1, 2, 3]"
    assert _truncate({"k": "v" * 300}, limit=10).endswith("…")


def test_history_path_uses_state_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert str(history_path()) == str(tmp_path / "bioq" / "jobs.jsonl")


def test_history_file_is_0600(tmp_path):
    p = tmp_path / "jobs.jsonl"
    record_submit(p, job_id="j1", svc="s", endpoint="e")
    assert (p.stat().st_mode & 0o777) == 0o600


def test_history_write_failure_is_nonfatal(tmp_path, monkeypatch, capsys):
    import pathlib

    def boom(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(pathlib.Path, "write_text", boom)
    p = tmp_path / "jobs.jsonl"
    record_status(p, job_id="j1", status="completed")  # must not raise
    assert "could not record job history" in capsys.readouterr().err
