# GatewayClient & Auth

English | [中文](gateway-client.zh.md)

> **Why (source):** Derived from `bioq/client.py`, `auth.py`, `oidc.py`, `config.py`,
> and `tokens.py` — those files are the single source of truth; read them alongside
> this doc.
> **Read when:** you touch networking, status-code handling, auth/login, OIDC, config
> precedence, or the token cache.
> **Remove/rewrite when:** a `/v1` endpoint, a status mapping, or an auth mode changes;
> mirror any such change in `skills/bioq/SKILL.md`.

## GatewayClient (`bioq/client.py`)

The thinnest possible httpx wrapper over the gateway `/v1/*`; maps HTTP status →
`CLIError` subclasses.

| method | HTTP call | returns / notes |
|---|---|---|
| `list_services()` | `GET /v1/services` | `resp["services"]` |
| `describe(svc)` | `GET /v1/services/{svc}` | manifest + openapi payload |
| `prepare_upload(job_id, filename, sha256)` | `POST /v1/uploads/prepare` | upload target (presigned or gateway-relative URL) |
| `put_file(url, content)` | `PUT` via session | file-storage backend only; carries auth |
| `run(svc, endpoint, job_id, body)` | `POST /v1/run/{svc}/{endpoint}` | JSON body + header `X-Bioagent-Job-Id` |
| `get_job(job_id)` | `GET /v1/jobs/{id}` | job status |
| `cancel(job_id)` | `POST /v1/jobs/{id}/cancel` | best-effort cancel |
| `download(job_id, dest)` | `GET /v1/jobs/{id}/download` | streams to a file |

### Status mapping (`_raise_for_status`)

`401/403 → AuthError`, `404 → NotFoundError`, `409 → ConflictError`, any other ≥400 →
`GatewayError`.

### `_BioqAuth` (httpx.Auth)

Calls `resolve_bearer` on **every** request to attach `Authorization: Bearer`. If the
response is 401 and `auth_mode == "oidc"`, it calls `tokens.mark_expired` + refresh and
retries once — tolerates clock skew and server-side token revocation.

## Auth modes (`resolve_bearer`, `bioq/auth.py`)

JWT-only, three modes. `resolve_bearer` returns `None` only in `none` mode.

| mode | behavior |
|---|---|
| `oidc` | use the cached device-flow token, refreshing if expired (a 30s safety margin is baked into `expires_at`). Not logged in → `AuthError("run \`bioq login --oidc\`")`. |
| `client_credentials` | mint a fresh token per request (machine/CI; needs issuer + client_id + secret). |
| `none` | no Authorization header → relies on the gateway VPC bypass (localhost / internal). |

### OIDC primitives (`bioq/oidc.py`)

- `discover` → `/.well-known/openid-configuration`.
- `start_device` → scope `"openid profile offline_access"`. **Do NOT add a `groups`
  scope** — Keycloak rejects it with `invalid_scope`; `groups` is a client protocol
  mapper claim, not a requested scope. *(Why: verified against a live Keycloak;
  remove-when the IdP actually accepts a groups scope.)*
- `poll_token` → handles `authorization_pending` / `slow_down`.
- `client_credentials` → scope `"openid"`.
- `refresh` → `grant_type=refresh_token`.

## Config (`bioq/config.py`) & tokens (`bioq/tokens.py`)

- Config file: `~/.config/bioq/config.toml` (`XDG_CONFIG_HOME`-aware), written `0600`.
- `Config` fields: `gateway_url`, `profile`, `auth_mode` (`none|oidc|client_credentials`),
  `oidc_issuer`, `oidc_client_id`, `oidc_client_secret`, `state_dir`, `tokens_dir`.
- Precedence: `gateway_url` = flag > `BIOQ_GATEWAY_URL` env > profile file;
  `oidc_client_secret` = `BIOQ_OIDC_CLIENT_SECRET` env > profile file (CI-friendly).
- Module-level `_current_config` lets `jobs.py` / `tokens.py` read `state_dir` /
  `tokens_dir` without threading the Config object through every signature.
- Tokens: device-flow access/refresh tokens are cached **separately** in
  `~/.config/bioq/tokens/<profile>.json` (`0600`) — config holds durable settings, the
  token cache holds volatile credentials.