# Phase 2 — Structural Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break up the overloaded `bioq/commands.py` (293 lines) by extracting two clearly separable clusters — the offline credential commands and the `describe` renderer — and document the intentional `_current_config` design. Optional but keeps `commands.py` focused.

**Architecture:** Two new modules (`bioq/authcmds.py`, `bioq/describe.py`). Dependency direction is one-way: `describe → commands` (it imports the shared short-name/timeout primitives), and `main → {commands, describe, authcmds}`. No cycles. `_canonical_svc`/`_SUFFIX`/`_resolve_timeout` stay single-sourced in `commands.py` per `docs/conventions.md`.

**Tech Stack:** Python ≥3.10, `pytest`, `ruff`.

---

## Task 2.1: Extract offline credential commands into `bioq/authcmds.py`

**Files:**
- Create: `bioq/authcmds.py`
- Modify: `bioq/main.py` (import + `_NO_CLIENT`)
- Modify: `bioq/commands.py` (delete moved functions)
- Modify: `bioq/tests/test_main.py` (add a structure test)

- [ ] **Step 1: Write the failing test**

Append to `bioq/tests/test_main.py`:

```python
def test_authcmds_exposes_offline_commands():
    from bioq import authcmds
    assert callable(authcmds.cmd_login)
    assert callable(authcmds.cmd_logout)
    assert callable(authcmds.cmd_config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest bioq/tests/test_main.py::test_authcmds_exposes_offline_commands -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioq.authcmds'`.

- [ ] **Step 3: Create `bioq/authcmds.py`**

Copy the three offline commands verbatim from `bioq/commands.py` (current lines 231-293)
into the new module. The only change is the leading docstring:

```python
"""Offline credential-management commands: login / logout / config.

These never touch the gateway; login bootstraps the config file, so they run
before ``load_config`` (see ``main._NO_CLIENT``)."""
from __future__ import annotations


def cmd_login(args) -> int:
    from . import oidc, tokens
    from .config import default_config_path, write_profile
    profile = args.profile or "default"
    url = args.gateway_url or input("Gateway URL: ").strip()
    issuer = args.issuer or input("OIDC issuer URL: ").strip()
    client_id = args.client_id or input("OIDC client_id: ").strip()
    path = default_config_path()

    if getattr(args, "client_credentials", False):
        # Machine/CI: store the profile; the secret is read at request time
        # (from the profile or BIOQ_OIDC_CLIENT_SECRET) and exchanged for a token.
        write_profile(path, profile=profile, gateway_url=url,
                      auth_mode="client_credentials", oidc_issuer=issuer,
                      oidc_client_id=client_id,
                      oidc_client_secret=(getattr(args, "client_secret", None) or None))
        print(f"saved client_credentials profile '{profile}' to {path}")
        return 0

    meta = oidc.discover(issuer)
    dev = oidc.start_device(meta["device_authorization_endpoint"], client_id)
    print(f"\n  open: {dev.get('verification_uri_complete') or dev['verification_uri']}")
    print(f"  code: {dev['user_code']}\n  waiting for authorization...")
    tok = oidc.poll_token(meta["token_endpoint"], client_id, dev["device_code"],
                          interval=int(dev.get("interval", 5)),
                          expires_in=int(dev.get("expires_in", 600)))
    tokens.save_tokens(profile, tok, token_endpoint=meta["token_endpoint"],
                       client_id=client_id)
    write_profile(path, profile=profile, gateway_url=url, auth_mode="oidc",
                  oidc_issuer=issuer, oidc_client_id=client_id)
    print(f"logged in via OIDC; profile '{profile}' saved to {path}")
    return 0


def cmd_logout(args) -> int:
    from . import tokens
    profile = args.profile or "default"
    tokens.clear_tokens(profile)
    print(f"cleared cached tokens for profile '{profile}'")
    return 0


def cmd_config(args) -> int:
    from .config import default_config_path, tomllib
    path = default_config_path()
    if getattr(args, "config_action", "show") == "path":
        print(path)
        return 0
    if not path.exists():
        print(f"no config at {path}")
        return 0
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for name, ent in (data.get("profiles") or {}).items():
        masked = dict(ent)
        if masked.get("oidc_client_secret"):
            masked["oidc_client_secret"] = masked["oidc_client_secret"][:4] + "…"
        marker = " (default)" if data.get("default_profile") == name else ""
        print(f"[{name}]{marker}")
        for k, v in masked.items():
            print(f"  {k} = {v}")
    return 0
```

