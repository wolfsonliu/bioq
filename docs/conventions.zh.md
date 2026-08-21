# 修改约定

[English](conventions.md) | 中文

> **来源（为何存在）：** 从仓库历史与 `AGENTS.md` 的硬性约束提炼而来。下面每条规则
> 都说明为何存在、何时可删除。
> **何时需要读：** 做任何改动——这是每次编辑/提交的参照。
> **何时可删除/重写：** 当某条规则的底层理由消失时（如某依赖终于被允许、某契约被迁移
> 等）。及时删除过时规则——无用指令只会拖慢系统。

## 架构与依赖

- **保持 thin。** bioq 不含 FC / OSS / JWT 逻辑；平台能力属于网关侧。
  *原因：网关是平台复杂度的唯一拥有者；在这里重复实现会重复且漂移。
  删除条件：bioq 不再是一个瘦网关客户端时。*
- **依赖克制。** 运行时依赖仅 `httpx`（3.10 加 `tomli`）。不要 numpy/torch/pandas。
  *原因：保持 bioq 轻量、随处可导入。删除条件：某个硬性功能确实需要重依赖——
  但先重新评估为网关侧功能。*

## 契约

- **退出码稳定。** 脚本按码分支；绝不重新编号。新失败类型映射到已有码
  （`docs/exit-codes.md`）。*原因：重新编号会破坏所有下游脚本。
  删除条件：在所有消费方之间协调一次主版本破坏性变更。*
- **`--output json` 是机读接口。** 保持可被 `jq` 稳定解析；`pretty` 是人读视图。
  *原因：LLM 与脚本解析 JSON。删除条件：有更新版、带版本的输出契约取而代之。*
- **`describe` 与网关 manifest 对齐。** pretty 视图从 `/api/manifest` 的
  `/api/tasks/*` + `request_fields`（`is_file` / `required` / `type` / `default` /
  `description`）推导；字段名需与网关一致。*原因：describe 是实时 manifest 的镜像；
  漂移会误导调用方。*
- **`-server` 短名逻辑单一来源**于 `commands._canonical_svc`。
  *原因：单一位置避免两条代码路径漂移。*

## 安全与风格

- **凭据安全。** 绝不打印明文 secret、提交 `config.toml` 或 token 文件、或 echo token；
  写文件用 `0600`。*原因：凭据存在用户家目录；泄露是真实事故。*
- **每个模块**用 `from __future__ import annotations`。
  *原因：前向引用的字符串注解在 Python 3.10 也可用。*
- **语言。** 代码、标识符、docstring/注释、commit message 用**英文**。中文仅用于面向
  用户的文档（`README.md`、`skills/bioq/SKILL.md`）与 `docs/` 下的 `.zh.md` 镜像
  （其权威形式是英文 `*.md`）。*原因：与现有代码库一致，保持开发者向文本统一。*
- commit 中**不要**加 `Co-Authored-By` 之类的 AI co-author trailer。
- **`config._current_config` 是有意的环境态访问器。** `load_config` 把解析好的 `Config`
  存为模块全局，使 `get_state_dir`/`get_tokens_dir`（进而 `jobs.history_path`）无需把
  `Config` 穿透进每个函数签名。*原因：bioq 是单次启动的 CLI；每次调用级全局态安全且简单。
  删除条件：bioq 变为长驻或并发——届时改用显式传参或 `contextvars`。*

## Skill 同步

`skills/bioq/SKILL.md` 是教“使用”bioq 的中性（agent 无关）skill——与本开发向
`AGENTS.md` 互补。当改动命令、退出码或认证流程时，**同步更新 `SKILL.md`**（以及
`README.md` 的命令/退出码表）以避免漂移。安装方式是复制到各 agent 的发现位置；正文自包含。

## 示例

`examples/run_dockq_score.sh` 与 `run_dockq_score_batch.sh` 是可运行用法示例
（单结构 vs 批量打分），展示了 `--file`/`--set`/`--wait`/`-o` 与 env 覆盖
（`BIOQ`、`BIOQ_PROFILE`、`OUT`）。可作为集成/文档参考。