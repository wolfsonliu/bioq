# Architecture

English | [中文](architecture.zh.md)

> **Why (source):** These facts are read directly from `src/bioq/*.py` (primarily
> `src/bioq/main.py`). They are captured here so a change doesn't require reading every
> module first — only the ones you actually touch.
> **Read when:** before your first code change in this repo, to orient in the layout
> and the run-data flow.
> **Remove/rewrite when:** a module is renamed/added/removed, or the flow in
> `main.main()` changes; keep this in sync with `src/bioq/main.py`.

## Layout

```
src/bioq/               package (thin, single layer)
├── main.py             argparse (build_parser) + dispatch + exit-code mapping
├── client.py           GatewayClient (httpx wrapper over /v1) + _BioqAuth
├── commands.py         cmd_* handlers (lifecycle) + shared short-name/timeout primitives
├── describe.py         describe rendering (--file/--set tables + --wait cold-start)
├── authcmds.py         offline login/logout/config commands (no-client)
├── config.py           profiles (~/.config/bioq/config.toml, 0600) + load_config precedence
├── auth.py             resolve_bearer (oidc / client_credentials / none)
├── oidc.py             OAuth2 primitives: discover / device flow / client-credentials / refresh
├── tokens.py           OIDC token cache (~/.config/bioq/tokens/<profile>.json, 0600)
├── jobs.py             poll loop (transient-error tolerant) + local job history (JSONL) + recent
├── params.py           build_body (--set / --set-json / file uris)
├── upload.py           --file → sha256 → prepare_upload → PUT → {field}_uri
├── errors.py           exit-code taxonomy + CLIError hierarchy
└── output.py           emit (pretty human / json machine)
tests/                  offline unit tests + opt-in live/contract tests
skills/bioq/SKILL.md    agent-neutral skill for *using* bioq (not developing it)
examples/               runnable bash samples
pyproject.toml          packaging (hatchling) + ruff + pytest marker config
```

## Run flow (`src/bioq/main.py`)

1. `build_parser()` assembles argparse. Global flags (`--gateway-url` / `--profile` /
   `--output`) live on a **shared parent parser applied to the top level and every
   subparser**, so position doesn't matter (`bioq --output json run ...` ≡
   `bioq run ... --output json`). `default=SUPPRESS` keeps the subparser copy from
   clobbering an already-parsed value; `main()` backfills the real defaults.
2. **No-client commands** (`login` / `logout` / `config` / `recent`) never connect to the
   gateway and must run **before** `load_config` (login creates the config; `recent`
   reads only the local `jobs.jsonl`). See `_NO_CLIENT`.
3. Everything else: `load_config(profile, gateway_url)` → `GatewayClient.from_url(url,
   cfg)` → dispatch to `_COMMANDS[cmd](client, args)` → map exceptions to exit codes.
4. Exception → exit code: `ConflictError` is caught **before** `CLIError`; for **only**
   `run`/`submit` it returns `EXIT_OK` (job_id already exists = idempotent, treated as
   "already submitted"); any other command's 409 and `CLIError` → `exc.exit_code`
   (`EXIT_GATEWAY`=7); `KeyboardInterrupt` → `EXIT_INTERRUPT` (130).

Details of each handler, the client, auth, and the exit-code table live in the sibling
docs — not duplicated here.

## I/O contract

Normal results go to **stdout**; a user-facing error goes to **stderr** as
`error: <message>` (see `src/bioq/main.py`). Scripts branch on the process exit code, not
on stderr text (see `docs/exit-codes.md`).

## Related docs

- `docs/gateway-client.md` — the client, status mapping, and auth behind the above flow.
- `docs/commands.md` — what each `cmd_*` handler does.
- `docs/exit-codes.md` — the exit-code mapping in step 4.