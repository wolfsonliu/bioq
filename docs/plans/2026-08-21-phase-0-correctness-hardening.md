# Phase 0 — Correctness & Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the correctness/security findings A1–A4 — scope 409 `ConflictError` idempotency to `run`/`submit`, turn the write-only `jobs.json` into a useful JSONL job history + `bioq recent`, remove the dead `poll(on_update)` parameter, and harden zip extraction / `job_id` handling.

**Architecture:** Phase 0 touches `bioq/main.py`, `bioq/errors.py`, `bioq/jobs.py`, `bioq/commands.py` and their tests. Each task is independently shippable: run tests after every step, commit at the end of each task, and **leave the repo green at every commit** (the registry rename is split add-then-remove across Tasks 0.2/0.3). The exit-code contract is never renumbered.

**Tech Stack:** Python ≥3.10, `httpx`, `pytest` (offline unit tests), `ruff`.

---

## Task 0.1: Scope 409 `ConflictError` idempotency to `run`/`submit`

**Files:**
- Modify: `bioq/main.py:128-139`
- Modify: `bioq/errors.py:49-52`
- Modify: `bioq/tests/test_main.py`
- Modify: `docs/exit-codes.md` (and `docs/exit-codes.zh.md`)

- [ ] **Step 1: Write the failing test**

Append to `bioq/tests/test_main.py` (after the existing `test_run_treats_409_as_already_submitted`, which must keep passing):

```python
def test_409_on_status_is_gateway_error_not_ok(monkeypatch):
    monkeypatch.setattr(mainmod, "load_config",
                        lambda **kw: Config(gateway_url="https://gw", profile=None))

    class _C:
        def get_job(self, job_id): raise ConflictError("conflict")
        def close(self): pass
    monkeypatch.setattr(mainmod.GatewayClient, "from_url",
                        classmethod(lambda cls, *a, **k: _C()))
    code = mainmod.main(["status", "j1"])
    assert code == 7  # EXIT_GATEWAY — a 409 on `status` is NOT "already submitted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest bioq/tests/test_main.py::test_409_on_status_is_gateway_error_not_ok -v`
Expected: FAIL — `assert 0 == 7` (current code returns `EXIT_OK` for any `ConflictError`).

- [ ] **Step 3: Gate the special case on `run`/`submit`**

In `bioq/main.py`, replace the `except ConflictError:` block (currently lines 130-133):

```python
    except ConflictError:
        # job_id already exists => idempotent: treat submit/run as "already
        # submitted" and exit 0 (the job is on the gateway; poll with `bioq status`).
        return EXIT_OK
```

with:

```python
    except ConflictError as exc:
        if args.command in ("run", "submit"):
            # job_id already exists => idempotent: treat submit/run as "already
            # submitted" and exit 0 (the job is on the gateway; poll with
            # `bioq status`).
            return EXIT_OK
        # Any other command's 409 is an ordinary gateway failure.
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run python -m pytest bioq/tests/test_main.py -v`
Expected: PASS — new test passes; `test_run_treats_409_as_already_submitted` still returns 0.

- [ ] **Step 5: Update the `ConflictError` docstring**

In `bioq/errors.py`, replace:

```python
class ConflictError(CLIError):
    """409 from the gateway — job_id already exists. `run` treats this as
    'already submitted' and proceeds to poll, so it is not fatal by itself."""
    exit_code = EXIT_GATEWAY
```

with:

```python
class ConflictError(CLIError):
    """409 from the gateway. For `run`/`submit` a 409 means the client-generated
    job_id already exists and is treated as idempotent ("already submitted") by
    `main.main`; for any other command it is an ordinary gateway error."""
    exit_code = EXIT_GATEWAY
```

- [ ] **Step 6: Sync the exit-codes doc**

In `docs/exit-codes.md`, the "Mapping rules" section has:

