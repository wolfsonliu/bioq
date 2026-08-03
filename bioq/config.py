"""bioq config: profiles from ~/.config/bioq/config.toml.

Precedence: CLI flag > env (BIOQ_GATEWAY_URL) > profile file. Auth is JWT-only:
a profile is either `oidc` (device-flow tokens cached separately, see tokens.py),
`client_credentials` (machine/CI), or has no auth (`none` → rely on the gateway's
VPC bypass for local/internal access).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from .errors import UsageError


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "bioq" / "config.toml"


@dataclass
class Config:
    gateway_url: str
    profile: str | None
    auth_mode: str = "none"                    # none | oidc | client_credentials
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None      # client_credentials only (prefer env)


def load_config(*, profile: str | None, gateway_url: str | None,
                config_path: Path | None = None) -> Config:
    data: dict = {}
    path = config_path or default_config_path()
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))

    chosen = profile or data.get("default_profile")
    prof = (data.get("profiles") or {}).get(chosen, {}) if chosen else {}

    url = gateway_url or os.environ.get("BIOQ_GATEWAY_URL") or prof.get("gateway_url")
    if not url:
        raise UsageError(
            "no gateway_url: run `bioq login`, pass --gateway-url, set "
            f"BIOQ_GATEWAY_URL, or add a profile to {path}"
        )
    return Config(
        gateway_url=url.rstrip("/"),
        profile=chosen,
        auth_mode=prof.get("auth_mode", "none"),
        oidc_issuer=prof.get("oidc_issuer"),
        oidc_client_id=prof.get("oidc_client_id"),
        oidc_client_secret=(os.environ.get("BIOQ_OIDC_CLIENT_SECRET")
                            or prof.get("oidc_client_secret")),
    )


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _write_data(path: Path, data: dict) -> None:
    """Serialize our flat config schema to TOML at path (chmod 0600)."""
    lines: list[str] = []
    if data.get("default_profile"):
        lines += [f'default_profile = "{_toml_escape(data["default_profile"])}"', ""]
    for name, ent in (data.get("profiles") or {}).items():
        lines.append(f"[profiles.{name}]")
        for k, v in ent.items():
            lines.append(f'{k} = "{_toml_escape(str(v))}"')
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path.chmod(0o600)


def write_profile(path: Path, *, profile: str, gateway_url: str,
                  auth_mode: str | None = None, oidc_issuer: str | None = None,
                  oidc_client_id: str | None = None,
                  oidc_client_secret: str | None = None,
                  make_default: bool = True) -> None:
    """Persist a profile to config.toml (chmod 0600). Only provided fields are
    written. OIDC tokens are NOT stored here — they live in tokens.py's cache."""
    data: dict = {}
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    profiles = data.setdefault("profiles", {})
    entry = profiles.setdefault(profile, {})
    entry["gateway_url"] = gateway_url
    if auth_mode is not None:
        entry["auth_mode"] = auth_mode
    if oidc_issuer is not None:
        entry["oidc_issuer"] = oidc_issuer
    if oidc_client_id is not None:
        entry["oidc_client_id"] = oidc_client_id
    if oidc_client_secret is not None:
        entry["oidc_client_secret"] = oidc_client_secret
    if make_default or "default_profile" not in data:
        data["default_profile"] = profile
    _write_data(path, data)