- [ ] **Step 4: Point `main.py` at the new module**

In `bioq/main.py`, add the import (next to `from . import commands`):

```python
from . import authcmds, commands
```

Replace `_NO_CLIENT` (lines 23-27) with:

```python
_NO_CLIENT = {
    "login": authcmds.cmd_login,
    "logout": authcmds.cmd_logout,
    "config": authcmds.cmd_config,
    "recent": commands.cmd_recent,
}
```

- [ ] **Step 5: Delete the moved functions from `commands.py`**

Remove the block in `bioq/commands.py` from the `# --- no-client commands` comment
(current line 231) through the end of `cmd_config` (current line 293), i.e. the three
functions `cmd_login`, `cmd_logout`, `cmd_config` and their section comment.

- [ ] **Step 6: Run the full suite + lint**

Run:
- `uv run python -m pytest -q`  (the existing `test_login_oidc_device_flow` and `test_login_client_credentials` now exercise `authcmds` through `main()`)
- `uv run ruff check bioq/`
Expected: PASS / no errors.

- [ ] **Step 7: Commit**

```bash
git add bioq/authcmds.py bioq/main.py bioq/commands.py bioq/tests/test_main.py
git commit -m "refactor(bioq): extract offline auth commands into authcmds.py"
```

---

## Task 2.2: Extract `describe` rendering into `bioq/describe.py`

**Files:**
- Create: `bioq/describe.py`
- Create: `bioq/tests/test_describe.py`
- Modify: `bioq/main.py` (`_COMMANDS["describe"]`)
- Modify: `bioq/commands.py` (delete moved functions/constants; drop `import time`)
- Modify: `bioq/tests/test_commands.py` (remove the relocated describe tests)

- [ ] **Step 1: Write the failing test**

Create `bioq/tests/test_describe.py` (full file):

