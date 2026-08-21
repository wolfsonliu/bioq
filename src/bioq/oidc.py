"""OAuth2 primitives against an OIDC IdP: discovery, Device Authorization Grant
(RFC 8628), client-credentials, and refresh. Pure httpx so tests can mock it."""
from __future__ import annotations

import time

import httpx

from .errors import AuthError

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


def discover(issuer: str) -> dict:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    r = httpx.get(url, timeout=15.0)
    if r.status_code >= 400:
        raise AuthError(f"OIDC discovery failed ({r.status_code}) at {url}")
    return r.json()


# NOTE: `groups` is delivered by a client protocol mapper, not a requested scope —
# asking for a `groups` scope makes Keycloak reject the request (invalid_scope).
def start_device(device_endpoint: str, client_id: str,
                 scope: str = "openid profile offline_access") -> dict:
    r = httpx.post(device_endpoint, data={"client_id": client_id, "scope": scope},
                   timeout=15.0)
    if r.status_code >= 400:
        raise AuthError(f"device authorization failed ({r.status_code})")
    return r.json()


def poll_token(token_endpoint: str, client_id: str, device_code: str,
               interval: int = 5, expires_in: int = 600) -> dict:
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        r = httpx.post(token_endpoint, timeout=15.0, data={
            "grant_type": DEVICE_GRANT, "client_id": client_id,
            "device_code": device_code})
        body = r.json()
        if r.status_code < 400:
            return body
        err = body.get("error")
        if err == "authorization_pending":
            time.sleep(interval)
        elif err == "slow_down":
            interval += 5
            time.sleep(interval)
        else:
            raise AuthError(f"device token error: {err}")
    raise AuthError("device login timed out; re-run `bioq login --oidc`")


def client_credentials(token_endpoint: str, client_id: str, client_secret: str,
                       scope: str = "openid") -> dict:
    r = httpx.post(token_endpoint, timeout=15.0, data={
        "grant_type": "client_credentials", "client_id": client_id,
        "client_secret": client_secret, "scope": scope})
    if r.status_code >= 400:
        raise AuthError(f"client-credentials grant failed ({r.status_code})")
    return r.json()


def refresh(token_endpoint: str, client_id: str, refresh_token: str) -> dict:
    r = httpx.post(token_endpoint, timeout=15.0, data={
        "grant_type": "refresh_token", "client_id": client_id,
        "refresh_token": refresh_token})
    if r.status_code >= 400:
        raise AuthError("token refresh failed; re-run `bioq login --oidc`")
    return r.json()
