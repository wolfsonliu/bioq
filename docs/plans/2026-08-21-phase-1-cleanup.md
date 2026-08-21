# Phase 1 — Low-Cost Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the small duplications and hygiene gaps (B6/B9 + the `_describe_timeout`/`_poll_timeout` merge): single-source `PUT_TIMEOUT`, merge the two timeout resolvers, and hoist/annotate a few inconsistencies. No user-visible behavior changes.

**Architecture:** Pure refactors on `bioq/client.py`, `bioq/upload.py`, `bioq/commands.py`, `bioq/auth.py`. Existing offline tests are the safety net; a new identity/reference test guards the timeout single-sourcing.

**Tech Stack:** Python ≥3.10, `httpx`, `pytest`, `ruff`.

---

## Task 1.1: Single-source `PUT_TIMEOUT`

**Files:**
- Modify: `bioq/client.py:18-19,109`
- Modify: `bioq/upload.py:1-15,42`
- Modify: `bioq/tests/test_upload.py`

- [ ] **Step 1: Write the failing test**

Append to `bioq/tests/test_upload.py`:

```python
def test_put_timeout_is_single_sourced():
    from bioq.client import PUT_TIMEOUT
    from bioq.upload import PUT_TIMEOUT as upload_timeout
    assert upload_timeout is PUT_TIMEOUT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest bioq/tests/test_upload.py::test_put_timeout_is_single_sourced -v`
Expected: FAIL — `ImportError: cannot import name 'PUT_TIMEOUT'` (upload.py defines `_PUT_TIMEOUT`, not `PUT_TIMEOUT`).

- [ ] **Step 3: Rename the constant in `client.py` and export it**

In `bioq/client.py`, replace (lines 18-19):

```python
# Uploads can be large / slow; give file PUTs a generous read+write budget.
_PUT_TIMEOUT = httpx.Timeout(connect=10, read=300, write=300, pool=10)
```

with:

```python
# Uploads can be large / slow; give file PUTs a generous read+write budget.
# Single-sourced: upload.py imports this for presigned/relative PUTs.
PUT_TIMEOUT = httpx.Timeout(connect=10, read=300, write=300, pool=10)
```

And in `put_file` (line 109), change `timeout=_PUT_TIMEOUT` to `timeout=PUT_TIMEOUT`:

```python
        r = self._http.put(url, content=content, timeout=PUT_TIMEOUT)
```

- [ ] **Step 4: Import it in `upload.py` and drop the local duplicate**

In `bioq/upload.py`, delete the local constant (line 15):

```python
_PUT_TIMEOUT = httpx.Timeout(connect=10, read=300, write=300, pool=10)
```

Add the import near the top, after `from .errors import UsageError`:

```python
from .client import PUT_TIMEOUT
from .errors import UsageError
```

Change the PUT call (line 42) to use the imported name:

```python
                resp = httpx.put(url, content=path.read_bytes(), timeout=PUT_TIMEOUT)
```

- [ ] **Step 5: Run the full suite + lint**

Run:
- `uv run python -m pytest -q`
- `uv run ruff check bioq/`
Expected: PASS / no errors.

- [ ] **Step 6: Commit**

```bash
git add bioq/client.py bioq/upload.py bioq/tests/test_upload.py
git commit -m "refactor(bioq): single-source PUT_TIMEOUT in client.py"
```

---

## Task 1.2: Merge `_describe_timeout` / `_poll_timeout` into `_resolve_timeout`

**Files:**
- Modify: `bioq/commands.py` (`from .errors import ...` + `_describe_timeout` + `_poll_timeout`)
- Modify: `bioq/tests/test_commands.py`

- [ ] **Step 1: Write the failing test**

Append to `bioq/tests/test_commands.py`:

```python
def test_resolve_timeout_precedence_and_validation(monkeypatch):
    from bioq.errors import UsageError
    monkeypatch.setenv("BIOQ_X", "42")
    assert commands._resolve_timeout(_args(timeout=7.5),
                                     env_var="BIOQ_X", default=1.0) == 7.5
    assert commands._resolve_timeout(_args(), env_var="BIOQ_X", default=1.0) == 42.0
    monkeypatch.delenv("BIOQ_X", raising=False)
    assert commands._resolve_timeout(_args(), env_var="BIOQ_X", default=1.0) == 1.0
    with pytest.raises(UsageError):
        commands._resolve_timeout(_args(timeout=0), env_var="BIOQ_X", default=1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest bioq/tests/test_commands.py::test_resolve_timeout_precedence_and_validation -v`
