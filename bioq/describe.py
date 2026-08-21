"""`bioq describe`: human/CLI and JSON views of a service's runnable endpoints,
with --wait cold-start tolerance. Imports the shared short-name and timeout
primitives from ``commands``."""
from __future__ import annotations

import time

from .commands import _SUFFIX, _canonical_svc, _resolve_timeout
from .output import emit

DESCRIBE_WAIT_INTERVAL_S = 2.0   # describe --wait refetch cadence
DESCRIBE_WAIT_TIMEOUT_S = 120.0  # describe --wait give-up (FC cold start ~tens of s)


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


def _describe_timeout(args) -> float:
    """Resolve describe --wait deadline: --timeout > BIOQ_DESCRIBE_TIMEOUT env >
    DESCRIBE_WAIT_TIMEOUT_S default."""
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