```
- `main()` catches `ConflictError` **before** `CLIError` and returns `EXIT_OK` (0): a
  409 means the job_id already exists = idempotent, treated as "already submitted"
  (continue with `bioq status <job_id>`). Although `ConflictError.exit_code` is
  `EXIT_GATEWAY`, it is only meaningful via this early, special-case handling in
  `main()`, not as a normal failure.
```

Replace with:

```
- `main()` catches `ConflictError` **before** `CLIError`. For **only** `run` and
  `submit`, a 409 means the job_id already exists = idempotent, treated as "already
  submitted" and returns `EXIT_OK` (0) (continue with `bioq status <job_id>`). For
  every other command a 409 is an ordinary gateway error → `EXIT_GATEWAY` (7).
  Although `ConflictError.exit_code` is `EXIT_GATEWAY`, it is only special-cased for
  `run`/`submit` via this early handling in `main()`, not as a normal failure.
```

Mirror the same wording change in `docs/exit-codes.zh.md` (translate the changed
sentences; keep the rest as-is).

- [ ] **Step 7: Commit**

```bash
git add bioq/main.py bioq/errors.py bioq/tests/test_main.py docs/exit-codes.md docs/exit-codes.zh.md
git commit -m "fix(bioq): scope 409 ConflictError idempotency to run/submit"
```

---

## Task 0.2: Add JSONL job-history functions (keep the old registry for now)

> Split note: this task **only adds** the new functions; the old `record_job` /
> `default_registry_path` stay in place (still used by `commands.py`) so the tree
> stays green. Task 0.3 switches `commands.py` over and then removes them.

**Files:**
- Modify: `bioq/jobs.py` (append new functions + `_HISTORY_MAX_EVENTS`)
- Modify: `bioq/tests/test_jobs.py` (extend imports + add tests)

- [ ] **Step 1: Write the failing tests**

In `bioq/tests/test_jobs.py`, extend the import (currently
`from bioq.jobs import TERMINAL, poll, record_job`) to:

```python
from bioq.jobs import (TERMINAL, history_path, poll, read_history, record_job,
                       record_status, record_submit)
```

Append these tests (keep the existing `test_record_job_appends` unchanged):

```python
def test_submit_and_status_events_roundtrip(tmp_path):
    p = tmp_path / "jobs.jsonl"
    record_submit(p, job_id="j1", svc="s", endpoint="e", profile="prod",
                  params={"num_seq_per_target": 2, "long": "x" * 300},
                  files={"pdb": "x.pdb"})
    record_status(p, job_id="j1", status="completed", output_dir="out", n_files=3)
    events = read_history(p, limit=10)
    assert [e["type"] for e in events] == ["submit", "status"]
    submit = events[0]
    assert submit["job_id"] == "j1" and submit["svc"] == "s"
    assert submit["params"]["num_seq_per_target"] == 2
    assert submit["params"]["long"].endswith("…") and len(submit["params"]["long"]) <= 201
    assert submit["files"] == {"pdb": "x.pdb"}
    status = events[1]
    assert status["status"] == "completed" and status["files"] == 3
    assert status["output_dir"] == "out"


def test_read_history_tolerates_malformed_line(tmp_path):
    p = tmp_path / "jobs.jsonl"
    p.write_text('{"type": "submit", "job_id": "ok"}\nGARBAGE\n', encoding="utf-8")
    assert [e["job_id"] for e in read_history(p)] == ["ok"]


def test_read_history_missing_file_returns_empty(tmp_path):
    assert read_history(tmp_path / "missing.jsonl") == []


def test_history_path_uses_state_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert str(history_path()) == str(tmp_path / "bioq" / "jobs.jsonl")


def test_history_file_is_0600(tmp_path):
    p = tmp_path / "jobs.jsonl"
    record_submit(p, job_id="j1", svc="s", endpoint="e")
    assert (p.stat().st_mode & 0o777) == 0o600
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest bioq/tests/test_jobs.py -v`
Expected: FAIL — `ImportError` (`history_path`/`read_history`/`record_submit`/`record_status` not defined).