Expected: FAIL — `AttributeError: module 'bioq.commands' has no attribute '_resolve_timeout'`.

- [ ] **Step 3: Hoist `UsageError` into the top-level import**

In `bioq/commands.py`, replace line 10:

```python
from .errors import JobFailedError, NoOutputError
```

with:

```python
from .errors import JobFailedError, NoOutputError, UsageError
```

- [ ] **Step 4: Implement `_resolve_timeout` and slim the two wrappers**

In `bioq/commands.py`, replace the current `_describe_timeout` and `_poll_timeout`
functions (lines 117-129 and 175-186) with:

```python
def _resolve_timeout(args, *, env_var: str, default: float) -> float:
    """Resolve a poll/wait deadline: CLI --timeout > ``env_var`` env > default."""
    t = getattr(args, "timeout", None)
    if t is not None:
        if t <= 0:
            raise UsageError("--timeout must be > 0")
        return t
    env = os.environ.get(env_var)
    if env:
        return float(env)
    return default


def _describe_timeout(args) -> float:
    return _resolve_timeout(args, env_var="BIOQ_DESCRIBE_TIMEOUT",
                            default=DESCRIBE_WAIT_TIMEOUT_S)


def _poll_timeout(args) -> float:
    return _resolve_timeout(args, env_var="BIOQ_POLL_TIMEOUT", default=POLL_TIMEOUT_S)
```

Note: `_describe_timeout`/`_poll_timeout` are kept as one-line wrappers so their
existing call sites (and the existing `test_describe_timeout_*` /
`test_poll_timeout_*` tests) keep working unchanged.

- [ ] **Step 5: Run the full suite**

Run: `uv run python -m pytest -q`
Expected: PASS (the new test + the existing `_describe_timeout`/`_poll_timeout` precedence tests).

- [ ] **Step 6: Commit**

```bash
git add bioq/commands.py bioq/tests/test_commands.py
git commit -m "refactor(bioq): merge describe/poll timeout resolvers"
```

---

## Task 1.3: Import & type hygiene

**Files:**
- Modify: `bioq/commands.py` (remove redundant local `UsageError` import)
- Modify: `bioq/client.py` (import `Config`; annotate `cfg`)
- Modify: `bioq/auth.py` (import `Config`; annotate `resolve_bearer`)

> This task changes no behavior, so there is no failing runtime test — `ruff`
> plus the existing suite are the guard. (Type annotations are strings under
> `from __future__ import annotations`, so they cannot fail at runtime.)

- [ ] **Step 1: Remove the now-redundant local `UsageError` import**

In `bioq/commands.py`, `_validate_job_id` (added in Phase 0) still contains a local
`from .errors import UsageError`. Delete that line — `UsageError` is already imported
at module top from Task 1.2:

```python
def _validate_job_id(job_id: str) -> str:
    """job_id is normally uuid4().hex[:20]. Accept only that ASCII shape so a
    user-supplied id can't build a `../`-escaping output dir."""
    if not job_id or any(ch not in _JOB_ID_CHARS for ch in job_id):
        raise UsageError(f"invalid job_id {job_id!r}")
    return job_id
```

- [ ] **Step 2: Annotate `cfg` in `client.py`**

In `bioq/client.py`, add the `Config` import (after the `from .auth import resolve_bearer` line):

```python
from . import tokens
from .auth import resolve_bearer
from .config import Config
from .errors import AuthError, ConflictError, GatewayError, NotFoundError
```

Update the two `cfg` annotations:

```python
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
```

```python
    @classmethod
    def from_url(cls, gateway_url: str, cfg: Config,
                 timeout: float = 60.0) -> GatewayClient:
```

- [ ] **Step 3: Annotate `cfg` in `auth.py`**

In `bioq/auth.py`, add the `Config` import and annotate the parameter:

```python
from . import oidc, tokens
from .config import Config
from .errors import AuthError


def resolve_bearer(cfg: Config) -> str | None:
```

- [ ] **Step 4: Run tests + lint**

Run:
- `uv run ruff check bioq/`
- `uv run python -m pytest -q`
Expected: PASS / no errors.

- [ ] **Step 5: Commit**

```bash
git add bioq/commands.py bioq/client.py bioq/auth.py
git commit -m "refactor(bioq): hoist imports + annotate cfg params"
```

---

## Phase 1 exit check

Before moving on, confirm the whole phase is green and shippable:

```bash
uv run python -m pytest -q
uv run ruff check bioq/
git log --oneline -3
```

All Phase 1 tasks are independent behavior-preserving refactors; if any test
fails, `git reset` that task's commit and re-run it in isolation.