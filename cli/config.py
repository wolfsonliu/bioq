"""bioq config: profiles from ~/.config/bioq/config.toml.

Precedence: CLI flag > env (BIOQ_GATEWAY_URL / BIOQ_API_KEY) > profile file.
The API key may be persisted here (by `bioq login`) but env always overrides.
"""
from __future__ import annotations

import os
import sys
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
    api_key: str | None
    profile: str | None
    key_id: str | None = None  # metadata only (not sent; auth is by api_key secret)


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
    api_key = os.environ.get("BIOQ_API_KEY") or prof.get("api_key")
    if path.exists() and prof.get("api_key") and (path.stat().st_mode & 0o077):
        print(f"warning: {path} is not 0600 (contains api_key)", file=sys.stderr)
    return Config(gateway_url=url.rstrip("/"), api_key=api_key, profile=chosen,
                  key_id=prof.get("key_id"))


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
                  api_key: str | None = None, key_id: str | None = None,
                  make_default: bool = True) -> None:
    """Persist a profile to config.toml (chmod 0600). Minimal TOML writer for our
    flat schema (default_profile + profiles.<name>.{gateway_url,api_key,key_id}).
    key_id is optional metadata (which key/principal); it is NOT sent on requests."""
    data: dict = {}
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    profiles = data.setdefault("profiles", {})
    entry = profiles.setdefault(profile, {})
    entry["gateway_url"] = gateway_url
    if api_key is not None:
        entry["api_key"] = api_key
    if key_id is not None:
        entry["key_id"] = key_id
    if make_default or "default_profile" not in data:
        data["default_profile"] = profile
    _write_data(path, data)


def remove_api_key(path: Path, profile: str) -> None:
    """`bioq logout`: drop a profile's api_key (keep gateway_url + default)."""
    if not path.exists():
        return
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    prof = (data.get("profiles") or {}).get(profile)
    if prof and "api_key" in prof:
        del prof["api_key"]
        _write_data(path, data)
