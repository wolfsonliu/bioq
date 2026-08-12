"""Subcommand handlers. Each returns an exit code (0) or raises a CLIError."""
from __future__ import annotations

import os
import uuid
import zipfile
from pathlib import Path

from .errors import JobFailedError, NoOutputError
from .jobs import TERMINAL, default_registry_path, poll, record_job
from .output import emit
from .params import build_body
from .upload import upload_files

POLL_INTERVAL_S = 10.0
POLL_TIMEOUT_S = 21600.0  # 6 hours — FC async-task hard limit is 24h
_SUFFIX = "-server"


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
    info = client.describe(_canonical_svc(args.svc))
    if args.output == "json":
        emit(info, fmt="json")   # raw payload — the machine/LLM view
        return 0
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
        print(f"{svc_short}: no runnable task endpoints found; try `--output json`")
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


def _build_and_submit(client, args) -> str:
    svc = _canonical_svc(args.svc)
    job_id = uuid.uuid4().hex[:20]
    file_uris = upload_files(client, job_id, args.file)
    body = build_body(sets=args.set, set_jsons=args.set_json, file_uris=file_uris)
    client.run(svc, args.endpoint, job_id, body)
    record_job(default_registry_path(), job_id=job_id, svc=svc, endpoint=args.endpoint)
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


def _poll_timeout(args) -> float:
    """Resolve poll timeout: CLI --timeout > BIOQ_POLL_TIMEOUT env > default."""
    t = getattr(args, "timeout", None)
    if t is not None:
        if t <= 0:
            from .errors import UsageError
            raise UsageError("--timeout must be > 0")
        return t
    env = os.environ.get("BIOQ_POLL_TIMEOUT")
    if env:
        return float(env)
    return POLL_TIMEOUT_S


def cmd_run(client, args) -> int:
    job_id = _build_and_submit(client, args)
    if not args.wait:
        emit({"job_id": job_id, "status": "running"}, fmt=args.output)
        return 0
    timeout = _poll_timeout(args)
    job = poll(client, job_id, interval=POLL_INTERVAL_S, timeout=timeout)
    if job["status"] != "completed":
        raise JobFailedError(f"job {job_id} ended with status={job['status']}")
    out_dir = Path(args.out) if args.out else Path(f"./{job_id}")
    n = _extract_download(client, job_id, out_dir)
    emit({"job_id": job_id, "status": "completed", "output_dir": str(out_dir),
          "files": n}, fmt=args.output)
    return 0


def cmd_status(client, args) -> int:
    # Single-shot by default. If --timeout is given (or BIOQ_POLL_TIMEOUT env is
    # set for this invocation), and the job isn't already in a terminal state,
    # poll until it becomes terminal or the timeout expires.
    explicit_timeout = (getattr(args, "timeout", None) is not None
                        or os.environ.get("BIOQ_POLL_TIMEOUT"))
    job = client.get_job(args.job_id)
    if explicit_timeout and job.get("status") not in TERMINAL:
        job = poll(client, args.job_id, interval=POLL_INTERVAL_S,
                   timeout=_poll_timeout(args))
    emit(job, fmt=args.output)
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
    from . import oidc, tokens
    from .config import default_config_path, write_profile
    profile = args.profile or "default"
    url = args.gateway_url or input("Gateway URL: ").strip()
    issuer = args.issuer or input("OIDC issuer URL: ").strip()
    client_id = args.client_id or input("OIDC client_id: ").strip()
    path = default_config_path()

    if getattr(args, "client_credentials", False):
        # Machine/CI: store the profile; the secret is read at request time
        # (from the profile or BIOQ_OIDC_CLIENT_SECRET) and exchanged for a token.
        write_profile(path, profile=profile, gateway_url=url,
                      auth_mode="client_credentials", oidc_issuer=issuer,
                      oidc_client_id=client_id,
                      oidc_client_secret=(getattr(args, "client_secret", None) or None))
        print(f"saved client_credentials profile '{profile}' to {path}")
        return 0

    meta = oidc.discover(issuer)
    dev = oidc.start_device(meta["device_authorization_endpoint"], client_id)
    print(f"\n  open: {dev.get('verification_uri_complete') or dev['verification_uri']}")
    print(f"  code: {dev['user_code']}\n  waiting for authorization...")
    tok = oidc.poll_token(meta["token_endpoint"], client_id, dev["device_code"],
                          interval=int(dev.get("interval", 5)),
                          expires_in=int(dev.get("expires_in", 600)))
    tokens.save_tokens(profile, tok, token_endpoint=meta["token_endpoint"],
                       client_id=client_id)
    write_profile(path, profile=profile, gateway_url=url, auth_mode="oidc",
                  oidc_issuer=issuer, oidc_client_id=client_id)
    print(f"logged in via OIDC; profile '{profile}' saved to {path}")
    return 0


def cmd_logout(args) -> int:
    from . import tokens
    profile = args.profile or "default"
    tokens.clear_tokens(profile)
    print(f"cleared cached tokens for profile '{profile}'")
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
        if masked.get("oidc_client_secret"):
            masked["oidc_client_secret"] = masked["oidc_client_secret"][:4] + "…"
        marker = " (default)" if data.get("default_profile") == name else ""
        print(f"[{name}]{marker}")
        for k, v in masked.items():
            print(f"  {k} = {v}")
    return 0
