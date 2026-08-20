# diffdock Cold-Start `describe` Tolerance — Design

> Status: approved (2026-08-20). Scope: bioq CLI only (this repo).

## Problem Statement

`GET /v1/services/{svc}` builds `manifest.endpoints` by fetching the downstream
FC function's `/openapi.json` (the manifest carries `openapi_url`), so while a
service cold-starts the returned endpoint list can be empty. bioq's pretty
`describe` then prints a terse, confusing banner:

```
diffdock: no runnable task endpoints found; try `--output json`
```

The root fix — make the gateway serve a static/cached endpoint list instead of
deriving it from a warm FC — belongs to the gateway, which is out of scope here.
Within bioq we can only (a) say clearly what is happening and (b) optionally wait
the cold start out. Per the "stay thin" constraint, bioq adds no FC/keep-warm
logic.

## Proposed Solution

1. **A** — reword the empty-endpoints banner in `_print_describe_cli` to name
   the cause (cold start) and the remedy (retry, or `--wait`).
2. **B** — add `describe --wait [--timeout Ns]` that re-fetches `/v1/services/{svc}`
   on a fixed interval until `/api/tasks/*` endpoints appear (or timeout).
   `--output json` is untouched (single, faithful fetch).

## Detailed Design

### `bioq/commands.py`

- Add `import time` and module constants:
  - `DESCRIBE_WAIT_INTERVAL_S = 2.0`
  - `DESCRIBE_WAIT_TIMEOUT_S = 120.0`
- `cmd_describe`:
  1. canonicalize svc (`_canonical_svc`);
  2. `client.describe(svc)` once;
  3. if `output == "json"`: `emit` the raw payload and return (no retry);
  4. if `args.wait`: `info = _describe_wait(client, svc, timeout=...)`;
  5. render via `_print_describe_cli(info, svc_short=..., only=...)`.
- `_describe_wait(client, svc, *, timeout, interval=DESCRIBE_WAIT_INTERVAL_S)`:
  - deadline = now + timeout; fetch once;
  - while `_task_endpoints(info)` is empty and `time.time() < deadline`:
    `time.sleep(interval)` then re-fetch;
  - return the last `info` (never raises on timeout — the caller renders the
    empty-endpoints hint).
- `_describe_timeout(args)`: `--timeout` > `BIOQ_DESCRIBE_TIMEOUT` env >
  `DESCRIBE_WAIT_TIMEOUT_S` default; a value `<= 0` raises `UsageError`
  (mirrors `_poll_timeout`).
- `_print_describe_cli` empty branch becomes a multi-line hint:
  - `{svc_short}: gateway returned no runnable task endpoints`
  - `(endpoint list can be empty while the service cold-starts)`
  - `retry in a few seconds, or wait: bioq describe {svc_short} --wait`
  - `raw payload, if any: --output json`

### `bioq/main.py`

- `describe` subparser gains:
  - `--wait` (`store_true`) — wait for runnable endpoints to appear (cold-start tolerance);
  - `--timeout` (float, default `None`) — max seconds to wait when `--wait` is set
    (help references `BIOQ_DESCRIBE_TIMEOUT`).

### Behavior / contracts

- Exit code stays **0** for the empty case — `describe` reporting "no endpoints"
  is not a failure, and exit codes are a stable contract (no renumbering).
- `--output json` + `--wait`: `--wait` is ignored — the JSON is a single, faithful
  fetch and stays `jq`-stable.
- `--wait` + `<endpoint>`: `_describe_wait` waits for *any* `/api/tasks/*` to
  appear (they all come from the same openapi.json); the existing `only` filter
  then resolves the specific endpoint.
- Not doing: client-side keep-warm / FC ping (stay-thin), gateway manifest caching
  (out of repo).

### Tests

- `test_commands.py`:
  - `--wait` polls empty→populated and returns the populated manifest;
  - `--wait` with always-empty manifest + tiny timeout returns the empty manifest
    and prints the new banner;
  - `--output json` + `--wait` performs exactly one fetch;
  - `_describe_timeout` precedence (flag > env > default) and non-positive → `UsageError`;
  - empty-manifest banner text.
- `test_main.py`: `describe` parser accepts `--wait` and `--timeout`.

### Docs to sync (English canonical + zh mirrors)

- `docs/commands.md` / `commands.zh.md` — describe `--wait`/`--timeout` and the
  empty-endpoints behavior.
- `README.md` / `README.zh.md` — describe row in the command table + cold-start note.
- `skills/bioq/SKILL.md` — describe flags + "cold-start: use `--wait`" guidance.

## Success Criteria

- `bioq describe diffdock` during cold start prints an actionable cold-start hint,
  not the old terse banner.
- `bioq describe diffdock --wait` holds until endpoints appear, then renders normally.
- `bioq --output json describe diffdock` returns the raw manifest unchanged.
- Exit codes unchanged; `uv run python -m pytest -q` green.

## Open Questions

1. Confirm whether the cold case is `200`-with-empty-endpoints or a `5xx` from the
   gateway's openapi proxy. If `5xx` is also observed, `_describe_wait` should
   tolerate `GatewayError` the way `jobs.poll` does.
2. Confirm honoring `BIOQ_DESCRIBE_TIMEOUT` (default: yes, mirroring `BIOQ_POLL_TIMEOUT`).
3. `--wait` timeout keeps exit 0 (proposed) rather than a new non-zero — to honor
   the exit-code contract.