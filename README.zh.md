# bioq

[English](README.md) | 中文

`bioq` 是 bioq-services 服务网关（gateway）的瘦客户端：一个 URL + 一组凭据
即可发现服务、上传输入、提交任务、轮询、下载结果。**不含任何 FC / OSS / JWT 代码**——平台复杂度全在网关。

运行时依赖只有 `httpx`（Python 3.10 额外需要 `tomli`）；不拉 numpy / torch 等重依赖。

> 服务端 `gateway` 及各算法服务位于 **`bioq-services`** 仓库。

## 安装

```bash
# 仓库内开发（最简）
uv sync
uv run bioq --help                 # 或 source .venv/bin/activate && bioq --help

# 可编辑安装到任意环境
uv pip install -e .                # Python 3.10 加 compat: uv pip install -e '.[compat]'
bioq --help
```

## 认证（首次使用）

鉴权统一走 **OIDC / JWT**，请求带 `Authorization: Bearer <access_token>`。

```bash
# 人类 / agent：OIDC device flow（浏览器登一次，token 缓存 + 过期自动刷新）
bioq --gateway-url https://<gateway> login --oidc \
     --issuer https://<idp>/realms/<realm> --client-id bioq-gateway

# 机器 / CI：client-credentials（无人值守；secret 建议走 env）
bioq --gateway-url https://<gateway> login --client-credentials \
     --issuer https://<idp>/realms/<realm> --client-id <svc> --client-secret <secret>
export BIOQ_OIDC_CLIENT_SECRET=<secret>   # 或存 profile

# 本地 / 内网：无需登录——经网关的 VPC bypass（localhost / *-vpc）直接放行
bioq --gateway-url http://127.0.0.1:9000 services
```

profile 写入 `~/.config/bioq/config.toml`（`0600`，含 `auth_mode`/`oidc_issuer`/`oidc_client_id`）；
device-flow 的 access/refresh token 单独缓存在 `~/.config/bioq/tokens/<profile>.json`（`0600`）。

**凭证优先级**：`gateway_url` = flag > `BIOQ_GATEWAY_URL` env > 配置文件；
`oidc_client_secret` = `BIOQ_OIDC_CLIENT_SECRET` env > 配置文件（CI 友好）。

```bash
bioq config show     # 查看配置（client_secret 打码）
bioq config path     # 打印配置文件路径
bioq logout          # 清除该 profile 的缓存 token
```

多环境用 named profile：配置文件里写多个 `[profiles.<name>]`，用 `--profile <name>` 选择。

## 命令

| 命令 | 作用 |
|------|------|
| `bioq services` | 列出所有服务（短名，去掉 `-server`） |
| `bioq describe <svc> [<endpoint>] [--wait]` | 服务端点 / 参数 / 文件输入字段（`--wait` 容忍 FC 冷启动） |
| `bioq run <svc> <endpoint> [...] --wait -o <dir>` | 上传输入 + 提交 + 轮询 + 下载解压 |
| `bioq submit <svc> <endpoint> [...]` | 只提交，打印 `job_id` |
| `bioq status <job_id>` | 查询任务状态 |
| `bioq download <job_id> -o <dir>` | 下载结果 zip 并解压 |
| `bioq cancel <job_id>` | best-effort 取消 |
| `bioq recent [--limit N]` | 列出本地作业历史（submit/status 事件） |
| `bioq login` / `logout` / `config` | 本地凭证管理（不连网关） |

## 示例

```bash
bioq services
bioq describe proteinmpnn design

# 跑一个真实任务并等结果（proteinmpnn 序列设计）
bioq run proteinmpnn design \
    --file pdb=5L33.pdb \
    --set name=demo --set num_seq_per_target=2 \
    --set model_variant=vanilla --set model_name=v_48_020 \
    --set sampling_temp=0.1 --set seed=37 \
    --wait -o ./out
# → ./out/seqs/demo.fa

# 只提交，稍后再看
JOB=$(bioq --output json submit proteinmpnn design --file pdb=5L33.pdb --set name=demo | jq -r .job_id)
bioq status "$JOB"
bioq download "$JOB" -o ./out
```

## 用法要点

- **`describe` 两种视图**：默认（pretty）是**面向 CLI 用法**的人读视图——每个 endpoint 列出
  `--file` / `--set` 参数（含类型 / 默认值 / 说明）+ 一行可复制的 `bioq run ...` 示例；
  `bioq describe <svc> <endpoint>` 只看某个端点。加 `--output json` 则返回网关原始 manifest+openapi
  （给 LLM / 脚本用）。
- **冷启动 `describe`**：服务（如 `diffdock`）冷启动期间，网关可能返回空端点列表；此时
  `describe` 打印提示而非旧的简短 banner。加 `--wait [--timeout <s>]` 等待端点出现
  （默认超时 120s；`BIOQ_DESCRIBE_TIMEOUT` env 可覆盖）。`--output json` 仍是单次忠实抓取。
