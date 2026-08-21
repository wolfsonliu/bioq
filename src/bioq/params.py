"""Build the JSON run body from --set / --set-json / uploaded --file uris.

The gateway accepts a JSON body and form-encodes it downstream (str as-is,
list/dict JSON-encoded). --set does light type inference; --set-json takes
literal JSON or @file for structured values (e.g. `sequences`).
"""
from __future__ import annotations

import json
from pathlib import Path

from .errors import UsageError


def _split(pair: str) -> tuple[str, str]:
    if "=" not in pair:
        raise UsageError(f"expected key=value, got {pair!r}")
    k, v = pair.split("=", 1)
    if not k:
        raise UsageError(f"empty key in {pair!r}")
    return k, v


def _infer(v: str):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def build_body(*, sets: list[str], set_jsons: list[str],
               file_uris: dict[str, str]) -> dict:
    body: dict = {}
    for pair in sets:
        k, v = _split(pair)
        body[k] = _infer(v)
    for pair in set_jsons:
        k, v = _split(pair)
        raw = Path(v[1:]).read_text(encoding="utf-8") if v.startswith("@") else v
        try:
            body[k] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UsageError(f"--set-json {k}: invalid JSON: {exc}") from None
    body.update(file_uris)
    return body
