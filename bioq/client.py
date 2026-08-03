"""Thin httpx wrapper over the gateway /v1 API. Maps HTTP status to CLIError."""
from __future__ import annotations

from pathlib import Path

import httpx

from .errors import AuthError, ConflictError, GatewayError, NotFoundError

JOB_ID_HEADER = "X-Bioagent-Job-Id"


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


class GatewayClient:
    def __init__(self, *, http: httpx.Client, token: str | None) -> None:
        self._http = http
        if token:
            http.headers["Authorization"] = f"Bearer {token}"

    @classmethod
    def from_url(cls, gateway_url: str, token: str | None,
                 timeout: float = 60.0) -> "GatewayClient":
        http = httpx.Client(base_url=gateway_url, timeout=timeout,
                            follow_redirects=True)
        return cls(http=http, token=token)

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

    def presign(self, job_id: str, filename: str, sha256: str) -> dict:
        r = self._http.post("/v1/uploads/presign",
                            json={"job_id": job_id, "filename": filename, "sha256": sha256})
        _raise_for_status(r)
        return r.json()

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
                for chunk in r.iter_bytes():
                    fh.write(chunk)
        return dest
