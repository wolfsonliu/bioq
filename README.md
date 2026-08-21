# bioq

English | [中文](README.zh.md)

`bioq` is a thin client for the bioq-services gateway: one URL + one set of
credentials lets you discover services, upload inputs, submit jobs, poll, and download
results. **No FC / OSS / JWT code** — all platform complexity lives in the gateway.

Runtime deps: `httpx` only (`tomli` on Python 3.10); no numpy / torch / pandas.

> The server-side `gateway` and the algorithm services live in the **`bioq-services`**
> repo.

## Install

```bash
# in-repo development (simplest)
uv sync
uv run bioq --help                 # or: source .venv/bin/activate && bioq --help

# editable install into any environment
uv pip install -e .                # Python 3.10 add compat: uv pip install -e '.[compat]'
bioq --help
```

## Auth (first use)

Auth is **OIDC / JWT**: requests carry `Authorization: Bearer <access_token>`.

```bash
# human / agent: OIDC device flow (log in once; token cached + auto-refreshed)
bioq --gateway-url https://<gateway> login --oidc \
     --issuer https://<idp>/realms/<realm> --client-id bioq-gateway

# machine / CI: client-credentials (unattended; keep the secret in env)
bioq --gateway-url https://<gateway> login --client-credentials \
     --issuer https://<idp>/realms/<realm> --client-id <svc> --client-secret <secret>
export BIOQ_OIDC_CLIENT_SECRET=<secret>   # or store it in the profile

# local / internal: no login — the gateway's VPC bypass (localhost / *-vpc) admits you
bioq --gateway-url http://127.0.0.1:9000 services
```

Profiles are written to `~/.config/bioq/config.toml` (`0600`, with `auth_mode` /
`oidc_issuer` / `oidc_client_id`); device-flow access/refresh tokens are cached
separately in `~/.config/bioq/tokens/<profile>.json` (`0600`).

**Credential precedence**: `gateway_url` = flag > `BIOQ_GATEWAY_URL` env > config file;
`oidc_client_secret` = `BIOQ_OIDC_CLIENT_SECRET` env > config file (CI-friendly).

```bash
bioq config show     # view config (client_secret masked)
bioq config path     # print the config file path
bioq logout          # clear this profile's cached tokens
```

For multiple environments use a named profile: write several `[profiles.<name>]`
sections in the config and select one with `--profile <name>`.

## Commands

| command | purpose |
|------|------|
| `bioq services` | list all services (short names, `-server` stripped) |
| `bioq describe <svc> [<endpoint>] [--wait]` | service endpoints / params / file-input fields (`--wait` tolerates FC cold starts) |
| `bioq run <svc> <endpoint> [...] --wait -o <dir>` | upload inputs + submit + poll + download/extract |
| `bioq submit <svc> <endpoint> [...]` | submit only; prints `job_id` |
| `bioq status <job_id>` | query job status |
| `bioq download <job_id> -o <dir>` | download + extract the results zip |
| `bioq cancel <job_id>` | best-effort cancel |
| `bioq recent [--limit N]` | list local job history (submit/status events) |
| `bioq login` / `logout` / `config` | local credential management (offline) |

## Examples

```bash
bioq services
bioq describe proteinmpnn design

# run a real job and wait (proteinmpnn sequence design)
bioq run proteinmpnn design \
    --file pdb=5L33.pdb \
    --set name=demo --set num_seq_per_target=2 \
    --set model_variant=vanilla --set model_name=v_48_020 \
    --set sampling_temp=0.1 --set seed=37 \
    --wait -o ./out
# → ./out/seqs/demo.fa

# submit now, check later
JOB=$(bioq --output json submit proteinmpnn design --file pdb=5L33.pdb --set name=demo | jq -r .job_id)
bioq status "$JOB"
bioq download "$JOB" -o ./out
```

## Usage notes

- **Two `describe` views**: the default (pretty) is the **CLI-usage** human view — per
  endpoint it lists `--file` / `--set` params (type / default / description) + a
  copy-paste `bioq run ...` line; `bioq describe <svc> <endpoint>` shows a single
  endpoint. `--output json` returns the raw gateway manifest+openapi (for LLM/scripts).
- **Cold-start `describe`**: while a service (e.g. `diffdock`) cold-starts, the gateway
  may return an empty endpoint list; `describe` then prints a hint instead of the old
  terse banner. Add `--wait [--timeout <s>]` to wait for the endpoints to appear
  (default timeout 120s; `BIOQ_DESCRIBE_TIMEOUT` env overrides). `--output json` stays
  a single, faithful fetch.
