# 架构

[English](architecture.md) | 中文

> **来源（为何存在）：** 这些事实直接读自 `bioq/*.py`（主要是 `bioq/main.py`）。
> 把它们记在这里，是为了改动时不必先读完所有模块——只需读你真正触及的模块。
> **何时需要读：** 在本仓库做第一次代码改动前，用来熟悉目录结构与运行数据流。
> **何时可删除/重写：** 当模块被重命名/新增/删除，或 `main.main()` 的流程变化时；
> 需与 `bioq/main.py` 保持同步。

## 目录结构

```
bioq/                   （thin，单层包）
├── main.py             argparse（build_parser）+ 命令分发 + 退出码映射
├── client.py           GatewayClient（对 /v1 的 httpx 封装）+ _BioqAuth
├── commands.py         各 cmd_* 处理器 + 提交/轮询/下载逻辑
├── config.py           profile 配置（~/.config/bioq/config.toml，0600）+ load_config 优先级
├── auth.py             resolve_bearer（oidc / client_credentials / none 三种模式）
├── oidc.py             OAuth2 原语：discover / device flow / client-credentials / refresh
├── tokens.py           OIDC token 缓存（~/.config/bioq/tokens/<profile>.json，0600）
├── jobs.py             轮询循环（容忍瞬时错误）+ 本地 recent-job 注册表
├── params.py           build_body（--set / --set-json / 文件 uri）
├── upload.py           --file → sha256 → prepare_upload → PUT → {field}_uri
├── errors.py           退出码 taxonomy + CLIError 异常层级
└── output.py           emit（pretty 人读 / json 机读）
bioq/tests/             离线单测 + opt-in live/contract 测试
skills/bioq/SKILL.md    中性（agent 无关）skill，教“使用”bioq（而非开发）
examples/               可运行 bash 示例
pyproject.toml          打包（hatchling）+ ruff + pytest marker 配置
```

## 运行流程（`bioq/main.py`）

1. `build_parser()` 组装 argparse。全局 flag（`--gateway-url` / `--profile` /
   `--output`）挂在**同时作用于顶层和每个 subparser 的共享 parent parser**上，
   因此位置随意（`bioq --output json run ...` ≡ `bioq run ... --output json`）。
   用 `default=SUPPRESS` 防止 subparser 副本覆盖已解析的值；`main()` 再回填真正默认值。
2. **no-client 命令**（`login` / `logout` / `config`）不连网关，且**必须**在
   `load_config` 之前执行（login 是创建 config 的）。见 `_NO_CLIENT`。
3. 其余命令：`load_config(profile, gateway_url)` → `GatewayClient.from_url(url, cfg)`
   → 派发到 `_COMMANDS[cmd](client, args)` → 异常映射到退出码。
4. 异常 → 退出码：`ConflictError` **先于** `CLIError` 被捕获；**仅**对 `run`/`submit`
   返回 `EXIT_OK`（job_id 已存在 = 幂等，按“已提交”处理）；任何其他命令的 409 以及
   `CLIError` → `exc.exit_code`（`EXIT_GATEWAY`=7）；`KeyboardInterrupt` →
   `EXIT_INTERRUPT`（130）。

各 handler、client、认证、退出码表的细节放在其余文档中——此处不重复。

## 输入输出契约

普通结果写到 **stdout**；面向用户的错误写到 **stderr**，形如 `error: <message>`
（见 `bioq/main.py`）。脚本按进程退出码分支，而不是解析 stderr 文本
（见 `docs/exit-codes.md`）。

## 相关文档

- `docs/gateway-client.md` —— 上述流程背后的 client、状态码映射与认证。
- `docs/commands.md` —— 每个 `cmd_*` 处理器做什么。
- `docs/exit-codes.md` —— 第 4 步的退出码映射。