- [ ] **Step 3: Add the new functions to `jobs.py`**

In `bioq/jobs.py`, add the capacity constant right after `TERMINAL` (line 10):

```python
TERMINAL = {"completed", "failed", "cancelled"}

_HISTORY_MAX_EVENTS = 500
```

Then append these functions at the END of `bioq/jobs.py` (leave `default_registry_path`
and `record_job` untouched above):

```python
def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _truncate(value, limit: int = 200):
    """Keep long values (esp. ``--set-json`` payloads) from bloating the history
    file. Scalars (int/float/bool/None) are stored as-is; strings are elided;
    lists/dicts are stored as a truncated repr."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, (list, dict)):
        return repr(value)[:limit]
    return value


def _append_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines.append(json.dumps(event, ensure_ascii=False))
    lines = lines[-_HISTORY_MAX_EVENTS:]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def read_history(path: Path, *, limit: int = 20) -> list[dict]:
    """Return the last ``limit`` events (newest last). Tolerates a missing file or
    a malformed trailing line (a torn write)."""
    if not path.exists():
        return []
    events = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return events[-limit:] if limit > 0 else events


def record_submit(path: Path, *, job_id: str, svc: str, endpoint: str,
                  profile: str | None = None, gateway_url: str | None = None,
                  params: dict | None = None, files: dict | None = None) -> None:
    _append_event(path, {
        "type": "submit",
        "job_id": job_id,
        "svc": svc,
        "endpoint": endpoint,
        "profile": profile,
        "gateway_url": gateway_url,
        "params": {k: _truncate(v) for k, v in (params or {}).items()},
        "files": files or {},
        "ts": _now_iso(),
    })


def record_status(path: Path, *, job_id: str, status: str,
                  output_dir: str | None = None, n_files: int | None = None) -> None:
    _append_event(path, {
        "type": "status",
        "job_id": job_id,
        "status": status,
        "output_dir": output_dir,
        "files": n_files,
        "ts": _now_iso(),
    })


def history_path() -> Path:
    from .config import get_state_dir
    return Path(get_state_dir()) / "bioq" / "jobs.jsonl"
```

The `json`, `time`, and `Path` imports already exist at the top of `jobs.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest bioq/tests/test_jobs.py -v`
Expected: PASS (new tests plus the still-present `test_record_job_appends`).

- [ ] **Step 5: Commit**

```bash
git add bioq/jobs.py bioq/tests/test_jobs.py
git commit -m "feat(bioq): add JSONL job history functions (submit/status/read)"
```

---

## Task 0.3: Wire history into lifecycle commands; remove the old registry

**Files:**
- Modify: `bioq/commands.py` (import line + `_build_and_submit`, `cmd_run`, `cmd_status`, `cmd_download`)
- Modify: `bioq/jobs.py` (delete `default_registry_path` + `record_job`)
- Modify: `bioq/tests/test_commands.py:43,51,59,66,95` (monkeypatch rename)
- Modify: `bioq/tests/test_main.py:63` (monkeypatch rename)
- Modify: `bioq/tests/test_jobs.py` (drop `record_job` import + `test_record_job_appends`)

- [ ] **Step 1: Write the failing test**

Append to `bioq/tests/test_commands.py`:

```python
def test_submit_records_history_event(tmp_path, monkeypatch):
    import json
    p = tmp_path / "jobs.jsonl"
    monkeypatch.setattr(commands, "history_path", lambda: p)
    c = _Client()
    commands.cmd_submit(c, _args(set=["num_seq_per_target=2"]))
    events = [json.loads(ln) for ln in p.read_text().splitlines()]
    assert events[0]["type"] == "submit"
    assert events[0]["svc"] == "proteinmpnn-server"
    assert events[0]["params"] == {"num_seq_per_target": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest bioq/tests/test_commands.py::test_submit_records_history_event -v`
Expected: FAIL — `AttributeError: module 'bioq.commands' has no attribute 'history_path'`.

