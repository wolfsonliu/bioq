# AGENTS.md — bioq

Guidance for agents **developing `bioq` itself**. The agent-neutral skill for
*driving* bioq as a tool (not developing it) is `skills/bioq/SKILL.md` — keep the
two in lockstep (see `docs/conventions.md`). All paths are relative to the repo root.

> Topic docs live in `docs/` as canonical English `*.md` plus Chinese mirrors
> `*.zh.md`. Read them on demand — this entry file is deliberately thin.

---

## Project Overview

`bioq` is a thin CLI client for the bioq-services gateway: one gateway URL + one set
of credentials lets you discover services, upload inputs, submit jobs, poll, and
download/extract results. It speaks only HTTP (`httpx`, Python ≥3.10) and holds **no
FC / OSS / JWT logic** — all platform complexity lives in the gateway. Single console
entrypoint: `bioq` (there is no `python -m bioq`).

## Quick Start

```bash
uv sync --all-extras          # install runtime + dev deps (pytest/ruff) into .venv
uv run python -m pytest -q    # offline unit tests (default)
uv run bioq --help            # sanity-check the CLI
```

Invoke as `uv run bioq ...` or `.venv/bin/bioq`; never `python -m bioq`.

## Hard Constraints

1. **Stay thin** — never add FC / OSS / JWT logic; platform capability belongs in the gateway.
2. **Dependency restraint** — runtime deps are `httpx` only (`tomli` on Python 3.10). No numpy/torch/pandas.
3. **Exit codes are a contract** — scripts branch on them; never renumber, map new failures to existing codes.
4. **`--output json` is the machine interface** — keep it `jq`-stable; `pretty` is the human view.
5. **`describe` mirrors the gateway manifest** — derive the pretty view from `/api/manifest` `/api/tasks/*` + `request_fields`; keep field names aligned.
6. **`-server` short-name logic is single-sourced** — strip/append only in `commands._canonical_svc`.
7. **Credential safety** — never print plaintext secrets, commit `config.toml`/tokens, or echo tokens; write with `0600`.
8. **Annotations** — every module starts with `from __future__ import annotations`.

(Why each rule exists and when it can be removed: `docs/conventions.md`.)

## Topic Docs

| Doc | Covers | Read when |
|---|---|---|
| `docs/architecture.md` | repo layout, run-data flow, module map | before your first code change (orient yourself) |
| `docs/gateway-client.md` | GatewayClient, status→error mapping, auth modes, config & token caches | touching network / auth / config / token code |
| `docs/commands.md` | subcommand behavior, upload & param construction, CLI flags | changing CLI / user-facing behavior |
| `docs/exit-codes.md` | exit-code contract + special cases | adding / changing error handling |
| `docs/testing.md` | test commands + layers | running or adding tests |
| `docs/conventions.md` | modification conventions, skill sync, language, examples | reference for every change |