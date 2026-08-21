# Commands & Input Construction

English | [中文](commands.zh.md)

> **Why (source):** Derived from `src/bioq/commands.py`, `describe.py`, `authcmds.py`,
> `upload.py`, `params.py`, `jobs.py`, and `output.py`, and verified against `src/bioq/main.py`.
> This describes the user-visible CLI behavior.
> **Read when:** changing CLI behavior, adding/renaming a subcommand or flag, or
> changing upload / param semantics.
> **Remove/rewrite when:** a command or flag changes — then also sync
> `skills/bioq/SKILL.md` and `README.md`'s command table.

## Command reference

| command | purpose |
|---|---|
| `bioq services` | list services (short names, `-server` stripped) |
| `bioq describe <svc> [<endpoint>]` | endpoints / `--file` / `--set` params (human view by default) |
| `bioq run <svc> <endpoint> [...] [--wait -o <dir>]` | upload + submit + (with `--wait`) poll + download/extract |
| `bioq submit <svc> <endpoint> [...]` | submit only; prints `job_id` |
| `bioq status <job_id> [--timeout <s>]` | query status (polls to terminal when a timeout is given) |
| `bioq download <job_id> -o <dir>` | download + extract results zip |
| `bioq cancel <job_id>` | best-effort cancel |
| `bioq recent [--limit N]` | list local job history (submit/status events) |
| `bioq login` / `logout` / `config` | local credential management (offline) |

## Service names

`_canonical_svc(name)` accepts a short name (`proteinmpnn`) or the canonical registry
key (`proteinmpnn-server`); it appends `-server` when missing. The gateway and its docs
use the canonical form; users type the short form shown by `bioq services`. The
strip/append logic lives **only** in `commands._canonical_svc` — don't duplicate it.

## describe

- Default (pretty) view: takes the `/api/tasks/<name>` endpoints from `manifest`,
  splits `request_fields` into **files** (`is_file`) and **params** (non-file,
  excluding each file's `<field>_uri` companion), and renders `--file` / `--set`
  tables plus a copy-paste `bioq run ...` example. `--output json` returns the raw
  manifest+openapi payload.
- `--wait [--timeout <s>]` (pretty only): if the manifest has no runnable
  `/api/tasks/*` endpoints (a service still cold-starting), re-fetch
  `/v1/services/{svc}` every `DESCRIBE_WAIT_INTERVAL_S` (2s) until endpoints appear
  or the timeout is hit. Timeout = `--timeout` > `BIOQ_DESCRIBE_TIMEOUT` env >
  `DESCRIBE_WAIT_TIMEOUT_S` (120s). `--output json` ignores `--wait` (single,
  faithful fetch); an empty endpoint list prints an actionable cold-start hint and
  still exits 0.
- `<endpoint>` may contain a slash (nested): `bioq run rfdiffusion generate/motif`.

## run / submit

`_build_and_submit`: canonicalize svc → `uuid.uuid4().hex[:20]` job_id → `upload_files`
→ `build_body` → `client.run` → `record_submit` (local history). On terminal status,
`cmd_run`/`cmd_status`/`cmd_download` append a `record_status` event to the same
`jobs.jsonl`. `bioq recent` reads it back (offline; it reads the default
`XDG_STATE_HOME`/`~/.local/state` file and does **not** honor a profile's custom
`state_dir`).

- `cmd_run --wait`: poll to terminal → non-`completed` raises `JobFailedError`
  (exit 5) → otherwise download + extract; **empty `results.zip` raises
  `NoOutputError` (exit 6)**.
- **`status=completed` ≠ has output.** FC async marks a container that returned 500
  as "Succeeded". `--wait`/`download` therefore download **and validate** the zip;
  empty → exit 6. *(Why: guards FC-status masking; remove-when the gateway guarantees
  output on `completed`.)*
- `_extract_download`: download to `<out>/<job_id>.zip`; `namelist()` empty →
  `NoOutputError`; else `extractall` into the out dir.
- `_poll_timeout`: `--timeout` > `BIOQ_POLL_TIMEOUT` env > default `21600s` (6h).
- `cmd_status`: single query by default; polls only when `--timeout` (or
  `BIOQ_POLL_TIMEOUT`) is present and the job isn't already terminal.
- Constants: `POLL_INTERVAL_S = 10.0`; `TERMINAL = {"completed","failed","cancelled"}`.

## Uploads (`src/bioq/upload.py`)

`--file <field>=<path>`: sha256 → `prepare_upload(job_id, filename, sha256)` → cache
hit (`exists`) skips transfer → else PUT the bytes → collect `pre["uri"]`.

- OSS presigned absolute URL → bare `httpx.put` (no gateway auth).
- Gateway-relative URL (`/v1/files/<key>`) → `client.put_file`, which resolves against
  `base_url` **and** carries auth.
- Same `field` repeated → collapse to a list; the body key is `{field}_uri`, and
  `<field>` must match the downstream service's `<field>_uri` form field.

## Params (`src/bioq/params.py`)

`build_body`: `--set k=v` does light type inference (`true/false`→bool, int-able→int,
float-able→float, else str); `--set-json k=<json>|@file.json` runs `json.loads`
(`@` prefix reads a file); finally `body.update(file_uris)` overrides with `{field}_uri`.

## Output (`src/bioq/output.py`)

`emit`: `--output json` prints JSON (machine; parse with `jq`); `pretty` is the human
view. Scripts and LLM agents always use `json`.