- [ ] **Step 3: Update the `jobs` import in `commands.py`**

In `bioq/commands.py`, replace:

```python
from .jobs import TERMINAL, default_registry_path, poll, record_job
```

with:

```python
from .jobs import TERMINAL, history_path, poll, record_status, record_submit
```

- [ ] **Step 4: Add a `_file_names` helper and rewrite `_build_and_submit`**

In `bioq/commands.py`, add just above `_build_and_submit`:

```python
def _file_names(file_args: list[str]) -> dict[str, str]:
    """field -> basename for ``--file field=path`` args (for the local history log)."""
    return {arg.split("=", 1)[0]: Path(arg.split("=", 1)[1]).name
            for arg in file_args}
```

Replace the body of `_build_and_submit` (currently lines 145-152) with:

```python
def _build_and_submit(client, args) -> str:
    svc = _canonical_svc(args.svc)
    job_id = uuid.uuid4().hex[:20]
    file_uris = upload_files(client, job_id, args.file)
    body = build_body(sets=args.set, set_jsons=args.set_json, file_uris=file_uris)
    client.run(svc, args.endpoint, job_id, body)
    record_submit(
        history_path(),
        job_id=job_id,
        svc=svc,
        endpoint=args.endpoint,
        profile=getattr(args, "profile", None),
        gateway_url=getattr(args, "gateway_url", None),
        params={k: v for k, v in body.items() if not k.endswith("_uri")},
        files=_file_names(args.file),
    )
    return job_id
```

- [ ] **Step 5: Record status events in `cmd_run`, `cmd_status`, `cmd_download`**

In `bioq/commands.py`:

`cmd_run` — replace its poll/error and success branches with:

```python
    timeout = _poll_timeout(args)
    job = poll(client, job_id, interval=POLL_INTERVAL_S, timeout=timeout)
    if job["status"] != "completed":
        record_status(history_path(), job_id=job_id, status=job["status"])
        raise JobFailedError(f"job {job_id} ended with status={job['status']}")
    out_dir = Path(args.out) if args.out else Path(f"./{job_id}")
    n = _extract_download(client, job_id, out_dir)
    record_status(history_path(), job_id=job_id, status="completed",
                  output_dir=str(out_dir), n_files=n)
    emit({"job_id": job_id, "status": "completed", "output_dir": str(out_dir),
          "files": n}, fmt=args.output)
    return 0
```

`cmd_status` — after `job` is resolved (single-shot or poll), before `emit`, add:

```python
    if job.get("status") in TERMINAL:
        record_status(history_path(), job_id=args.job_id, status=job["status"])
```

`cmd_download` — after `n = _extract_download(...)`, before its `emit`, add:

```python
    record_status(history_path(), job_id=args.job_id, status="completed",
                  output_dir=str(out_dir), n_files=n)
```

- [ ] **Step 6: Rename the `default_registry_path` monkeypatches**

In `bioq/tests/test_commands.py`, replace every occurrence of
`monkeypatch.setattr(commands, "default_registry_path", lambda: tmp_path / "j.json")`
(lines 43, 51, 59, 66, 95) with:

```python
    monkeypatch.setattr(commands, "history_path", lambda: tmp_path / "jobs.jsonl")
```

In `bioq/tests/test_main.py:63`, replace
`monkeypatch.setattr("bioq.commands.default_registry_path", lambda: tmp_path / "j.json")`
with:

```python
    monkeypatch.setattr("bioq.commands.history_path", lambda: tmp_path / "jobs.jsonl")
```

- [ ] **Step 7: Remove the old registry (now unused)**

In `bioq/jobs.py`, delete the now-unused `default_registry_path` and `record_job`
functions (the old registry block that used to sit between `poll` and the new functions).

In `bioq/tests/test_jobs.py`, drop `record_job` from the import and delete
`test_record_job_appends` (the history round-trip test already covers persistence).
The import becomes:

