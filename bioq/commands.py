"""Subcommand handlers. Each returns an exit code (0) or raises a CLIError."""
from __future__ import annotations

import os
import time
import uuid
import zipfile
from pathlib import Path

from .errors import JobFailedError, NoOutputError, UsageError
from .jobs import (TERMINAL, history_path, poll, read_history,
                   record_status, record_submit)
from .output import emit
from .params import build_body
from .upload import upload_files

POLL_INTERVAL_S = 10.0
POLL_TIMEOUT_S = 21600.0  # 6 hours — FC async-task hard limit is 24h
DESCRIBE_WAIT_INTERVAL_S = 2.0   # describe --wait refetch cadence
DESCRIBE_WAIT_TIMEOUT_S = 120.0  # describe --wait give-up (FC cold start ~tens of s)
_SUFFIX = "-server"

_JOB_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _validate_job_id(job_id: str) -> str:
    """job_id is normally uuid4().hex[:20]. Accept only that ASCII shape so a
    user-supplied id can't build a `../`-escaping output dir."""
    if not job_id or any(ch not in _JOB_ID_CHARS for ch in job_id):
        raise UsageError(f"invalid job_id {job_id!r}")
    return job_id


def _safe_extract(z: zipfile.ZipFile, out_dir: Path) -> None:
    """extractall with a zip-slip guard: every member must resolve inside out_dir."""
    root = str(out_dir.resolve())
    for member in z.infolist():
        target = str((out_dir / member.filename).resolve())
        try:
            common = os.path.commonpath([root, target])
        except ValueError:
            raise NoOutputError(
                f"refusing to extract {member.filename!r}: escapes output dir")
        if common != root:
            raise NoOutputError(
                f"refusing to extract {member.filename!r}: escapes output dir")
    z.extractall(out_dir)


def _canonical_svc(name: str) -> str:
    """Accept a short name (proteinmpnn) or the canonical registry key
    (proteinmpnn-server). All gateway services end in `-server`, so append it
    when missing — keeps the gateway/docs canonical while letting users type
    the shorter form shown by `bioq services`."""
    return name if name.endswith(_SUFFIX) else name + _SUFFIX


def cmd_services(client, args) -> int:
    # Display without the redundant `-server` suffix (accepted back on input).
    names = [s.removesuffix(_SUFFIX)
             for s in client.list_services()]
    emit(names, fmt=args.output)
    return 0


def cmd_describe(client, args) -> int:
    svc = _canonical_svc(args.svc)
    info = client.describe(svc)
    if args.output == "json":
        emit(info, fmt="json")   # raw payload — the machine/LLM view
        return 0
    if args.wait:
        # Cold-start tolerance: refetch until runnable endpoints appear. The JSON
        # path above stays a single, faithful fetch (jq-stable) regardless of --wait.
        info = _describe_wait(client, svc, timeout=_describe_timeout(args))
    svc_short = args.svc.removesuffix(_SUFFIX)
    _print_describe_cli(info, svc_short=svc_short, only=getattr(args, "endpoint", None))
    return 0


def _task_endpoints(info: dict) -> list[tuple[str, dict]]:
    """Runnable endpoints for `bioq run`: the downstream /api/tasks/<name> ones,
    keyed by the CLI name (part after /api/tasks/, may be nested)."""
    eps = (info.get("manifest") or {}).get("endpoints") or []
    out = []
    for e in eps:
        path = e.get("path", "")
        if path.startswith("/api/tasks/"):
            out.append((path[len("/api/tasks/"):], e))
    return out


