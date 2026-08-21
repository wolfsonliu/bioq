"""Emit results as JSON (machine) or pretty (human)."""
from __future__ import annotations

import json
from typing import Any


def emit(data: Any, *, fmt: str = "pretty") -> None:
    if fmt == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if isinstance(data, dict):
        for k, v in data.items():
            print(f"{k}: {v}")
    elif isinstance(data, list):
        for item in data:
            print(item)
    else:
        print(data)