```python
from bioq.jobs import (TERMINAL, history_path, poll, read_history,
                       record_status, record_submit)
```

- [ ] **Step 8: Run the full test suite + lint**

Run:
- `uv run python -m pytest -q`
- `uv run ruff check bioq/`
Expected: PASS / no errors.

- [ ] **Step 9: Commit**

```bash
git add bioq/commands.py bioq/jobs.py bioq/tests/test_commands.py bioq/tests/test_main.py bioq/tests/test_jobs.py
git commit -m "feat(bioq): record submit/status events; drop legacy registry"
```

---

## Task 0.4: Add the `bioq recent` read-only command + docs

**Files:**
- Modify: `bioq/main.py` (`_NO_CLIENT` + `build_parser`)
- Modify: `bioq/commands.py` (import `read_history` + `cmd_recent` + `_print_history_event`)
- Modify: `bioq/tests/test_main.py`, `bioq/tests/test_commands.py`
- Modify: `docs/commands.md`, `docs/commands.zh.md`, `docs/architecture.md`, `docs/architecture.zh.md`, `README.md`, `README.zh.md`, `skills/bioq/SKILL.md`

- [ ] **Step 1: Write the failing tests**

In `bioq/tests/test_main.py`, append:

```python
def test_parser_recent():
    ns = mainmod.build_parser().parse_args(["recent", "--limit", "5", "--output", "json"])
    assert ns.command == "recent"
    assert ns.limit == 5
    assert ns.output == "json"


def test_recent_is_offline_no_gateway(tmp_path, monkeypatch):
    monkeypatch.setattr("bioq.commands.history_path", lambda: tmp_path / "jobs.jsonl")
    assert mainmod.main(["recent"]) == 0
```

In `bioq/tests/test_commands.py`, append:

```python
def test_cmd_recent_pretty_and_json(tmp_path, monkeypatch, capsys):
    import json
    p = tmp_path / "jobs.jsonl"
    monkeypatch.setattr(commands, "history_path", lambda: p)
    commands.cmd_submit(_Client(), _args(set=["n=1"]))
    # pretty
    commands.cmd_recent(_args(output="pretty"))
    out = capsys.readouterr().out
    assert "submit" in out and "proteinmpnn-server" in out
    # json
    commands.cmd_recent(_args(output="json"))
    events = json.loads(capsys.readouterr().out)
    assert isinstance(events, list) and events[0]["type"] == "submit"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
- `uv run python -m pytest bioq/tests/test_main.py::test_parser_recent -v`
Expected: FAIL — argparse `SystemExit` (unrecognized `recent`).
- `uv run python -m pytest bioq/tests/test_commands.py::test_cmd_recent_pretty_and_json -v`
Expected: FAIL — `AttributeError: module 'bioq.commands' has no attribute 'cmd_recent'`.

- [ ] **Step 3: Register the `recent` subcommand and offline dispatch**

In `bioq/main.py`, add `"recent"` to `_NO_CLIENT`:

```python
_NO_CLIENT = {
    "login": commands.cmd_login,
    "logout": commands.cmd_logout,
    "config": commands.cmd_config,
    "recent": commands.cmd_recent,
}
```

In `build_parser`, after the `config` subparser block (after line 100), add:

```python
    rec = sub.add_parser("recent", parents=[common])
    rec.add_argument("--limit", type=int, default=20,
                     help="show the last N history events (default: 20)")
```

- [ ] **Step 4: Implement `cmd_recent` + `_print_history_event`**

In `bioq/commands.py`, extend the `jobs` import (from Task 0.3) to add `read_history`:

```python
from .jobs import (TERMINAL, history_path, poll, read_history,
                   record_status, record_submit)
```

Append to `bioq/commands.py` (near the other no-client commands / at the bottom):

```python
def cmd_recent(args) -> int:
    """List the local job history (offline — reads only jobs.jsonl)."""
    events = read_history(history_path(), limit=getattr(args, "limit", 20))
    if args.output == "json":
        emit(events, fmt="json")
        return 0
    if not events:
        print("no recent jobs yet (submit/run records local history)")
        return 0
    for e in events:
        _print_history_event(e)
    return 0


