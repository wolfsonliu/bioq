"""Poll loop (transient-error tolerant) + local recent-job registry."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .errors import CLIError, GatewayError

TERMINAL = {"completed", "failed", "cancelled"}


def poll(client, job_id: str, *, interval: float, timeout: float,
         max_transient: int = 10, on_update=None) -> dict:
    deadline = time.time() + timeout
    transient = 0
    last_status = None
    while time.time() < deadline:
        try:
            job = client.get_job(job_id)
        except GatewayError:
            transient += 1
            if transient > max_transient:
                raise
            time.sleep(max(interval, 1))
            continue
        except CLIError:
            raise
        transient = 0
        if on_update and job.get("status") != last_status:
            on_update(job)
            last_status = job.get("status")
        if job.get("status") in TERMINAL:
            return job
        time.sleep(interval)
    raise GatewayError(f"timed out waiting for job {job_id} after {timeout}s")


def default_registry_path() -> Path:
    from .config import get_state_dir
    return Path(get_state_dir()) / "bioq" / "jobs.json"


def record_job(path: Path, *, job_id: str, svc: str, endpoint: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if path.exists():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            rows = []
    rows.append({"job_id": job_id, "svc": svc, "endpoint": endpoint,
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    path.write_text(json.dumps(rows[-100:], indent=2), encoding="utf-8")