def _print_describe_cli(info: dict, *, svc_short: str, only: str | None = None) -> None:
    """Human/CLI-shaped view: --file / --set args + a copy-paste `bioq run` line."""
    tasks = _task_endpoints(info)
    if only is not None:
        tasks = [(n, e) for (n, e) in tasks if n == only]
        if not tasks:
            print(f"unknown endpoint {only!r} for {svc_short} "
                  f"(try `bioq describe {svc_short}`)")
            return
    if not tasks:
        print(f"{svc_short}: gateway returned no runnable task endpoints")
        print("  (its endpoint list can be empty while the service cold-starts)")
        print(f"  retry in a few seconds, or wait:  bioq describe {svc_short} --wait")
        print("  raw payload, if any:  --output json")
        return

    print(svc_short)
    for name, e in tasks:
        fields = e.get("request_fields") or []
        files = [f for f in fields if f.get("is_file")]
        uri_companions = {f"{f['name']}_uri" for f in files}
        params = [f for f in fields
                  if not f.get("is_file") and f["name"] not in uri_companions]

        summary = e.get("summary") or ""
        print(f"\n  {name}" + (f" — {summary}" if summary else ""))
        if files:
            print("    files:")
            for f in files:
                req = "required" if f.get("required") else "optional"
                print(f"      --file {f['name']}=<path>   ({req})")
        if params:
            print("    params:")
            for f in params:
                default = f.get("default")
                dv = "" if default is None else f"  [default: {default!r}]"
                req = "  (required)" if f.get("required") else ""
                print(f"      --set {f['name']}=<{f.get('type', 'string')}>{dv}{req}")
                desc = (f.get("description") or "").strip()
                if desc:
                    print(f"          {desc.splitlines()[0][:100]}")

        example = [f"bioq run {svc_short} {name}"]
        example += [f"--file {f['name']}=<path>" for f in files]
        example += [f"--set {f['name']}=<{f.get('type', 'string')}>"
                    for f in params if f.get("required")][:3]
        example.append("--wait -o ./out")
        print("    example:")
        print("      " + " ".join(example))


def _resolve_timeout(args, *, env_var: str, default: float) -> float:
    """Resolve a poll/wait deadline: CLI --timeout > ``env_var`` env > default."""
    t = getattr(args, "timeout", None)
    if t is not None:
        if t <= 0:
            raise UsageError("--timeout must be > 0")
        return t
    env = os.environ.get(env_var)
    if env:
        return float(env)
    return default


def _describe_timeout(args) -> float:
    return _resolve_timeout(args, env_var="BIOQ_DESCRIBE_TIMEOUT",
                            default=DESCRIBE_WAIT_TIMEOUT_S)


def _describe_wait(client, svc: str, *, timeout: float,
                   interval: float = DESCRIBE_WAIT_INTERVAL_S) -> dict:
    """Refetch the service manifest until runnable `/api/tasks/*` endpoints appear
    (cold-start tolerance). Returns the last payload and never raises on timeout —
    the caller renders the empty-endpoints hint."""
    deadline = time.time() + timeout
    info = client.describe(svc)
    while not _task_endpoints(info) and time.time() < deadline:
        time.sleep(interval)
        info = client.describe(svc)
    return info


def _file_names(file_args: list[str]) -> dict[str, str]:
    """field -> basename for ``--file field=path`` args (for the local history log)."""
    return {arg.split("=", 1)[0]: Path(arg.split("=", 1)[1]).name
            for arg in file_args}


def _build_and_submit(client, args) -> str:
    svc = _canonical_svc(args.svc)
    job_id = uuid.uuid4().hex[:20]
    file_uris = upload_files(client, job_id, args.file)
    body = build_body(sets=args.set, set_jsons=args.set_json, file_uris=file_uris)
    client.run(svc, args.endpoint, job_id, body)
    record_submit(
        history_path(),
        job_id=job_id,
        svc=svc,
        endpoint=args.endpoint,
        profile=getattr(args, "profile", None),
        gateway_url=getattr(args, "gateway_url", None),
        params={k: v for k, v in body.items() if not k.endswith("_uri")},
        files=_file_names(args.file),
    )
    return job_id


