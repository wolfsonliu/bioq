---
name: bioq
description: >
  Use the `bioq` CLI to run bioq-services computation services — discover services,
  upload input files, submit jobs, poll status, and download/extract results.
  Use this skill whenever the user wants to run a bioq-services algorithm service
  (proteinmpnn, rfdiffusion, boltz, genie3, dockq, megalodon, iggm, reinvent,
  etc.) through the gateway, list available services, inspect an endpoint's
  parameters, check a job, or fetch results. Trigger on phrases like:
  "跑一个bioq服务", "用bioq", "提交计算任务到网关", "列出bioq可用服务", "看看这个服务怎么调",
  "下载任务结果", "run <service> through the gateway", "submit a job with bioq",
  "what services are available", "describe <service>", "download job results".
  Covers auth setup, the run/submit/status/download lifecycle, --file / --set /
  --set-json inputs, exit-code handling, and the "completed ≠ has output" gotcha.
---

# bioq — bioq computation services CLI

`bioq` is a thin REST client for the bioq service gateway. One gateway URL +
one set of OIDC credentials lets you discover services, upload inputs, submit jobs, poll, and
download results. All platform complexity (FC / OSS / JWT) lives in the gateway —
`bioq` only speaks HTTP and depends on `httpx`.

Repo lives at `repos/bioq/`. This skill teaches an agent to drive it end to end.

## Step 0 — Make `bioq` runnable

The command must be on PATH or invoked from the repo venv. Check, in order:

```bash
bioq --help                                  # already installed?
# else, from the bioq repo:
cd repos/bioq && uv sync && uv run bioq --help
# or invoke the venv binary directly (no activation):
repos/bioq/.venv/bin/bioq --help
# or editable-install into the active env (py3.10 add: '.[compat]'):
uv pip install -e repos/bioq
```

Prefer `uv run bioq ...` (from `repos/bioq/`) or the absolute `.venv/bin/bioq`
path if the bare `bioq` is not found. In this project the repo `.venv` already
has `bioq` installed → `repos/bioq/.venv/bin/bioq` works.

## Step 1 — Authenticate (once per machine)

Auth is JWT/OIDC: each request carries `Authorization: Bearer <access_token>`. Three
`auth_mode`s: `oidc` (device flow — humans/agents), `client_credentials` (machine/CI),
`none` (VPC bypass for local/internal).

```bash
# human / agent — OIDC device flow (log in once; token cached + auto-refreshed)
bioq --gateway-url https://<gw> login --oidc \
     --issuer https://<idp>/realms/<realm> --client-id bioq-gateway

# machine / CI — client-credentials (unattended; secret via env preferred)
bioq --gateway-url https://<gw> login --client-credentials \
     --issuer https://<idp>/realms/<realm> --client-id <svc> --client-secret <secret>
export BIOQ_OIDC_CLIENT_SECRET=<secret>

# local / internal — no login: the gateway's VPC bypass (localhost / *-vpc) admits you
bioq --gateway-url http://127.0.0.1:9000 services
```

`bioq login` writes a profile to `~/.config/bioq/config.toml` (`0600`: `auth_mode` /
`oidc_issuer` / `oidc_client_id`); device-flow access/refresh tokens cache separately
in `~/.config/bioq/tokens/<profile>.json` (`0600`).

```bash
bioq config show     # view config (client_secret masked)
bioq config path     # ~/.config/bioq/config.toml (mode 0600)
bioq logout          # clear this profile's cached OIDC tokens
```

Credentials resolve as: `gateway_url` = `--gateway-url` flag > `BIOQ_GATEWAY_URL`
env > config file; `oidc_client_secret` = `BIOQ_OIDC_CLIENT_SECRET` env > config
file (CI friendly). Multi-env: write several `[profiles.<name>]` sections and select
with `--profile <name>`.

**Never** print a raw secret, commit `config.toml` or token files, or echo tokens.

## Step 2 — Discover the service + endpoint

```bash
bioq services                                # short names (‑server suffix stripped)
bioq describe proteinmpnn                     # all endpoints: --file/--set args + example
bioq describe proteinmpnn design              # just one endpoint
bioq --output json describe proteinmpnn       # raw manifest+openapi (for scripting/LLM)
bioq describe diffdock --wait --timeout 120   # wait out a cold start (see note below)
```

The default `describe` (pretty) is the **CLI-usage** view: per endpoint it lists
`--file` inputs (required/optional), `--set` params (type / default / one-line
desc), and a copy-paste `bioq run ...` example. Use it to learn exact field names
before running — do not guess.

- Service names: type the **short** form (`proteinmpnn`) or canonical
  (`proteinmpnn-server`); both work.
- Nested endpoints contain a slash: `rfdiffusion generate/motif`,
  `genie3 generate/unconditional`.