- **服务短名**：`bioq services` 显示去掉 `-server` 的名字；`run`/`describe` 两种写法都收
  （`proteinmpnn` 或 `proteinmpnn-server`），CLI 会补 `-server` 再发给网关。
- **嵌套 endpoint**：`<endpoint>` 可含斜杠，如 `bioq run rfdiffusion generate/motif ...`、
  `bioq run genie3 generate/unconditional ...`。
- **`--file <field>=<path>`**：CLI 算 sha256 → presign（命中免传）→ 直传 OSS → 注入 body
  `<field>_uri`。`<field>` 要匹配下游的 `<field>_uri` 表单字段（见 `bioq describe`）；同字段多文件 → list。
- **`--set` / `--set-json`**：`--set k=v` 自动推断 int/float/bool/str；`--set-json k=<json>|@file.json`
  传结构化值（如 `--set-json sequences=@seqs.json`）。
- **全局 flag 位置随意**：`--gateway-url` / `--profile` / `--output` 放在子命令前或后都行
  （`bioq --output json run ...` 与 `bioq run ... --output json` 等价）。
- **`--output pretty|json`**：脚本用 `json`。
- **`--wait` 成功判据**：`status=completed` **不等于有产物**（FC 异步会把返回 500 的容器也标成
  Succeeded）。`--wait` 完成后会下载校验；若无 `results.zip`，报"完成但无产物"（退出码 6），
  不报成功——此时查下游 FC 日志。

## 给 code agent 用（Skill）

本仓库自带一份**中立（agent 无关）的 skill**，教 agent 端到端驱动 `bioq`（安装 →
认证 → `describe` → `run`/`submit`/`status`/`download` → 退出码判读，含
"completed ≠ 有产物"陷阱）。它是**自包含的纯 markdown**，唯一副本放在中立位置：

```
skills/bioq/SKILL.md
```

各家 coding agent 用不同的发现机制，因此**用复制的方式**把这份 skill 装到对应位置即可
（各 agent 只需自己那一份，互不影响）：

| Agent | 装法（在你的项目根或用户目录执行） |
|---|---|
| **Claude Code** | `cp -r skills/bioq ~/.claude/skills/`（用户级）或 `cp -r skills/bioq <项目>/.claude/skills/`（项目级） |
| **opencode** 等支持 Agent Skills 格式的 agent | 把整个 `skills/bioq/` 目录复制到该 agent 的 skills 目录（保留 `SKILL.md` 的 frontmatter） |
| **Codex** | `cat skills/bioq/SKILL.md >> AGENTS.md`，或在 `AGENTS.md` 里加一行指向它 |
| **Gemini CLI** | 同上，追加/指向 `GEMINI.md` |
| **Cursor** | 复制成一条规则：`cp skills/bioq/SKILL.md <项目>/.cursor/rules/bioq.mdc`（或在规则里指向它） |

要点：
- SKILL.md 顶部的 YAML frontmatter（`name` + `description`）是 Agent Skills 格式所需；
  支持该格式的 agent（Claude Code / opencode 等）直接复制目录即可被触发。
- 只认单一指令文件的 agent（Codex `AGENTS.md`、Gemini `GEMINI.md`、Cursor 规则），把
  正文并进去或指向 `skills/bioq/SKILL.md` 即可——内容自包含，无需改动。
- 之后在对话里说"用 bioq 跑一个服务 / 列出可用服务 / 下载任务结果"等即可触发。

> 前提：agent 所在环境里 `bioq` 命令可用（见上文[安装](#安装)）。Skill 的 Step 0
> 也会引导 agent 用 `uv run bioq` 或 `.venv/bin/bioq` 兜底。

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 2 | 用法错误 |
| 3 | 鉴权失败（401/403）——重新 `bioq login`（token 过期/未登录）或检查 IdP 配置 |
| 4 | 未找到（404，未知服务 / 任务） |
| 5 | 任务失败（终态 failed/cancelled） |
| 6 | 完成但无产物（见上文 `--wait` 判据） |
| 7 | 网关 / 派发错误（5xx / 502） |
| 130 | 被 Ctrl-C 中断（不杀远端，可 `bioq status <job_id>` 重连） |

## 测试

```bash
uv run python -m pytest -q               # 离线单测
# 契约冒烟（需可达 gateway）：
BIOQ_E2E_GATEWAY_URL=https://<gateway> \
    uv run python -m pytest bioq/tests/test_contract.py -v
# 完整 live e2e（提交真实任务）：
RUN_FC_TESTS=1 BIOQ_GATEWAY_URL=https://<gateway> \
    uv run python -m pytest -m fc -v
```

live / contract 测试通过已登录的 profile（`bioq login`）认证，或对 localhost /
VPC-bypass 网关用 `auth_mode = "none"`。