def cmd_submit(client, args) -> int:
    job_id = _build_and_submit(client, args)
    emit({"job_id": job_id, "status": "running"}, fmt=args.output)
    return 0


def _extract_download(client, job_id: str, out_dir: Path) -> int:
    zip_path = out_dir / f"{job_id}.zip"
    client.download(job_id, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if not names:
            raise NoOutputError(
                f"job {job_id} is completed but results.zip is empty "
                f"(downstream may have failed at setup; check gateway/FC logs)"
            )
        _safe_extract(z, out_dir)
    return len(names)


def _poll_timeout(args) -> float:
    return _resolve_timeout(args, env_var="BIOQ_POLL_TIMEOUT", default=POLL_TIMEOUT_S)


def cmd_run(client, args) -> int:
    job_id = _build_and_submit(client, args)
    if not args.wait:
        emit({"job_id": job_id, "status": "running"}, fmt=args.output)
        return 0
    timeout = _poll_timeout(args)
    job = poll(client, job_id, interval=POLL_INTERVAL_S, timeout=timeout)
    if job["status"] != "completed":
        record_status(history_path(), job_id=job_id, status=job["status"])
        raise JobFailedError(f"job {job_id} ended with status={job['status']}")
    out_dir = Path(args.out) if args.out else Path(f"./{job_id}")
    n = _extract_download(client, job_id, out_dir)
    record_status(history_path(), job_id=job_id, status="completed",
                  output_dir=str(out_dir), n_files=n)
    emit({"job_id": job_id, "status": "completed", "output_dir": str(out_dir),
          "files": n}, fmt=args.output)
    return 0


def cmd_status(client, args) -> int:
    _validate_job_id(args.job_id)
    # Single-shot by default. If --timeout is given (or BIOQ_POLL_TIMEOUT env is
    # set for this invocation), and the job isn't already in a terminal state,
    # poll until it becomes terminal or the timeout expires.
    explicit_timeout = (getattr(args, "timeout", None) is not None
                        or os.environ.get("BIOQ_POLL_TIMEOUT"))
    job = client.get_job(args.job_id)
    if explicit_timeout and job.get("status") not in TERMINAL:
        job = poll(client, args.job_id, interval=POLL_INTERVAL_S,
                   timeout=_poll_timeout(args))
    if job.get("status") in TERMINAL:
        record_status(history_path(), job_id=args.job_id, status=job["status"])
    emit(job, fmt=args.output)
    return 0


def cmd_download(client, args) -> int:
    _validate_job_id(args.job_id)
    out_dir = Path(args.out) if args.out else Path(f"./{args.job_id}")
    n = _extract_download(client, args.job_id, out_dir)
    record_status(history_path(), job_id=args.job_id, status="completed",
                  output_dir=str(out_dir), n_files=n)
    emit({"job_id": args.job_id, "output_dir": str(out_dir), "files": n}, fmt=args.output)
    return 0


def cmd_cancel(client, args) -> int:
    _validate_job_id(args.job_id)
    emit(client.cancel(args.job_id), fmt=args.output)
    return 0


def cmd_recent(args) -> int:
    """List the local job history (offline — reads only jobs.jsonl)."""
    events = read_history(history_path(), limit=getattr(args, "limit", 20))
    if args.output == "json":
        emit(events, fmt="json")
        return 0
    if not events:
        print("no recent jobs yet (submit/run records local history)")
        return 0
    for e in events:
        _print_history_event(e)
    return 0


def _print_history_event(e: dict) -> None:
    ts = e.get("ts", "")
    if e.get("type") == "status":
        n = e.get("files")
        where = f"  {e.get('output_dir')}" if e.get("output_dir") else ""
        count = f"  ({n} files)" if n is not None else ""
        print(f"{ts}  {e.get('job_id')}  {e.get('status')}{where}{count}")
    else:
        print(f"{ts}  {e.get('job_id')}  submit  "
              f"{e.get('svc', '')} {e.get('endpoint', '')}")