- **Cold start**: while a service cold-starts, `describe` may show
  `gateway returned no runnable task endpoints` (the gateway's endpoint list is
  empty until the FC exposes `/openapi.json`). Add `--wait [--timeout <s>]` to
  refetch every 2s until endpoints appear (default timeout 120s,
  `BIOQ_DESCRIBE_TIMEOUT` env overrides). `--output json` ignores `--wait`; it stays
  a single faithful fetch.

## Step 3 — Run a job

```bash
bioq run proteinmpnn design \
    --file pdb=5L33.pdb \
    --set name=demo --set num_seq_per_target=2 \
    --set model_variant=vanilla --set sampling_temp=0.1 --set seed=37 \
    --wait -o ./out
# → uploads pdb, submits, polls to terminal, downloads+extracts to ./out/
```

Input flags:
- `--file <field>=<path>` — CLI computes sha256 → prepare upload (skips upload on
  cache hit) → uploads the bytes → injects body `<field>_uri`. `<field>` must match the
  downstream `<field>` shown by `describe` (its `_uri` companion). Repeat the
  same `<field>` for a list of files.
- `--set k=v` — scalar; auto-infers `int`/`float`/`bool`, else string.
- `--set-json k=<json>` or `--set-json k=@file.json` — structured values
  (e.g. `--set-json sequences=@seqs.json`).

Global flags (`--gateway-url` / `--profile` / `--output`) may go before **or**
after the subcommand — `bioq --output json run ...` == `bioq run ... --output json`.

### Submit now, collect later

```bash
JOB=$(bioq --output json submit proteinmpnn design --file pdb=5L33.pdb --set name=demo | jq -r .job_id)
bioq status "$JOB"
bioq download "$JOB" -o ./out                 # downloads results.zip → extracts
bioq cancel "$JOB"                            # best-effort
```

Scripting: always pass `--output json` and parse with `jq`.

Forgot a `job_id`? `bioq recent` lists your local submit/status history.

## Step 4 — Interpret the result (critical)

`status=completed` does **not** guarantee output — FC async marks a container
that returned 500 as "Succeeded". `bioq run --wait` (and `download`) therefore
download and validate: an empty `results.zip` → **exit 6 "completed but no
output"**, not success. On exit 6, the downstream job actually failed at
setup/runtime → tell the user to check the gateway / FC logs; do not report
success.

## Exit codes — branch on these

| code | meaning | agent action |
|------|---------|--------------|
| 0 | success | proceed |
| 2 | usage error | fix the command / field names (re-check `describe`) |
| 3 | auth failed (401/403) | check `bioq config show`; re-`login` |
| 4 | not found (404) | unknown service/job — check `bioq services` / job_id |
| 5 | job failed (terminal failed/cancelled) | inspect inputs; surface failure |
| 6 | completed but no output | downstream failed — check gateway/FC logs |
| 7 | gateway/dispatch error (5xx/502) | transient/infra — retry or escalate |
| 130 | Ctrl-C | remote keeps running; reconnect with `bioq status <job_id>` |

## Command reference

| command | purpose |
|---------|---------|
| `bioq services` | list services (short names) |
| `bioq describe <svc> [<endpoint>] [--wait]` | endpoints, params, file-input fields (`--wait` tolerates cold starts) |
| `bioq run <svc> <endpoint> [...] --wait -o <dir>` | upload + submit + poll + download |
| `bioq submit <svc> <endpoint> [...]` | submit only; prints `job_id` |
| `bioq status <job_id>` | query job status |
| `bioq download <job_id> -o <dir>` | download + extract results zip |
| `bioq cancel <job_id>` | best-effort cancel |
| `bioq recent [--limit N]` | list local job history (submit/status events) |
| `bioq login` / `logout` / `config` | local credential management (offline) |

## Installing this skill elsewhere

This skill is agent-neutral. Its single copy lives at `skills/bioq/SKILL.md` (not
under any `.claude/` path). Install it by **copying** into whatever location your
agent discovers — one copy per agent, no symlinks required:

```bash
# Claude Code (and other Agent-Skills-format agents): copy the whole folder
cp -r skills/bioq ~/.claude/skills/                 # user-wide
cp -r skills/bioq <other-project>/.claude/skills/   # per-project

# Single-instruction-file agents: append/point the body into their file
cat skills/bioq/SKILL.md >> AGENTS.md               # Codex / opencode
cat skills/bioq/SKILL.md >> GEMINI.md               # Gemini CLI
cp skills/bioq/SKILL.md <project>/.cursor/rules/bioq.mdc   # Cursor
```

The YAML frontmatter (`name` + `description`) is what Agent-Skills-format agents
use to trigger it. For agents that read a single instruction file, the body is
plain markdown and self-contained — copy it in or reference this file.
