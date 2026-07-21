# bioq CLI

`bioq` 是 [gateway-server](../services/gateway-server/) 的瘦客户端：一个 URL + 一个 API Key
即可发现服务、上传输入、提交任务、轮询、下载结果。**不含任何 FC / OSS / JWT 代码**——平台复杂度全在网关。

运行时依赖只有 `httpx`（+ Python 3.10 需要 `tomli`）；不拉 numpy / torch 等重依赖。

## 安装

```bash
# 仓库内开发（最简）
uv sync
uv run bioq --help                 # 或 source .venv/bin/activate && bioq --help

# 可编辑安装到任意环境
uv pip install -e '.[cli]'         # 或 pip install -e '.[cli]'
bioq --help
```

## 认证（首次使用）

```bash
# 交互式：提示 Gateway URL + 隐藏输入 API key
bioq login

# 非交互（flag）：
bioq --gateway-url https://<gateway> login --api-key <KEY> --key-id <KEY_ID>
```

写入 `~/.config/bioq/config.toml`（权限 `0600`）。`--key-id` 可选，仅作元数据展示——网关按
**api_key（secret）** 鉴权（`X-API-Key`），key_id 不随请求发送。

**凭证优先级**：`gateway_url` = flag > `BIOQ_GATEWAY_URL` env > 配置文件；
`api_key` = `BIOQ_API_KEY` env > 配置文件（env 覆盖 config，CI 友好）。

```bash
bioq config show     # 查看当前配置（api_key 打码，key_id 明文）
bioq config path     # 打印配置文件路径
bioq logout          # 删除该 profile 的 api_key（保留 gateway_url）
```

多环境用 named profile：配置文件里写多个 `[profiles.<name>]`，用 `--profile <name>` 选择。

## 命令

| 命令 | 作用 |
|------|------|
| `bioq services` | 列出所有服务（短名，去掉 `-server`） |
| `bioq describe <svc> [<endpoint>]` | 服务端点 / 参数 / 文件输入字段 |
| `bioq run <svc> <endpoint> [...] --wait -o <dir>` | 上传输入 + 提交 + 轮询 + 下载解压 |
| `bioq submit <svc> <endpoint> [...]` | 只提交，打印 `job_id` |
| `bioq status <job_id>` | 查询任务状态 |
| `bioq download <job_id> -o <dir>` | 下载结果 zip 并解压 |
| `bioq cancel <job_id>` | best-effort 取消 |
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

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 2 | 用法错误 |
| 3 | 鉴权失败（401/403）——检查 `bioq config show` 的 api_key |
| 4 | 未找到（404，未知服务 / 任务） |
| 5 | 任务失败（终态 failed/cancelled） |
| 6 | 完成但无产物（见上文 `--wait` 判据） |
| 7 | 网关 / 派发错误（5xx / 502） |
| 130 | 被 Ctrl-C 中断（不杀远端，可 `bioq status <job_id>` 重连） |

## 相关

- [使用 bioq CLI（指南）](../engineering/guides/using-the-bioq-cli.md) —— 更详细的教程
- [统一服务访问层设计](../engineering/decisions/2026-07-09-unified-service-access-cli.md) —— gateway + CLI 架构（§2 CLI）
- [gateway-server](../services/gateway-server/) —— 服务端
