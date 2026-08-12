import pytest

from bioq.errors import GatewayError
from bioq.jobs import TERMINAL, poll, record_job


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
