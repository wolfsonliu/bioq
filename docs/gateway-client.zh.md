# GatewayClient 与认证

[English](gateway-client.md) | 中文

> **来源（为何存在）：** 派生自 `bioq/client.py`、`auth.py`、`oidc.py`、
> `config.py`、`tokens.py`——这些文件是唯一权威来源，请与本文档对照阅读。
> **何时需要读：** 触及网络、状态码处理、认证/登录、OIDC、配置优先级或 token 缓存时。
> **何时可删除/重写：** 当 `/v1` 端点、状态码映射或认证模式变化时；
> 任何此类改动都要同步 `skills/bioq/SKILL.md`。

## GatewayClient（`bioq/client.py`）

对网关 `/v1/*` 的最薄 httpx 封装；把 HTTP 状态码映射为 `CLIError` 子类。

| 方法 | HTTP 调用 | 返回 / 说明 |
|---|---|---|
| `list_services()` | `GET /v1/services` | `resp["services"]` |
| `describe(svc)` | `GET /v1/services/{svc}` | manifest + openapi 载荷 |
| `prepare_upload(job_id, filename, sha256)` | `POST /v1/uploads/prepare` | 上传目标（presigned 或网关相对 URL） |
| `put_file(url, content)` | `PUT`（经会话） | 仅 file 存储后端；带 auth |
| `run(svc, endpoint, job_id, body)` | `POST /v1/run/{svc}/{endpoint}` | JSON body + 头 `X-Bioagent-Job-Id` |
| `get_job(job_id)` | `GET /v1/jobs/{id}` | 任务状态 |
| `cancel(job_id)` | `POST /v1/jobs/{id}/cancel` | best-effort 取消 |
| `download(job_id, dest)` | `GET /v1/jobs/{id}/download` | 流式写文件 |

### 状态码映射（`_raise_for_status`）

`401/403 → AuthError`、`404 → NotFoundError`、`409 → ConflictError`、其余 ≥400 →
`GatewayError`。

### `_BioqAuth`（httpx.Auth）

**每个**请求都调用 `resolve_bearer` 挂 `Authorization: Bearer`。若响应为 401 且
`auth_mode == "oidc"`，则调用 `tokens.mark_expired` + 刷新并重试一次——容忍时钟偏差
与服务端撤销 token。

## 认证模式（`resolve_bearer`，`bioq/auth.py`）

JWT-only，三种模式。`resolve_bearer` 仅在 `none` 模式下返回 `None`。

| 模式 | 行为 |
|---|---|
| `oidc` | 用缓存的 device-flow token，过期则刷新（`expires_at` 已留 30s 安全余量）。未登录 → `AuthError("run \`bioq login --oidc\`")`。 |
| `client_credentials` | 每次请求现换 token（机器/CI；需 issuer + client_id + secret）。 |
| `none` | 不发 Authorization 头 → 依赖网关 VPC bypass（localhost / 内网）。 |

### OIDC 原语（`bioq/oidc.py`）

- `discover` → `/.well-known/openid-configuration`。
- `start_device` → scope `"openid profile offline_access"`。**不要加 `groups`
  scope**——Keycloak 会以 `invalid_scope` 拒绝；`groups` 是 client protocol mapper
  追加的 claim，而不是可请求的 scope。*（原因：已在真实 Keycloak 上验证；
  仅当 IdP 真的接受 groups scope 时才可删除。）*
- `poll_token` → 处理 `authorization_pending` / `slow_down`。
- `client_credentials` → scope `"openid"`。
- `refresh` → `grant_type=refresh_token`。

## 配置（`bioq/config.py`）与 token（`bioq/tokens.py`）

- 配置文件：`~/.config/bioq/config.toml`（`XDG_CONFIG_HOME` 感知），写入 `0600`。
- `Config` 字段：`gateway_url`、`profile`、`auth_mode`（`none|oidc|client_credentials`）、
  `oidc_issuer`、`oidc_client_id`、`oidc_client_secret`、`state_dir`、`tokens_dir`。
- 优先级：`gateway_url` = flag > `BIOQ_GATEWAY_URL` env > profile 文件；
  `oidc_client_secret` = `BIOQ_OIDC_CLIENT_SECRET` env > profile 文件（CI 友好）。
- 模块级 `_current_config` 让 `jobs.py` / `tokens.py` 无需穿透传参即可读取
  `state_dir` / `tokens_dir`。
- token：device-flow 的 access/refresh token **单独**缓存在
  `~/.config/bioq/tokens/<profile>.json`（`0600`）——config 存持久设置，token 缓存存易变凭据。