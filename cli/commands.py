"""Subcommand handlers. Each returns an exit code (0) or raises a CLIError."""
from __future__ import annotations

import uuid
import zipfile
from pathlib import Path

from .errors import JobFailedError, NoOutputError
from .jobs import default_registry_path, poll, record_job
from .output import emit
from .params import build_body
from .upload import upload_files

POLL_INTERVAL_S = 10.0
POLL_TIMEOUT_S = 3600.0


def cmd_services(client, args) -> int:
    emit(client.list_services(), fmt=args.output)
    return 0


def cmd_describe(client, args) -> int:
    emit(client.describe(args.svc), fmt=args.output)
    return 0


def _build_and_submit(client, args) -> str:
    job_id = uuid.uuid4().hex[:20]
    file_uris = upload_files(client, job_id, args.file)
    body = build_body(sets=args.set, set_jsons=args.set_json, file_uris=file_uris)
    client.run(args.svc, args.endpoint, job_id, body)
    record_job(default_registry_path(), job_id=job_id, svc=args.svc, endpoint=args.endpoint)
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
        z.extractall(out_dir)
    return len(names)


def cmd_run(client, args) -> int:
    job_id = _build_and_submit(client, args)
    if not args.wait:
        emit({"job_id": job_id, "status": "running"}, fmt=args.output)
        return 0
    job = poll(client, job_id, interval=POLL_INTERVAL_S, timeout=POLL_TIMEOUT_S)
    if job["status"] != "completed":
        raise JobFailedError(f"job {job_id} ended with status={job['status']}")
    out_dir = Path(args.out) if args.out else Path(f"./{job_id}")
    n = _extract_download(client, job_id, out_dir)
    emit({"job_id": job_id, "status": "completed", "output_dir": str(out_dir),
          "files": n}, fmt=args.output)
    return 0


def cmd_status(client, args) -> int:
    emit(client.get_job(args.job_id), fmt=args.output)
    return 0


def cmd_download(client, args) -> int:
    out_dir = Path(args.out) if args.out else Path(f"./{args.job_id}")
    n = _extract_download(client, args.job_id, out_dir)
    emit({"job_id": args.job_id, "output_dir": str(out_dir), "files": n}, fmt=args.output)
    return 0


def cmd_cancel(client, args) -> int:
    emit(client.cancel(args.job_id), fmt=args.output)
    return 0


# --- no-client commands (config file only; never touch the gateway) ---

def cmd_login(args) -> int:
    from getpass import getpass
    from .config import default_config_path, write_profile
    url = args.gateway_url or input("Gateway URL: ").strip()
    key = args.api_key or getpass("API key (hidden, empty to skip): ").strip()
    profile = args.profile or "default"
    path = default_config_path()
    write_profile(path, profile=profile, gateway_url=url, api_key=(key or None))
    print(f"saved profile '{profile}' to {path} (mode 0600)")
    return 0


def cmd_logout(args) -> int:
    from .config import default_config_path, remove_api_key
    profile = args.profile or "default"
    remove_api_key(default_config_path(), profile)
    print(f"removed api_key for profile '{profile}'")
    return 0


def cmd_config(args) -> int:
    from .config import default_config_path, tomllib
    path = default_config_path()
    if getattr(args, "config_action", "show") == "path":
        print(path)
        return 0
    if not path.exists():
        print(f"no config at {path}")
        return 0
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for name, ent in (data.get("profiles") or {}).items():
        masked = dict(ent)
        if masked.get("api_key"):
            masked["api_key"] = masked["api_key"][:4] + "…"
        marker = " (default)" if data.get("default_profile") == name else ""
        print(f"[{name}]{marker}")
        for k, v in masked.items():
            print(f"  {k} = {v}")
    return 0