def _print_history_event(e: dict) -> None:
    ts = e.get("ts", "")
    if e.get("type") == "status":
        n = e.get("files")
        where = f"  {e.get('output_dir')}" if e.get("output_dir") else ""
        count = f"  ({n} files)" if n is not None else ""
        print(f"{ts}  {e.get('job_id')}  {e.get('status')}{where}{count}")
    else:
        print(f"{ts}  {e.get('job_id')}  submit  "
              f"{e.get('svc', '')} {e.get('endpoint', '')}")
```

- [ ] **Step 5: Run the full test suite**

Run: `uv run python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Sync docs**

Add the following row to the command table (after the `bioq cancel` row) in **each** of
`docs/commands.md`, `README.md`, and `skills/bioq/SKILL.md`:

```markdown
| `bioq recent [--limit N]` | list local job history (submit/status events) |
```

Chinese mirrors — add the equivalent row to `docs/commands.zh.md` and `README.zh.md`:

```markdown
| `bioq recent [--limit N]` | 列出本地作业历史（submit/status 事件） |
```

In `docs/commands.md`, update the `run / submit` section's pipeline description
(currently `… → \`client.run\` → \`record_job\` (local registry)`) to:

```
`_build_and_submit`: canonicalize svc → `uuid.uuid4().hex[:20]` job_id → `upload_files`
→ `build_body` → `client.run` → `record_submit` (local history). On terminal status,
`cmd_run`/`cmd_status`/`cmd_download` append a `record_status` event to the same
`jobs.jsonl`. `bioq recent` reads it back (offline).
```

Mirror that in `docs/commands.zh.md`.

In `docs/architecture.md`, update the `jobs.py` line in the layout tree (line 24) from:

```
├── jobs.py             poll loop (transient-error tolerant) + local recent-job registry
```

to:

```
├── jobs.py             poll loop (transient-error tolerant) + local job history (JSONL) + recent
```

and mirror in `docs/architecture.zh.md`.

- [ ] **Step 7: Commit**

```bash
git add bioq/main.py bioq/commands.py bioq/tests/test_main.py bioq/tests/test_commands.py
git add docs/commands.md docs/commands.zh.md docs/architecture.md docs/architecture.zh.md README.md README.zh.md skills/bioq/SKILL.md
git commit -m "feat(bioq): bioq recent command + local job history docs"
```

---

## Task 0.5: Remove the dead `poll(..., on_update)` parameter

**Files:**
- Modify: `bioq/jobs.py:13-36`

- [ ] **Step 1: Verify existing poll tests are the safety net**

Run: `uv run python -m pytest bioq/tests/test_jobs.py -q`
Expected: PASS (these lock the poll behavior; no caller uses `on_update`).

- [ ] **Step 2: Remove the dead parameter and its tracking**

In `bioq/jobs.py`, replace the `poll` signature and body (lines 13-36) with:

```python
def poll(client, job_id: str, *, interval: float, timeout: float,
         max_transient: int = 10) -> dict:
    deadline = time.time() + timeout
    transient = 0
    while time.time() < deadline:
        try:
            job = client.get_job(job_id)
        except GatewayError:
            transient += 1
            if transient > max_transient:
                raise
            time.sleep(max(interval, 1))
            continue
        except CLIError:
            raise
        transient = 0
        if job.get("status") in TERMINAL:
            return job
        time.sleep(interval)
    raise GatewayError(f"timed out waiting for job {job_id} after {timeout}s")
```

(`on_update` and `last_status` are gone.)

- [ ] **Step 3: Run tests + lint**

Run:
- `uv run python -m pytest -q`
- `uv run ruff check bioq/`
Expected: PASS / no errors.

- [ ] **Step 4: Commit**

