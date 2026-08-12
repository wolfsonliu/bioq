"""Thin httpx wrapper over the gateway /v1 API. Maps HTTP status to CLIError.

Auth is handled by _BioqAuth, which attaches a fresh Bearer token on every
request and auto-refreshes on 401 (for oidc mode).
"""
from __future__ import annotations

from pathlib import Path

import httpx

from . import tokens
from .auth import resolve_bearer
from .errors import AuthError, ConflictError, GatewayError, NotFoundError

JOB_ID_HEADER = "X-Bioagent-Job-Id"

# Uploads can be large / slow; give file PUTs a generous read+write budget.
_PUT_TIMEOUT = httpx.Timeout(connect=10, read=300, write=300, pool=10)


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return body.get("detail") or resp.text[:200]
    except Exception:  # noqa: BLE001
        return resp.text[:200]


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    msg = f"HTTP {resp.status_code}: {_detail(resp)}"
    if resp.status_code in (401, 403):
        raise AuthError(msg)
    if resp.status_code == 404:
        raise NotFoundError(msg)
    if resp.status_code == 409:
        raise ConflictError(msg)
    raise GatewayError(msg)


class _BioqAuth(httpx.Auth):
    """Attach a fresh Bearer per request; on 401 force a refresh and retry once.

    ``resolve_bearer`` returns the cached token when not expired (μs cost) and
    triggers ``oidc.refresh`` only on expiry — safe to call per request.
    """

    requires_response_body = False  # we only read status_code

    def __init__(self, cfg) -> None:
        self._cfg = cfg

    def auth_flow(self, request: httpx.Request) -> httpx.Request:
        token = resolve_bearer(self._cfg)
        if token:
            request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401 and self._cfg.auth_mode == "oidc":
            # Local cache said "valid" but gateway rejected — clock skew or
            # server-side revocation. Force a refresh and retry once.
            tokens.mark_expired(self._cfg.profile or "default")
            token = resolve_bearer(self._cfg)
            if token:
                request.headers["Authorization"] = f"Bearer {token}"
                yield request


class GatewayClient:
    def __init__(self, *, http: httpx.Client) -> None:
        self._http = http

    @classmethod
    def from_url(cls, gateway_url: str, cfg,
                 timeout: float = 60.0) -> GatewayClient:
        http = httpx.Client(base_url=gateway_url, timeout=timeout,
                            follow_redirects=True, auth=_BioqAuth(cfg))
        return cls(http=http)

    def close(self) -> None:
        self._http.close()

    def list_services(self) -> list[str]:
        r = self._http.get("/v1/services")
        _raise_for_status(r)
        return r.json()["services"]

    def describe(self, svc: str) -> dict:
        r = self._http.get(f"/v1/services/{svc}")
        _raise_for_status(r)
        return r.json()

    def prepare_upload(self, job_id: str, filename: str, sha256: str) -> dict:
        r = self._http.post("/v1/uploads/prepare",
                            json={"job_id": job_id, "filename": filename, "sha256": sha256})
        _raise_for_status(r)
        return r.json()

    def put_file(self, url: str, content: bytes) -> None:
        """PUT an upload through the gateway (file storage backend).

        The file backend's prepare_upload returns a gateway-relative URL
        (/v1/files/<key>); routing it through this session resolves it against
        base_url and carries the Authorization header. OSS direct-to-object
        URLs are absolute and must NOT get the gateway auth header, so those are
        PUT bare in upload.py instead.
        """
        r = self._http.put(url, content=content, timeout=_PUT_TIMEOUT)
        _raise_for_status(r)

    def run(self, svc: str, endpoint: str, job_id: str, body: dict) -> dict:
        r = self._http.post(f"/v1/run/{svc}/{endpoint}", json=body,
                           headers={JOB_ID_HEADER: job_id})
        _raise_for_status(r)
        return r.json()

    def get_job(self, job_id: str) -> dict:
        r = self._http.get(f"/v1/jobs/{job_id}")
        _raise_for_status(r)
        return r.json()

    def cancel(self, job_id: str) -> dict:
        r = self._http.post(f"/v1/jobs/{job_id}/cancel")
        _raise_for_status(r)
        return r.json()

    def download(self, job_id: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._http.stream("GET", f"/v1/jobs/{job_id}/download") as r:
            if r.status_code >= 400:
                r.read()
                _raise_for_status(r)
            with open(dest, "wb") as fh:
                fh.writelines(r.iter_bytes())
        return dest
