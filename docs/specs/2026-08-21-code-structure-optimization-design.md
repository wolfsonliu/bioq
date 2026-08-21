# Code-Structure Optimization Roadmap — Design

> Status: approved (2026-08-21). Scope: bioq CLI only (this repo). Approach:
> bugfix-first, phase-by-phase, each phase independently shippable/rollback-able.

## Problem Statement

The bioq codebase is structurally healthy — a thin, single-layer package with
clear module boundaries, EN/ZH docs, and disciplined hard constraints. An audit
of `bioq/*.py` surfaced a small set of correctness risks, dead/hidden code, and
duplication worth resolving. Two of the findings (the 409 `ConflictError`
special-case and the write-only `jobs.json`) are **contract-relevant**: their
semantics are documented in `docs/exit-codes.md`, `docs/commands.md`, and
`skills/bioq/SKILL.md`, so any change must keep those three (plus the EN/ZH
mirrors and `README.md`) in lockstep.

Findings (labels map to the checklist in this doc):

- **A1** — `ConflictError` (409) is caught for *all* commands in `main.main()`,
  returning `EXIT_OK`, but only `run`/`submit` should treat 409 as idempotent;
  other commands silently report success on a real conflict.
- **A2** — `jobs.json` is write-only: `record_job` appends on every submit but no
  code path reads it, so it is effectively invisible (looks like dead code even
  though the intent is a local audit trail).
- **A3** — `jobs.poll(..., on_update)` + `last_status` are dead parameters (no
  caller passes `on_update`).
- **A4** — unvalidated `zipfile.extractall` and user-controlled `job_id` path
  building (zip-slip / path traversal; low risk, gateway is trusted).
- **B5** — `commands.py` (293 lines) mixes short-name canonicalization, describe
  rendering, timeout resolution, lifecycle handlers, and the offline
  login/logout/config commands; `_describe_timeout`/`_poll_timeout` near-duplicate.
- **B6** — `_PUT_TIMEOUT` duplicated in `client.py` and `upload.py`.
- **B7** — module-level `_current_config` global in `config.py` (implicit state).
- **B8** — hand-rolled TOML writer in `config.py` (documented tradeoff).
- **B9** — untyped `cfg` params + inconsistent function-local imports.

## Proposed Solution

Tiered, bugfix-first roadmap of four phases + a decision gate. Phases 0–1 are
low-risk and high-value; Phase 2 is optional structural tidying; Phase 3 items are
explicitly kept (or deferred). The exit-code contract is never renumbered; any new
command/behavior is covered by tests and synced to the three contract docs + their
zh mirrors + `README.md`.

## Detailed Design

### Phase 0 — Correctness & hardening

#### P0-1 · Scope `ConflictError` to `run`/`submit` (A1)

**Decision (approved):** keep the "409 = already submitted" idempotent semantics,
but apply it **only** to `run` and `submit`.

- `bioq/main.py`: in the `_COMMANDS` dispatch's `except ConflictError` handler,
  gate on `args.command in {"run", "submit"}`:
  - run/submit → `return EXIT_OK` (unchanged behavior);
  - anything else → fall through to the normal `CLIError` path (print
    `error: ...` to stderr, return `exc.exit_code` = `EXIT_GATEWAY`).
- `bioq/errors.py`: update `ConflictError` docstring to state it is only special
  from `run`/`submit`; all other 409s are ordinary gateway errors.
- Sync: `docs/exit-codes.md` (mapping-rules note) — change "a 409 means the
  job_id already exists" to clarify it applies to `run`/`submit` only.

#### P0-2 · Turn `jobs.json` into a local job history / audit log (A2)

**Decision (approved):** full version — JSONL append + submit/status events + a
read-only `bioq recent` command + docs/tests. Intent: a local, inspectable record
of what was submitted and how it ended, for debugging.

- **Format:** switch from a single JSON array (rewritten on each submit) to
  append-only JSON Lines at `~/.local/state/bioq/jobs.jsonl` (path via
  `get_state_dir()`), mode `0600`.
- **Events** (one JSON object per line):
  - `submit`: `{"type": "submit", "job_id", "svc", "endpoint", "profile",
    "gateway_url", "params"?, "files"?, "ts"}` — written in `_build_and_submit`.
    `params` = `--set`/`--set-json` keys with values truncated (long values,
    e.g. `--set-json sequences=@file`, elided to avoid bloat); `files` =
    `field -> filename`. **Never log secrets** (token / client_secret).
  - `status`: `{"type": "status", "job_id", "status", "output_dir"?, "files"?,
    "ts"}` — appended whenever a terminal state is observed (`run --wait`,
    `cmd_download`, or `cmd_status` when it resolves a terminal state).
- **Bounding:** keep the last N events (e.g. 500) by trimming the oldest lines on
  write.