```bash
git add bioq/jobs.py
git commit -m "refactor(bioq): remove dead poll(on_update) parameter"
```

---

## Task 0.6: Harden zip extraction and `job_id` handling

**Files:**
- Modify: `bioq/commands.py` (`_extract_download` + add `_safe_extract` + `_validate_job_id`; use it in `cmd_status`/`cmd_download`/`cmd_cancel`)
- Modify: `bioq/tests/test_commands.py`

- [ ] **Step 1: Write the failing tests**

In `bioq/tests/test_commands.py`, add `UsageError` to the top import (line 9) so it reads:

```python
from bioq.errors import JobFailedError, NoOutputError, UsageError
```

Append:

```python
def test_extract_download_rejects_path_traversal(tmp_path):
    class C:
        def download(self, job_id, dest):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("../evil.txt", "x")
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(buf.getvalue())
            return dest

    with pytest.raises(NoOutputError):
        commands._extract_download(C(), "j1", tmp_path / "out")


def test_validate_job_id_accepts_hex_rejects_traversal():
    assert commands._validate_job_id("abc123_-") == "abc123_-"
    with pytest.raises(UsageError):
        commands._validate_job_id("../etc")
    with pytest.raises(UsageError):
        commands._validate_job_id("a/b")
    with pytest.raises(UsageError):
        commands._validate_job_id("")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest bioq/tests/test_commands.py::test_extract_download_rejects_path_traversal bioq/tests/test_commands.py::test_validate_job_id_accepts_hex_rejects_traversal -v`
Expected: FAIL — the first currently extracts `../evil.txt` (no raise); the second is an `AttributeError` (`_validate_job_id` missing).

- [ ] **Step 3: Implement `_safe_extract` and `_validate_job_id`**

In `bioq/commands.py`, add near the top (after the constants):

```python
_JOB_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _validate_job_id(job_id: str) -> str:
    """job_id is normally uuid4().hex[:20]. Accept only that ASCII shape so a
    user-supplied id can't build a `../`-escaping output dir."""
    from .errors import UsageError
    if not job_id or any(ch not in _JOB_ID_CHARS for ch in job_id):
        raise UsageError(f"invalid job_id {job_id!r}")
    return job_id


def _safe_extract(z: zipfile.ZipFile, out_dir: Path) -> None:
    """extractall with a zip-slip guard: every member must resolve inside out_dir."""
    root = str(out_dir.resolve())
    for member in z.infolist():
        target = str((out_dir / member.filename).resolve())
        try:
            common = os.path.commonpath([root, target])
        except ValueError:
            raise NoOutputError(
                f"refusing to extract {member.filename!r}: escapes output dir")
        if common != root:
            raise NoOutputError(
                f"refusing to extract {member.filename!r}: escapes output dir")
    z.extractall(out_dir)
```

In `_extract_download`, replace `z.extractall(out_dir)` (currently line 171) with:

```python
        _safe_extract(z, out_dir)
```

- [ ] **Step 4: Validate `job_id` in the three user-input commands**

In `bioq/commands.py`, add `_validate_job_id(args.job_id)` as the first statement of
`cmd_status`, `cmd_download`, and `cmd_cancel`. For example, `cmd_download` becomes:

```python
def cmd_download(client, args) -> int:
    _validate_job_id(args.job_id)
    out_dir = Path(args.out) if args.out else Path(f"./{args.job_id}")
    ...
```

(Do the same for `cmd_status` and `cmd_cancel`. `cmd_run`'s job_id is internally
generated hex, so it does not need the check.)

- [ ] **Step 5: Run the full test suite + lint**

Run:
- `uv run python -m pytest -q`
- `uv run ruff check bioq/`
Expected: PASS / no errors.

- [ ] **Step 6: Commit**

```bash
git add bioq/commands.py bioq/tests/test_commands.py
git commit -m "fix(bioq): guard zip extraction (zip-slip) + validate job_id"
```