```python
import json
import pytest
from types import SimpleNamespace

from bioq import describe
from bioq.errors import UsageError


def _args(**kw):
    base = dict(svc="proteinmpnn-server", endpoint="design", file=[], set=[],
                set_json=[], wait=False, output="json", out=None, job_id="j1",
                timeout=None)
    base.update(kw)
    return SimpleNamespace(**base)


_DESCRIBE = {
    "service": "proteinmpnn-server",
    "manifest": {"endpoints": [
        {"path": "/api/design", "summary": "sync", "request_fields": []},
        {"path": "/api/tasks/design", "summary": "Sequence design", "request_fields": [
            {"name": "pdb", "type": "file", "is_file": True, "required": False, "default": None},
            {"name": "pdb_uri", "type": "string", "is_file": False, "required": False, "default": None},
            {"name": "num_seq_per_target", "type": "integer", "is_file": False,
             "required": False, "default": 8},
        ]},
    ]},
    "openapi": {},
}


class _DescClient:
    def describe(self, svc): return _DESCRIBE


def test_describe_pretty_is_cli_shaped(capsys):
    describe.cmd_describe(_DescClient(), _args(svc="proteinmpnn", output="pretty", endpoint=None))
    out = capsys.readouterr().out
    assert "--file pdb=<path>" in out
    assert "--set num_seq_per_target=<integer>" in out
    assert "pdb_uri" not in out
    assert "bioq run proteinmpnn design" in out
    assert "/api/tasks" not in out


def test_describe_json_is_raw(capsys):
    describe.cmd_describe(_DescClient(), _args(svc="proteinmpnn", output="json", endpoint=None))
    assert json.loads(capsys.readouterr().out) == _DESCRIBE


def test_describe_endpoint_filter(capsys):
    describe.cmd_describe(_DescClient(),
                          _args(svc="proteinmpnn", output="pretty", endpoint="design"))
    out = capsys.readouterr().out
    assert "design" in out and "--file pdb=<path>" in out


def test_describe_unknown_endpoint(capsys):
    describe.cmd_describe(_DescClient(),
                          _args(svc="proteinmpnn", output="pretty", endpoint="nope"))
    assert "unknown endpoint 'nope'" in capsys.readouterr().out


def test_describe_empty_manifest_prints_cold_start_hint(capsys):
    class C:
        def describe(self, svc):
            return {"service": svc, "manifest": {}}
    describe.cmd_describe(C(), _args(svc="proteinmpnn", output="pretty", endpoint=None))
    out = capsys.readouterr().out
    assert "no runnable task endpoints" in out
    assert "cold-start" in out
    assert "--wait" in out


def test_describe_wait_polls_until_endpoints(capsys, monkeypatch):
    monkeypatch.setattr(describe, "DESCRIBE_WAIT_INTERVAL_S", 0.0)
    calls = []

    class C:
        def describe(self, svc):
            calls.append(svc)
            return _DESCRIBE if len(calls) > 1 else {"service": svc, "manifest": {}}

    describe.cmd_describe(C(), _args(svc="proteinmpnn", output="pretty",
                                     endpoint=None, wait=True, timeout=5.0))
    assert len(calls) == 2
    assert "--file pdb=<path>" in capsys.readouterr().out


def test_describe_wait_timeout_returns_last_and_hints(capsys, monkeypatch):
    monkeypatch.setattr(describe, "DESCRIBE_WAIT_INTERVAL_S", 0.0)

    class C:
        def describe(self, svc):
            return {"service": svc, "manifest": {}}

    code = describe.cmd_describe(C(), _args(svc="proteinmpnn", output="pretty",
                                             endpoint=None, wait=True, timeout=0.05))
    assert code == 0
    out = capsys.readouterr().out
    assert "no runnable task endpoints" in out
    assert "--wait" in out


def test_describe_json_ignores_wait_single_fetch(capsys):
    calls = []

    class C:
        def describe(self, svc):
            calls.append(svc)
            return _DESCRIBE

    describe.cmd_describe(C(), _args(svc="proteinmpnn", output="json",
                                     endpoint=None, wait=True, timeout=5.0))
    assert len(calls) == 1


# --- _describe_timeout precedence + validation ---

def test_describe_timeout_defaults_to_module_constant(monkeypatch):
    monkeypatch.delenv("BIOQ_DESCRIBE_TIMEOUT", raising=False)
    assert describe._describe_timeout(_args()) == describe.DESCRIBE_WAIT_TIMEOUT_S


def test_describe_timeout_env_overrides_default(monkeypatch):
    monkeypatch.setenv("BIOQ_DESCRIBE_TIMEOUT", "42")
    assert describe._describe_timeout(_args()) == 42.0


def test_describe_timeout_cli_beats_env(monkeypatch):
    monkeypatch.setenv("BIOQ_DESCRIBE_TIMEOUT", "42")
    assert describe._describe_timeout(_args(timeout=7.5)) == 7.5


def test_describe_timeout_nonpositive_raises_usage_error():
    with pytest.raises(UsageError):
        describe._describe_timeout(_args(timeout=0))
    with pytest.raises(UsageError):
        describe._describe_timeout(_args(timeout=-1))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest bioq/tests/test_describe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioq.describe'`.

- [ ] **Step 3: Create `bioq/describe.py`**

New file — the describe functions moved verbatim from `commands.py`, importing the
shared primitives (`_SUFFIX`, `_canonical_svc`, `_resolve_timeout`) from `.commands`:

