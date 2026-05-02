# Smoke Tests（真实 API 烟测）

本目录用于跑真实模型 API 的烟测，**不进默认 pytest 套件**（已在 `pyproject.toml` 的 `--ignore=tests/smoke` 中排除）。

## 何时跑

- 升级 `anthropic` / `openai` SDK 版本之后
- 修改 `harness/runner.py` 的 provider 调用逻辑后
- 验证某个真实模型 endpoint 是否可达

## 怎么跑

```bash
# 需要先在 .env 中配齐对应 API key
pytest tests/smoke -m smoke
```

或者手动选中单个文件：

```bash
pytest tests/smoke/test_runner_live.py
```

## 编写规范

- 必须打 `@pytest.mark.smoke`
- 必须在用例开头检查 API key，缺失时 `pytest.skip(...)` 而非失败
- 不写断言到具体输出文本（模型回复不稳定）；只断言 `error is None`、`raw_response` 非空、`usage` 字段存在
- 单次调用的 max_tokens 应控制在 200 以内，避免在烟测里烧钱
