"""Poll loop (transient-error tolerant) + local job history (JSONL read/write)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .errors import CLIError, GatewayError

TERMINAL = {"completed", "failed", "cancelled"}

_HISTORY_MAX_EVENTS = 500


def poll(client, job_id: str, *, interval: float, timeout: float,
         max_transient: int = 10) -> dict:
    deadline = time.time() + timeout
    transient = 0
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
        if job.get("status") in TERMINAL:
            return job
        time.sleep(interval)
    raise GatewayError(f"timed out waiting for job {job_id} after {timeout}s")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _truncate(value, limit: int = 200):
    """Keep long values (esp. ``--set-json`` payloads) from bloating the history
    file. Scalars (int/float/bool/None) are stored as-is; strings are elided;
    lists/dicts are stored as a truncated repr."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, (list, dict)):
        s = repr(value)
        return s if len(s) <= limit else s[:limit] + "…"
    return value


def _append_event(path: Path, event: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        lines.append(json.dumps(event, ensure_ascii=False))
        lines = lines[-_HISTORY_MAX_EVENTS:]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o600)
    except OSError as exc:
        # History is auxiliary: never let a logging failure fail the command.
        print(f"warning: could not record job history: {exc}", file=sys.stderr)


def read_history(path: Path, *, limit: int = 20) -> list[dict]:
    """Return the last ``limit`` events (newest last); ``limit <= 0`` returns ``[]``.
    Tolerates a missing file or a malformed/orphaned line."""
    if not path.exists():
        return []
    events = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        events.append(parsed)
    if limit <= 0:
        return []
    return events[-limit:]


def record_submit(path: Path, *, job_id: str, svc: str, endpoint: str,
                  profile: str | None = None, gateway_url: str | None = None,
                  params: dict | None = None, files: dict | None = None) -> None:
    _append_event(path, {
        "type": "submit",
        "job_id": job_id,
        "svc": svc,
        "endpoint": endpoint,
        "profile": profile,
        "gateway_url": gateway_url,
        "params": {k: _truncate(v) for k, v in (params or {}).items()},
        "files": files or {},
        "ts": _now_iso(),
    })


def record_status(path: Path, *, job_id: str, status: str,
                  output_dir: str | None = None, n_files: int | None = None) -> None:
    _append_event(path, {
        "type": "status",
        "job_id": job_id,
        "status": status,
        "output_dir": output_dir,
        "files": n_files,
        "ts": _now_iso(),
    })


def history_path() -> Path:
    from .config import get_state_dir
    return Path(get_state_dir()) / "bioq" / "jobs.jsonl"