- **New command `bioq recent [--limit N] [--output json]`:**
  - registered in `_NO_CLIENT` (it reads only the local file and must run without
    a gateway/`load_config`, like `login`/`logout`/`config`);
  - pretty prints the last N events (default 20); JSON is a `jq`-stable array;
  - reads via `get_state_dir()` with `_current_config` unset, i.e. honors
    `XDG_STATE_HOME` but not a profile's custom `state_dir` (see Open Questions).
- **Module:** keep in `bioq/jobs.py` to limit churn — rename `record_job` →
  `record_submit`, add `record_status` + `read_history`, replace
  `default_registry_path` with `history_path`.
- **Tests:** `test_jobs.py` — submit/status append, JSONL round-trip, malformed
  trailing line tolerated, trim-to-N. `test_commands.py` — `cmd_recent` pretty +
  json. `test_main.py` — `recent` dispatches without a gateway.
- **Sync:** `docs/commands.md`, `README.md` command table, `skills/bioq/SKILL.md`
  command reference + a "find a forgotten job_id: `bioq recent`" note.

#### P0-3 · Remove dead `poll(..., on_update)` (A3)

Remove the `on_update` parameter and the `last_status` tracking from
`bioq/jobs.py` (no caller uses it). If status-transition printing is later wanted
for `run --wait`, re-introduce it as a small, tested feature rather than an
unused stub.

#### P0-4 · Zip/path safety guard (A4)

- `bioq/commands.py` `_extract_download`: before `extractall`, verify every
  `ZipInfo` member resolves inside `out_dir` (`os.path.realpath` + `commonpath`);
  skip-or-raise on escape.
- Validate user-supplied `job_id` (for `status`/`download`/`cancel`) against a
  safe charset (e.g. `[A-Za-z0-9_-]+`) → `UsageError` otherwise; this also stops
  `./{job_id}` path building from escaping.

### Phase 1 — Low-cost cleanup (DRY / hygiene)

- **P1-5 (B6):** single-source `_PUT_TIMEOUT` in `bioq/client.py`; import it in
  `upload.py`.
- **P1-6 (B5 partial):** merge `_describe_timeout`/`_poll_timeout` into one
  `_resolve_timeout(args, env_var, default)` in `commands.py` (or a shared helper
  module).
- **P1-7 (B9):** hoist function-local imports (`UsageError`, `tomllib`) to module
  top as consistent with the rest; annotate `cfg` parameters (`_BioqAuth.__init__`,
  `GatewayClient.from_url`, `resolve_bearer`) with `Config`.

### Phase 2 — Structural refactor (optional, medium)

- **P2-8 (B5):** split `commands.py` into at most 2–3 modules, respecting "stay
  thin": `describe.py` (`_canonical_svc` + `_print_describe_cli` + `_describe_wait`),
  move `login`/`logout`/`config` into `bioq/authcmds.py` (offline commands), and
  keep `run`/`submit`/`status`/`download`/`cancel` in `commands.py`. Do **not**
  over-split.
- **P2-9 (B7):** `_current_config` — recommend **keep + document** (single-threaded
  CLI; benefit of explicit threading is marginal). If revisited, use explicit
  passing or `contextvars`, not a module global. (Deferred.)

### Phase 3 — Decision gate (deferred / keep)

- **P3-10 (B8):** keep the hand-rolled TOML writer — it is a documented tradeoff
  forced by the "dependency restraint (tomli only on 3.10)" constraint. Only
  revisit if a `tomli_w` dependency is ever accepted.
- **P3-11:** `_canonical_svc` case handling and remaining type-annotation polish —
  low priority.

### Out of scope

No gateway-protocol changes; no FC / OSS / JWT logic; no exit-code renumbering;
no new runtime dependency.

## Success Criteria

- Exit-code numbers unchanged; `ConflictError` idempotency applies only to
  `run`/`submit`, and a 409 on `status`/`download`/`cancel` surfaces as a normal
  gateway error (stderr + exit 7).
- `bioq recent` (pretty + `--output json`) lists local history; `jobs.jsonl` is
  append-only, capped, `0600`, and never contains secrets.
- `run --wait`/`download` never extract outside the target directory; a malformed
  `job_id` is rejected as a usage error.
- `uv run python -m pytest -q` green after each phase, with added coverage for
  every changed behavior; contract docs + zh mirrors + `README.md` + `SKILL.md`
  in sync.

## Open Questions

1. `bioq recent` path resolution: default to `XDG_STATE_HOME` (ignoring a
   profile's custom `state_dir`) as proposed, or do a light TOML-only read to
   honor `state_dir` without requiring a gateway? Leaning: default path only, to
   keep `recent` offline and simple.
2. Should `status` events truncate param values (proposed) or store full scalar
   `--set` values? Full scalars are more debuggable but can grow; propose
   truncating only very long values.
3. `poll(..., on_update)` removal confirmed as "delete" (not "wire up progress"),
   pending any desire for `run --wait` status-transition output.