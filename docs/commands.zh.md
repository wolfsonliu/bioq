# 命令与输入构造

[English](commands.md) | 中文

> **来源（为何存在）：** 派生自 `bioq/commands.py`、`upload.py`、`params.py`、
> `jobs.py`、`output.py`，并对 `bioq/main.py` 校验。描述面向用户的 CLI 行为。
> **何时需要读：** 改动 CLI 行为、新增/重命名子命令或 flag，或改变上传/参数语义时。
> **何时可删除/重写：** 当命令或 flag 变化时——同时同步 `skills/bioq/SKILL.md`
> 与 `README.md` 的命令表。

## 命令速查

| 命令 | 作用 |
|---|---|
| `bioq services` | 列出服务（短名，去掉 `-server`） |
| `bioq describe <svc> [<endpoint>]` | 端点 / `--file` / `--set` 参数（默认人读视图） |
| `bioq run <svc> <endpoint> [...] [--wait -o <dir>]` | 上传 + 提交 +（带 `--wait`）轮询 + 下载解压 |
| `bioq submit <svc> <endpoint> [...]` | 只提交；打印 `job_id` |
| `bioq status <job_id> [--timeout <s>]` | 查询状态（给定超时则轮询到终态） |
| `bioq download <job_id> -o <dir>` | 下载并解压结果 zip |
| `bioq cancel <job_id>` | best-effort 取消 |
| `bioq recent [--limit N]` | 列出本地作业历史（submit/status 事件） |
| `bioq login` / `logout` / `config` | 本地凭据管理（不连网关） |

## 服务名

`_canonical_svc(name)` 接受短名（`proteinmpnn`）或规范注册名（`proteinmpnn-server`）；
缺 `-server` 时补齐。网关及其文档用规范名；用户打 `bioq services` 展示的短名。
补/去后缀的逻辑**只**放在 `commands._canonical_svc`——不要重复实现。

## describe

- 默认（pretty）视图：取 `manifest` 中的 `/api/tasks/<name>` 端点，把
  `request_fields` 分成 **files**（`is_file`）与 **params**（非文件、排除每个文件的
  `<field>_uri` companion），渲染 `--file` / `--set` 参数表 + 一行可复制的
  `bioq run ...` 示例。`--output json` 返回原始 manifest+openapi 载荷。
- `--wait [--timeout <s>]`（仅 pretty）：若 manifest 里没有可运行的 `/api/tasks/*`
  端点（服务仍在冷启动），每 `DESCRIBE_WAIT_INTERVAL_S`（2s）重拉
  `/v1/services/{svc}`，直到端点出现或超时。超时 = `--timeout` >
  `BIOQ_DESCRIBE_TIMEOUT` env > `DESCRIBE_WAIT_TIMEOUT_S`（120s）。`--output json`
  忽略 `--wait`（单次、忠实抓取）；端点列表为空时打印可操作的冷启动提示并以 0 退出。
- `<endpoint>` 可含斜杠（嵌套）：`bioq run rfdiffusion generate/motif`。

## run / submit

`_build_and_submit`：canonicalize svc → `uuid.uuid4().hex[:20]` job_id → `upload_files`
→ `build_body` → `client.run` → `record_submit`（本地历史）。到终态后，
`cmd_run`/`cmd_status`/`cmd_download` 会向同一份 `jobs.jsonl` 追加一条 `record_status`
事件。`bioq recent`（离线）读回这些记录（它读取默认的 `XDG_STATE_HOME`/
`~/.local/state` 文件，**不会**使用 profile 自定义的 `state_dir`）。

- `cmd_run --wait`：轮询到终态 → 非 `completed` 抛 `JobFailedError`（exit 5）→
  否则下载解压；**空 `results.zip` 抛 `NoOutputError`（exit 6）**。
- **`status=completed` ≠ 有产物。** FC 异步会把返回 500 的容器也标成 "Succeeded"。
  `--wait`/`download` 因此会下载**并校验** zip；空则 exit 6。
  *（原因：防 FC 状态遮蔽；仅当网关保证 `completed` 必有产物时才可删除。）*
- `_extract_download`：下载到 `<out>/<job_id>.zip`；`namelist()` 为空 →
  `NoOutputError`；否则 `extractall` 到 out 目录。
- `_poll_timeout`：`--timeout` > `BIOQ_POLL_TIMEOUT` env > 默认 `21600s`（6h）。
- `cmd_status`：默认单次查询；仅当给了 `--timeout`（或 `BIOQ_POLL_TIMEOUT`）且任务
  尚未终态时才轮询。
- 常量：`POLL_INTERVAL_S = 10.0`；`TERMINAL = {"completed","failed","cancelled"}`。

## 上传（`bioq/upload.py`）

`--file <field>=<path>`：sha256 → `prepare_upload(job_id, filename, sha256)` → 缓存命中
（`exists`）免传 → 否则 PUT 字节 → 收集 `pre["uri"]`。

- OSS presigned 绝对 URL → 裸 `httpx.put`（不带网关 auth）。
- 网关相对 URL（`/v1/files/<key>`）→ `client.put_file`，会接 `base_url` **并**带 auth。
- 同一 `field` 重复 → 折叠成 list；body 键是 `{field}_uri`，且 `<field>` 必须匹配
  下游服务的 `<field>_uri` 表单字段。

## 参数（`bioq/params.py`）

`build_body`：`--set k=v` 做轻量类型推断（`true/false`→bool、可转 int→int、
可转 float→float、否则 str）；`--set-json k=<json>|@file.json` 执行 `json.loads`
（`@` 前缀读文件）；最后 `body.update(file_uris)` 用 `{field}_uri` 覆盖。

## 输出（`bioq/output.py`）

`emit`：`--output json` 打印 JSON（机读；用 `jq` 解析）；`pretty` 是人读视图。
脚本与 LLM agent 一律用 `json`。