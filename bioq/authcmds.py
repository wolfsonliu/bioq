"""Offline credential-management commands: login / logout / config.

These never touch the gateway; login bootstraps the config file, so they run
before ``load_config`` (see ``main._NO_CLIENT``)."""
from __future__ import annotations


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
