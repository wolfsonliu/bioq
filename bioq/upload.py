"""--file field=path → prepare upload → PUT (if absent) → {field}_uri body entries.

field must match the downstream's <field>_uri form field. Multiple --file with
the same field collapse to a list under {field}_uri (gateway JSON-encodes it).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from .client import PUT_TIMEOUT
from .errors import UsageError


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_files(client, job_id: str, file_args: list[str]) -> dict:
    per_field: dict[str, list[str]] = {}
    for arg in file_args:
        if "=" not in arg:
            raise UsageError(f"--file expects field=path, got {arg!r}")
        field, path_str = arg.split("=", 1)
        if not field:
            raise UsageError(f"--file empty field in {arg!r}")
        path = Path(path_str).expanduser()
        if not path.is_file():
            raise UsageError(f"--file {field}: not a file: {path}")
        pre = client.prepare_upload(job_id, path.name, sha256_file(path))
        if not pre["exists"]:
            url = pre["put_url"]
            if url.startswith(("http://", "https://")):
                # OSS direct-to-object presigned URL: PUT bare (no gateway auth).
                resp = httpx.put(url, content=path.read_bytes(), timeout=PUT_TIMEOUT)
                if resp.status_code not in (200, 201):
                    raise UsageError(f"upload failed for {path.name}: HTTP {resp.status_code}")
            else:
                # Gateway-relative URL (file storage backend): PUT through the
                # authed client session so base_url + Authorization apply.
                client.put_file(url, path.read_bytes())
        per_field.setdefault(field, []).append(pre["uri"])
    return {f"{field}_uri": (uris[0] if len(uris) == 1 else uris)
            for field, uris in per_field.items()}
