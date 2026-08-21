# Testing

English | [中文](testing.zh.md)

> **Why (source):** Test layout and gating live in `tests/`; markers live in
> `pyproject.toml`. Verified against `README.md`'s commands.
> **Read when:** running, writing, or debugging tests.
> **Remove/rewrite when:** the pytest markers or the test-file inventory change.

## Commands

```bash
uv run python -m pytest -q                         # offline unit tests (default)
# contract smoke (needs a reachable gateway; gated by BIOQ_E2E_GATEWAY_URL):
BIOQ_E2E_GATEWAY_URL=https://<gateway> \
    uv run python -m pytest tests/test_contract.py -v
# full live e2e (submits real jobs; opt-in):
RUN_FC_TESTS=1 BIOQ_GATEWAY_URL=https://<gateway> \
    uv run python -m pytest -m fc -v
```

## Layers (all under `tests/`)

- **Offline unit tests:** `test_main` (argparse/dispatch), `test_client` (status
  mapping + retry), `test_commands` (runner logic), and
  `test_config` / `test_tokens` / `test_auth` / `test_oidc` / `test_params` /
  `test_upload` / `test_jobs` / `test_output` / `test_errors`.
- **Contract smoke:** `test_contract.py`, gated by `BIOQ_E2E_GATEWAY_URL`, guards
  against silent `/v1` contract drift between this repo and the gateway.
- **Packaging guard:** `test_packaging.py` asserts the console script + wheel
  packages are registered.
- **Live e2e:** `test_fc.py` hits a real gateway (`@pytest.mark.fc`; see the file's
  docstring/skipif for the exact gating).

## Config (`pyproject.toml`)

- ruff: `line-length=100`, `target-version=py310`.
- pytest markers: `fc` (live end-to-end tests against a deployed gateway, opt-in).

## Lint

```bash
uv run ruff check .   # lint (line-length=100, target-version=py310)
```

## Running subsets

```bash
uv run python -m pytest tests/test_client.py -q   # a single file
uv run python -m pytest -m 'not fc' -q                # everything except live e2e
```

Live `fc` tests are gated by env-driven `skipif` guards and selected with `-m fc`; the
plain `-q` run skips them.

## See also

- `tests/` — the test sources themselves (skipif/docstring gating lives there).
- `docs/exit-codes.md` — codes the tests assert against.