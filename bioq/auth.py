"""Resolve the Bearer token for a request (JWT-only).

- oidc: use the cached device-flow token, refreshing if expired.
- client_credentials: mint a fresh token (machine/CI).
- none: return None → no Authorization header → rely on the gateway's VPC bypass.
"""
from __future__ import annotations

from . import oidc, tokens
from .errors import AuthError


def resolve_bearer(cfg) -> str | None:
    profile = cfg.profile or "default"

    if cfg.auth_mode == "client_credentials":
        if not (cfg.oidc_issuer and cfg.oidc_client_id and cfg.oidc_client_secret):
            raise AuthError("client_credentials needs oidc_issuer / oidc_client_id / "
                            "oidc_client_secret (set BIOQ_OIDC_CLIENT_SECRET or the profile)")
        meta = oidc.discover(cfg.oidc_issuer)
        tok = oidc.client_credentials(meta["token_endpoint"], cfg.oidc_client_id,
                                      cfg.oidc_client_secret)
        return tok["access_token"]

    if cfg.auth_mode == "oidc":
        tok = tokens.load_tokens(profile)
        if not tok:
            raise AuthError("not logged in; run `bioq login --oidc`")
        if tokens.is_expired(tok):
            if not tok.get("refresh_token"):
                raise AuthError("session expired; run `bioq login --oidc`")
            fresh = oidc.refresh(tok["token_endpoint"], tok["client_id"],
                                 tok["refresh_token"])
            tokens.save_tokens(
                profile,
                {**fresh, "refresh_token": fresh.get("refresh_token", tok["refresh_token"])},
                token_endpoint=tok["token_endpoint"], client_id=tok["client_id"])
            return fresh["access_token"]
        return tok["access_token"]

    return None  # auth_mode == "none" → VPC bypass (local/internal)
