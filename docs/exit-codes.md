# Exit Codes

English | [中文](exit-codes.zh.md)

> **Why (source):** Defined in `bioq/errors.py` — that file is the canonical source.
> Scripts and the skill branch on these numbers, so they are a **stable contract**.
> **Read when:** adding or changing any error path, or deciding which code a new
> failure maps to.
> **Remove/rewrite when:** essentially never. Renumbering requires a coordinated
> downstream migration; otherwise this table is permanent.

## Table

| code | meaning | error class |
|---|---|---|
| 0 | success | — |
| 2 | usage error (bad args) | `UsageError` |
| 3 | auth failed 401/403 | `AuthError` |
| 4 | not found 404 (unknown service or job) | `NotFoundError` |
| 5 | job failed (terminal failed/cancelled) | `JobFailedError` |
| 6 | completed but no results.zip | `NoOutputError` |
| 7 | gateway / dispatch error (5xx / 502) | `GatewayError` |
| 130 | Ctrl-C (`KeyboardInterrupt`) | — |

## Mapping rules

- `main()` catches `ConflictError` **before** `CLIError`. For **only** `run` and
  `submit`, a 409 means the job_id already exists = idempotent, treated as "already
  submitted" and returns `EXIT_OK` (0) (continue with `bioq status <job_id>`). For
  every other command a 409 is an ordinary gateway error → `EXIT_GATEWAY` (7).
  Although `ConflictError.exit_code` is `EXIT_GATEWAY`, it is only special-cased for
  `run`/`submit` via this early handling in `main()`, not as a normal failure.
- Ctrl-C does **not** cancel the remote job; reconnect with `bioq status <job_id>`.

## Adding a failure mode

Reuse an existing code/class; do **not** renumber. If genuinely novel, add a
`CLIError` subclass with a new `EXIT_*` constant in `bioq/errors.py`, then update this
table and `skills/bioq/SKILL.md`.

## How failures surface

- Normal results go to **stdout**; errors go to **stderr** as `error: <message>` (see
  `bioq/main.py`). Scripts must branch on the exit code, not on stderr text.
- **5 vs 6:** `5` means the gateway reported a terminal failure; `6` means the gateway
  said `completed` but produced no `results.zip` (FC-status masking — see
  `docs/commands.md`).

## Constants

Prefer these named constants over literal integers: `EXIT_OK`, `EXIT_USAGE`,
`EXIT_AUTH`, `EXIT_NOT_FOUND`, `EXIT_JOB_FAILED`, `EXIT_NO_OUTPUT`, `EXIT_GATEWAY`,
`EXIT_INTERRUPT` (mapping to the table above).

## See also

- `bioq/errors.py` — canonical definitions.
- `docs/commands.md` — where `5` and `6` are raised.
- `skills/bioq/SKILL.md` — how a using-agent should act on each code.