```python
"""`bioq describe`: human/CLI and JSON views of a service's runnable endpoints,
with --wait cold-start tolerance. Imports the shared short-name and timeout
primitives from ``commands``."""
from __future__ import annotations

import time

from .commands import _SUFFIX, _canonical_svc, _resolve_timeout
from .output import emit

DESCRIBE_WAIT_INTERVAL_S = 2.0   # describe --wait refetch cadence
DESCRIBE_WAIT_TIMEOUT_S = 120.0  # describe --wait give-up (FC cold start ~tens of s)


def cmd_describe(client, args) -> int:
    svc = _canonical_svc(args.svc)
    info = client.describe(svc)
    if args.output == "json":
        emit(info, fmt="json")   # raw payload — the machine/LLM view
        return 0
    if args.wait:
        # Cold-start tolerance: refetch until runnable endpoints appear. The JSON
        # path above stays a single, faithful fetch (jq-stable) regardless of --wait.
        info = _describe_wait(client, svc, timeout=_describe_timeout(args))
    svc_short = args.svc.removesuffix(_SUFFIX)
    _print_describe_cli(info, svc_short=svc_short, only=getattr(args, "endpoint", None))
    return 0


def _task_endpoints(info: dict) -> list[tuple[str, dict]]:
    """Runnable endpoints for `bioq run`: the downstream /api/tasks/<name> ones,
    keyed by the CLI name (part after /api/tasks/, may be nested)."""
    eps = (info.get("manifest") or {}).get("endpoints") or []
    out = []
    for e in eps:
        path = e.get("path", "")
        if path.startswith("/api/tasks/"):
            out.append((path[len("/api/tasks/"):], e))
    return out


def _print_describe_cli(info: dict, *, svc_short: str, only: str | None = None) -> None:
    """Human/CLI-shaped view: --file / --set args + a copy-paste `bioq run` line."""
    tasks = _task_endpoints(info)
    if only is not None:
        tasks = [(n, e) for (n, e) in tasks if n == only]
        if not tasks:
            print(f"unknown endpoint {only!r} for {svc_short} "
                  f"(try `bioq describe {svc_short}`)")
            return
    if not tasks:
        print(f"{svc_short}: gateway returned no runnable task endpoints")
        print("  (its endpoint list can be empty while the service cold-starts)")
        print(f"  retry in a few seconds, or wait:  bioq describe {svc_short} --wait")
        print("  raw payload, if any:  --output json")
        return

    print(svc_short)
    for name, e in tasks:
        fields = e.get("request_fields") or []
        files = [f for f in fields if f.get("is_file")]
        uri_companions = {f"{f['name']}_uri" for f in files}
        params = [f for f in fields
                  if not f.get("is_file") and f["name"] not in uri_companions]

        summary = e.get("summary") or ""
        print(f"\n  {name}" + (f" — {summary}" if summary else ""))
        if files:
            print("    files:")
            for f in files:
                req = "required" if f.get("required") else "optional"
                print(f"      --file {f['name']}=<path>   ({req})")
        if params:
            print("    params:")
            for f in params:
                default = f.get("default")
                dv = "" if default is None else f"  [default: {default!r}]"
                req = "  (required)" if f.get("required") else ""
                print(f"      --set {f['name']}=<{f.get('type', 'string')}>{dv}{req}")
                desc = (f.get("description") or "").strip()
                if desc:
                    print(f"          {desc.splitlines()[0][:100]}")

        example = [f"bioq run {svc_short} {name}"]
        example += [f"--file {f['name']}=<path>" for f in files]
        example += [f"--set {f['name']}=<{f.get('type', 'string')}>"
                    for f in params if f.get("required")][:3]
        example.append("--wait -o ./out")
        print("    example:")
        print("      " + " ".join(example))


def _describe_timeout(args) -> float:
    """Resolve describe --wait deadline: --timeout > BIOQ_DESCRIBE_TIMEOUT env >
    DESCRIBE_WAIT_TIMEOUT_S default."""
    return _resolve_timeout(args, env_var="BIOQ_DESCRIBE_TIMEOUT",
                            default=DESCRIBE_WAIT_TIMEOUT_S)


def _describe_wait(client, svc: str, *, timeout: float,
                   interval: float = DESCRIBE_WAIT_INTERVAL_S) -> dict:
    """Refetch the service manifest until runnable `/api/tasks/*` endpoints appear
    (cold-start tolerance). Returns the last payload and never raises on timeout —
    the caller renders the empty-endpoints hint."""
    deadline = time.time() + timeout
    info = client.describe(svc)
    while not _task_endpoints(info) and time.time() < deadline:
        time.sleep(interval)
        info = client.describe(svc)
    return info
```

- [ ] **Step 4: Point `main.py` at `describe.cmd_describe`**

In `bioq/main.py`, add the import:

```python
from . import authcmds, commands, describe
```

In `_COMMANDS` (line 11), change `"describe": commands.cmd_describe,` to:

```python
    "describe": describe.cmd_describe,
```

- [ ] **Step 5: Remove the moved code from `commands.py`**

Delete from `bioq/commands.py`:
- the `DESCRIBE_WAIT_INTERVAL_S` and `DESCRIBE_WAIT_TIMEOUT_S` constants (lines 18-19);
- `cmd_describe`, `_task_endpoints`, `_print_describe_cli`, `_describe_timeout`,
  `_describe_wait` (the functions between line 39 and line 142);
- `import time` (line 5) — no remaining `time` usage in `commands.py`.

Keep `_canonical_svc`, `cmd_services`, `_SUFFIX`, and all run/submit/status/download/
cancel/recent code and `_resolve_timeout`/`_validate_job_id`/`_file_names`.

- [ ] **Step 6: Remove the relocated tests from `test_commands.py`**

Delete from `bioq/tests/test_commands.py`: the `_DESCRIBE` dict, `_DescClient`, and the
ten `test_describe_*` tests (including the four `test_describe_timeout_*`). Keep
`test_canonical_svc_appends_suffix` (still tests `commands._canonical_svc`) and
`test_services_strips_server_suffix` (still tests `commands.cmd_services`), the
`test_submit_*`/`test_run_*` tests, and the `test_poll_timeout_*`/`test_resolve_timeout_*`
tests.

- [ ] **Step 7: Run the full suite + lint**

Run:
- `uv run python -m pytest -q`
- `uv run ruff check bioq/`
Expected: PASS / no errors.

- [ ] **Step 8: Commit**

```bash
git add bioq/describe.py bioq/tests/test_describe.py bioq/main.py bioq/commands.py bioq/tests/test_commands.py
git commit -m "refactor(bioq): extract describe rendering into describe.py"
```

---

## Task 2.3: Document `_current_config` as an intentional ambient-state design

**Files:**
- Modify: `bioq/config.py` (docstring around `_current_config`)
- Modify: `docs/conventions.md`

> Decision (per roadmap P2-9): **keep** the module-level `_current_config` accessor
> (single-threaded CLI; explicit threading via `contextvars`/param-passing has
> marginal benefit). This task only records that decision so future readers don't
> flag it as an accident.

- [ ] **Step 1: Note it in `config.py`**

In `bioq/config.py`, replace the section comment above `_current_config` (lines 70-74):

```
# ---------------------------------------------------------------------------
# Module-level config accessor — lets other modules (jobs.py, tokens.py) pick
# up the configured state_dir / tokens_dir without threading the Config object
# through every function signature.
# ---------------------------------------------------------------------------
```

with:

```
# ---------------------------------------------------------------------------
# Module-level config accessor — lets other modules (jobs.py, tokens.py) pick
# up the configured state_dir / tokens_dir without threading the Config object
# through every function signature. This ambient state is INTENTIONAL (documented
# in docs/conventions.md): bioq is a single-shot CLI, so per-invocation global
# state is fine. If bioq ever becomes long-lived/concurrent, switch to explicit
# passing or contextvars, not a module global.
# ---------------------------------------------------------------------------
```

- [ ] **Step 2: Record the convention**

In `docs/conventions.md`, append to the "Security & style" section:

```
- **`config._current_config` is an intentional ambient accessor.** `load_config`
  stores the resolved `Config` module-globally so `get_state_dir`/`get_tokens_dir`
  (and, via them, `jobs.history_path`) don't require threading `Config` through every
  signature. *Why: bioq is a single-shot CLI; per-invocation global state is safe and
  simpler. Remove-when: bioq becomes long-lived or concurrent — then replace with
  explicit passing or `contextvars`.*
```

Mirror the same note in `docs/conventions.zh.md` (translated).

- [ ] **Step 3: Verify**

Run: `uv run python -m pytest -q`
Expected: PASS (no code change; guard against accidental breakage).

- [ ] **Step 4: Commit**

```bash
git add bioq/config.py docs/conventions.md docs/conventions.zh.md
git commit -m "docs(bioq): document _current_config ambient-state decision"
```

---

## Phase 2 exit check

```bash
uv run python -m pytest -q
uv run ruff check bioq/
python -c "import bioq.commands, bioq.describe, bioq.authcmds; print('ok')"
git log --oneline -4
```

`commands.py` should now hold only the lifecycle + shared primitives
(`services`/`run`/`submit`/`status`/`download`/`cancel`/`recent`, `_canonical_svc`,
`_SUFFIX`, `_resolve_timeout`, `_file_names`, `_validate_job_id`), with `describe`
and the offline auth commands in their own modules.