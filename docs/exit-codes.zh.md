# 退出码

[English](exit-codes.md) | 中文

> **来源（为何存在）：** 定义于 `bioq/errors.py`——该文件是权威来源。脚本与 skill
> 都按这些编号分支，因此它们是**稳定契约**。
> **何时需要读：** 新增或改变任何错误路径，或决定新失败类型映射到哪个码时。
> **何时可删除/重写：** 基本不会。重新编号需要协调下游迁移；否则此表永久有效。

## 表

| 码 | 含义 | 异常类 |
|---|---|---|
| 0 | 成功 | — |
| 2 | 用法错误（参数错误） | `UsageError` |
| 3 | 鉴权失败 401/403 | `AuthError` |
| 4 | 未找到 404（未知服务或任务） | `NotFoundError` |
| 5 | 任务失败（终态 failed/cancelled） | `JobFailedError` |
| 6 | 完成但无 results.zip | `NoOutputError` |
| 7 | 网关 / 派发错误（5xx / 502，或 `run`/`submit` 之外的 409） | `GatewayError` / `ConflictError` |
| 130 | Ctrl-C（`KeyboardInterrupt`） | — |

## 映射规则

- `main()` **先于** `CLIError` 捕获 `ConflictError`。**仅**对 `run` 与 `submit`，
  409 表示 job_id 已存在 = 幂等，按“已提交”处理并返回 `EXIT_OK`（0）（用
  `bioq status <job_id>` 继续）。对于其他任何命令，409 都是普通网关错误 →
  `EXIT_GATEWAY`（7）。虽然 `ConflictError.exit_code` 是 `EXIT_GATEWAY`，但它只通过
  `main()` 里这段针对 `run`/`submit` 的提前处理才被特殊对待，而不是作为普通失败。
- Ctrl-C **不会**取消远端任务；用 `bioq status <job_id>` 重连。

## 新增失败类型

复用已有的码/类；**不要**重新编号。若确有全新类型，在 `bioq/errors.py` 里新增
带新 `EXIT_*` 常量的 `CLIError` 子类，然后更新本表与 `skills/bioq/SKILL.md`。

## 失败如何呈现

- 普通结果写到 **stdout**；错误写到 **stderr**，形如 `error: <message>`（见
  `bioq/main.py`）。脚本必须按退出码分支，而不是解析 stderr 文本。
- **5 与 6 的区别：** `5` 表示网关报告了终态失败；`6` 表示网关说 `completed`
  但没有产出 `results.zip`（FC 状态遮蔽——见 `docs/commands.md`）。

## 常量

优先使用这些命名常量而非字面整数：`EXIT_OK`、`EXIT_USAGE`、`EXIT_AUTH`、
`EXIT_NOT_FOUND`、`EXIT_JOB_FAILED`、`EXIT_NO_OUTPUT`、`EXIT_GATEWAY`、
`EXIT_INTERRUPT`（对应上表）。

## 另见

- `bioq/errors.py` —— 权威定义。
- `docs/commands.md` —— `5` 与 `6` 的抛出位置。
- `skills/bioq/SKILL.md` —— 使用方 agent 应对各码采取什么动作。