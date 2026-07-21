"""bioq entrypoint: argparse parser + dispatch + exit-code mapping."""
from __future__ import annotations

import sys

from . import commands
from .client import GatewayClient
from .config import load_config
from .errors import CLIError, ConflictError, EXIT_INTERRUPT, EXIT_OK, UsageError

_COMMANDS = {
    "services": commands.cmd_services,
    "describe": commands.cmd_describe,
    "run": commands.cmd_run,
    "submit": commands.cmd_submit,
    "status": commands.cmd_status,
    "download": commands.cmd_download,
    "cancel": commands.cmd_cancel,
}

# Commands that only touch the local config file — no gateway connection, and
# must run BEFORE load_config (login bootstraps the config).
_NO_CLIENT = {
    "login": commands.cmd_login,
    "logout": commands.cmd_logout,
    "config": commands.cmd_config,
}


# Global flags live on a shared parent parser applied to BOTH the top-level
# parser and every subparser, so they work before OR after the subcommand
# (like `uv`/`git`): `bioq --output json run ...` and `bioq run ... --output json`
# are equivalent. `default=SUPPRESS` keeps the subparser copy from clobbering a
# value already parsed at the top level; main() backfills the real defaults.
_GLOBAL_DEFAULTS = (("gateway_url", None), ("profile", None), ("output", "pretty"))


def _global_flags():
    import argparse
    g = argparse.ArgumentParser(add_help=False)
    g.add_argument("--gateway-url", default=argparse.SUPPRESS)
    g.add_argument("--profile", default=argparse.SUPPRESS)
    g.add_argument("--output", choices=["pretty", "json"], default=argparse.SUPPRESS)
    return g


def build_parser():
    import argparse
    common = _global_flags()
    p = argparse.ArgumentParser(prog="bioq", description="bioagent gateway CLI",
                                parents=[common])
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("services", parents=[common])

    d = sub.add_parser("describe", parents=[common])
    d.add_argument("svc")
    d.add_argument("endpoint", nargs="?")  # optional: show just one endpoint

    for name in ("run", "submit"):
        sp = sub.add_parser(name, parents=[common])
        sp.add_argument("svc")
        sp.add_argument("endpoint")  # single token; may contain '/'
        sp.add_argument("--file", action="append", default=[], metavar="FIELD=PATH")
        sp.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
        sp.add_argument("--set-json", dest="set_json", action="append", default=[],
                        metavar="KEY=JSON")
        if name == "run":
            sp.add_argument("--wait", action="store_true")
            sp.add_argument("-o", "--out")

    s = sub.add_parser("status", parents=[common])
    s.add_argument("job_id")
    dl = sub.add_parser("download", parents=[common])
    dl.add_argument("job_id")
    dl.add_argument("-o", "--out")
    c = sub.add_parser("cancel", parents=[common])
    c.add_argument("job_id")

    lg = sub.add_parser("login", parents=[common])
    lg.add_argument("--api-key")           # login-only (not global → no history leak)
    lg.add_argument("--key-id")            # optional metadata (which key)
    lg.add_argument("--account-id")        # optional metadata (account jobs are owned by)
    sub.add_parser("logout", parents=[common])
    cf = sub.add_parser("config", parents=[common])
    cf.add_argument("config_action", nargs="?", choices=["show", "path"], default="show")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Backfill global-flag defaults (SUPPRESS means an unset flag is absent).
    for attr, default in _GLOBAL_DEFAULTS:
        if not hasattr(args, attr):
            setattr(args, attr, default)

    # No-client commands (login/logout/config) run without a gateway connection
    # and must NOT require an existing config (login creates it).
    if args.command in _NO_CLIENT:
        try:
            return _NO_CLIENT[args.command](args)
        except CLIError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            return exc.exit_code

    try:
        cfg = load_config(profile=args.profile, gateway_url=args.gateway_url)
    except UsageError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code

    client = GatewayClient.from_url(cfg.gateway_url, cfg.api_key)
    try:
        return _COMMANDS[args.command](client, args)
    except ConflictError:
        # job_id already exists => idempotent: treat submit/run as "already
        # submitted" and exit 0 (the job is on the gateway; poll with `bioq status`).
        return EXIT_OK
    except CLIError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("interrupted; check `bioq status <job_id>`", file=sys.stderr)
        return EXIT_INTERRUPT
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
