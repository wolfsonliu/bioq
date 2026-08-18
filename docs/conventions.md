# Modification Conventions

English | [中文](conventions.zh.md)

> **Why (source):** Distilled from the repo's history and the hard constraints in
> `AGENTS.md`. Each rule below states why it exists and when it can be removed.
> **Read when:** making any change — this is the reference for every edit/commit.
> **Remove/rewrite when:** a rule's underlying reason disappears (a dependency is
> finally allowed, a contract is migrated away, etc.). Delete stale rules promptly —
> unused instructions slow the system down.

## Architecture & deps

- **Stay thin.** bioq holds no FC / OSS / JWT logic; platform capability belongs in
  the gateway. *Why: the gateway is the single owner of platform complexity; adding it
  here duplicates and drifts. Remove-when: bioq is no longer a thin gateway client.*
- **Dependency restraint.** Runtime deps: `httpx` only (`tomli` on Python 3.10). No
  numpy/torch/pandas. *Why: keep bioq lightweight and importable anywhere. Remove-when:
  a hard feature genuinely needs a heavy dep — re-evaluate it as a gateway-side feature
  first.*

## Contracts

- **Exit codes are stable.** Scripts branch on them; never renumber. Map new failures
  to existing codes (`docs/exit-codes.md`). *Why: renumbering breaks every downstream
  script. Remove-when: you coordinate a major-version break across all consumers.*
- **`--output json` is the machine interface.** Keep it `jq`-stable; `pretty` is the
  human view. *Why: LLMs and scripts parse JSON. Remove-when: a newer, versioned output
  contract replaces it.*
- **`describe` aligns with the gateway manifest.** The pretty view derives from
  `/api/manifest` `/api/tasks/*` + `request_fields` (`is_file` / `required` / `type` /
  `default` / `description`); keep field names matching the gateway. *Why: describe is
  a mirror of the live manifest; divergence misleads callers.*
- **`-server` short-name logic is single-sourced** in `commands._canonical_svc`.
  *Why: a single place prevents two code paths drifting.*

## Security & style

- **Credential safety.** Never print plaintext secrets, commit `config.toml` or token
  files, or echo tokens; write with `0600`. *Why: credentials live in user home dirs;
  leaking them is a real incident.*
- **`from __future__ import annotations`** in every module. *Why: forward-ref string
  annotations also work on Python 3.10.*
- **Language.** Code, identifiers, docstrings/comments, and commit messages are
  **English**. Chinese is reserved for user-facing docs (`README.md`,
  `skills/bioq/SKILL.md`) and the `.zh.md` mirrors in `docs/` (whose canonical form is
  the English `*.md`). *Why: matches the existing codebase and keeps developer-facing
  text consistent.*
- **No `Co-Authored-By`-style AI co-author trailers** in commits.

## Skill sync

`skills/bioq/SKILL.md` is the agent-neutral skill for *using* bioq — complementary to
this dev-facing `AGENTS.md`. When you change commands, exit codes, or the auth flow,
**update `SKILL.md` in lockstep** (and `README.md`'s command/exit-code tables) to avoid
drift. Install the skill by copying it into each agent's discovery location; the body
is self-contained.

## Examples

`examples/run_dockq_score.sh` and `run_dockq_score_batch.sh` are runnable usage
samples (single vs batch scoring) showing `--file`/`--set`/`--wait`/`-o` and env
overrides (`BIOQ`, `BIOQ_PROFILE`, `OUT`). Use them as integration/doc reference.