- **Service short names**: `bioq services` shows names with `-server` stripped;
  `run`/`describe` accept both forms (`proteinmpnn` or `proteinmpnn-server`) and append
  `-server` before calling the gateway.
- **Nested endpoints**: `<endpoint>` may contain a slash, e.g.
  `bioq run rfdiffusion generate/motif ...`, `bioq run genie3 generate/unconditional ...`.
- **`--file <field>=<path>`**: the CLI computes sha256 → presign (skips upload on cache
  hit) → uploads to OSS → injects body `<field>_uri`. `<field>` must match the
  downstream `<field>_uri` form field (see `bioq describe`); repeat the same field for a
  list of files.
- **`--set` / `--set-json`**: `--set k=v` auto-infers int/float/bool/str;
  `--set-json k=<json>|@file.json` passes a structured value (e.g.
  `--set-json sequences=@seqs.json`).
- **Global flags are position-free**: `--gateway-url` / `--profile` / `--output` work
  before or after the subcommand (`bioq --output json run ...` ≡
  `bioq run ... --output json`).
- **`--output pretty|json`**: scripts use `json`.
- **`--wait` success check**: `status=completed` does **not** guarantee output (FC async
  marks a container that returned 500 as Succeeded). `--wait` downloads and validates;
  if there is no `results.zip`, it reports "completed but no output" (exit code 6)
  instead of success — check the downstream FC logs.

## For code agents (Skill)

This repo ships a **neutral (agent-agnostic) skill** that teaches an agent to drive
`bioq` end to end (install → auth → `describe` → `run`/`submit`/`status`/`download` →
exit-code reading, including the "completed ≠ has output" gotcha). It is
**self-contained plain markdown**, with its single copy in a neutral location:

```
skills/bioq/SKILL.md
```

Each coding agent uses a different discovery mechanism, so install the skill by
**copying** it to the right place (each agent needs only its own copy):

| Agent | Install (run in your project root or user dir) |
|---|---|
| **Claude Code** | `cp -r skills/bioq ~/.claude/skills/` (user-level) or `cp -r skills/bioq <project>/.claude/skills/` (project-level) |
| **opencode** and other Agent-Skills-format agents | copy the whole `skills/bioq/` dir into that agent's skills dir (keep the `SKILL.md` frontmatter) |
| **Codex** | `cat skills/bioq/SKILL.md >> AGENTS.md`, or add a line in `AGENTS.md` pointing to it |
| **Gemini CLI** | same — append/point into `GEMINI.md` |
| **Cursor** | copy as a rule: `cp skills/bioq/SKILL.md <project>/.cursor/rules/bioq.mdc` (or point to it) |

Notes:
- The YAML frontmatter (`name` + `description`) at the top of SKILL.md is required by
  the Agent Skills format; agents that support it (Claude Code / opencode, etc.) just
  copy the directory to be triggered.
- Agents that read a single instruction file (Codex `AGENTS.md`, Gemini `GEMINI.md`,
  Cursor rules) merge the body in or point to `skills/bioq/SKILL.md` — the content is
  self-contained and needs no edits.
- Afterwards, saying "run a service with bioq / list available services / download job
  results" in the conversation triggers it.

> Prerequisite: `bioq` must be runnable in the agent's environment (see
> [Install](#install) above). The skill's Step 0 also falls back to `uv run bioq` or
> `.venv/bin/bioq`.

## Exit codes

| code | meaning |
|----|------|
| 0 | success |
| 2 | usage error |
| 3 | auth failed (401/403) — re-run `bioq login` (token expired/not logged in) or check IdP config |
| 4 | not found (404, unknown service / job) |
| 5 | job failed (terminal failed/cancelled) |
| 6 | completed but no output (see `--wait` check above) |
| 7 | gateway / dispatch error (5xx / 502) |
| 130 | interrupted by Ctrl-C (does not kill the remote job; reconnect with `bioq status <job_id>`) |

## Tests

```bash
uv run python -m pytest -q               # offline unit tests
# contract smoke (needs a reachable gateway):
BIOQ_E2E_GATEWAY_URL=https://<gateway> \
    uv run python -m pytest tests/test_contract.py -v
# full live e2e (submits real jobs):
RUN_FC_TESTS=1 BIOQ_GATEWAY_URL=https://<gateway> \
    uv run python -m pytest -m fc -v
```

Live / contract tests authenticate through the logged-in profile (`bioq login`), or
`auth_mode = "none"` for a localhost / VPC-bypass gateway.