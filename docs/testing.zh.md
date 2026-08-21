# 测试

[English](testing.md) | 中文

> **来源（为何存在）：** 测试布局与门控在 `tests/`；marker 在 `pyproject.toml`。
> 已与 `README.md` 的命令核对。
> **何时需要读：** 运行、编写或调试测试时。
> **何时可删除/重写：** pytest marker 或测试文件清单变化时。

## 命令

```bash
uv run python -m pytest -q                         # 离线单测（默认）
# 契约冒烟（需可达网关；由 BIOQ_E2E_GATEWAY_URL 门控）：
BIOQ_E2E_GATEWAY_URL=https://<gateway> \
    uv run python -m pytest tests/test_contract.py -v
# 完整 live e2e（提交真实任务；opt-in）：
RUN_FC_TESTS=1 BIOQ_GATEWAY_URL=https://<gateway> \
    uv run python -m pytest -m fc -v
```

## 分层（均在 `tests/` 下）

- **离线单测：** `test_main`（argparse/分发）、`test_client`（状态码映射 + 重试）、
  `test_commands`（runner 逻辑），以及 `test_config` / `test_tokens` / `test_auth` /
  `test_oidc` / `test_params` / `test_upload` / `test_jobs` / `test_output` /
  `test_errors`。
- **契约冒烟：** `test_contract.py`，由 `BIOQ_E2E_GATEWAY_URL` 门控，防本仓库与网关
  之间的 `/v1` 契约静默漂移。
- **打包守护：** `test_packaging.py` 断言 console script + wheel packages 已注册。
- **live e2e：** `test_fc.py` 打真实网关（`@pytest.mark.fc`；具体门控见该文件
  docstring/skipif）。

## 配置（`pyproject.toml`）

- ruff：`line-length=100`、`target-version=py310`。
- pytest marker：`fc`（对已部署网关的 live 端到端测试，opt-in）。

## Lint

```bash
uv run ruff check .   # lint（line-length=100、target-version=py310）
```

## 运行子集

```bash
uv run python -m pytest tests/test_client.py -q   # 单个文件
uv run python -m pytest -m 'not fc' -q                # 排除 live e2e 的全部测试
```

live `fc` 测试由 env 驱动的 `skipif` 门控，并用 `-m fc` 选中；普通 `-q` 运行会跳过它们。

## 另见

- `tests/` —— 测试源码本身（skipif/docstring 门控在那里）。
- `docs/exit-codes.md` —— 测试所断言的退出码。