"""Per-profile OIDC token cache at ~/.config/bioq/tokens/<profile>.json (0600).

Kept separate from config.toml: config holds durable settings, this holds the
volatile access/refresh tokens.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import default_config_path


def tokens_path(profile: str) -> Path:
    return default_config_path().parent / "tokens" / f"{profile}.json"


def save_tokens(profile: str, tok: dict, *, token_endpoint: str, client_id: str) -> None:
    p = tokens_path(profile)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "token_endpoint": token_endpoint,
        "client_id": client_id,
        # absolute expiry with a 30s safety margin
        "expires_at": time.time() + int(tok.get("expires_in", 300)) - 30,
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    p.chmod(0o600)


def load_tokens(profile: str) -> dict | None:
    p = tokens_path(profile)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def clear_tokens(profile: str) -> None:
    tokens_path(profile).unlink(missing_ok=True)


def is_expired(tok: dict) -> bool:
    return time.time() >= tok.get("expires_at", 0)
