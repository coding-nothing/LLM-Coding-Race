# tests/mocks — Mock 边界与策略

本仓库测试策略对应 `references/test-plan-llm-coding-harness.md` §测试策略。
本文件是开发期的硬约束，**测试代码不得违反**。

## 各层级 Mock 策略

| 测试层级       | Mock 策略                | 说明                                                                                                       |
| -------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------- |
| 单元（unit）   | 完全 Mock 外部依赖       | LLM SDK 客户端层（`anthropic.Anthropic` / `openai.OpenAI`）必须 patch；禁止真实网络请求                    |
| 集成（integration） | Mock LLM，git/文件系统真实 | LLM 调用仍 patch SDK 客户端；git 命令走真实 `subprocess`，作用于 `tests/fixtures/` 下的临时仓库            |
| E2E            | Mock LLM，业务全链路真实 | 仅 LLM 调用 patch；fetch→run→grade→report 全流程文件落盘                                                   |
| Smoke          | 真实 API                 | 不在默认 pytest 套件；显式 `pytest tests/smoke -m smoke` 才跑                                              |

> 禁止在单元/集成/E2E 测试中触发真实 LLM HTTP 请求，所有外部模型必须通过 SDK 客户端 mock 隔离。

## Mock 点位

### LLM 调用

- **Anthropic**：`mocker.patch("harness.runner.anthropic.Anthropic")` 返回的实例
  需提供 `.messages.create(...)` → 假 Message 对象（含 `content[0].text`、`usage.input_tokens` 等）
- **OpenAI 兼容**：`mocker.patch("harness.runner.openai.OpenAI")` 返回的实例
  需提供 `.chat.completions.create(...)` → 假 ChatCompletion 对象
- **taskprep.llm**：`mocker.patch("taskprep.llm._get_client")` 返回 stub

> 所有 mock 仅作用于 SDK 客户端构造，**不要**直接 patch `call_model` 本身——
> 这会让 retry / cache_control / extra_body 等关键路径跳过测试。

### git 子进程

- 不 Mock。所有 `subprocess.run(["git", ...])` 调用都跑真实 git，
  作用于 `tests/fixtures/` 下由 `make_repo` fixture 程序化创建的最小仓库。

### 文件系统

- 不 Mock。使用 pytest 的 `tmp_path` / `tmp_path_factory`。

### 时间 / 重试退避

- `time.sleep` 在重试退避路径下需要 `monkeypatch.setattr("time.sleep", lambda s: None)`，
  避免单元测试因等待 2/4/8 秒变慢。

## Mock 响应物料

供测试复用的固定 LLM 响应文本放在 `tests/fixtures/llm_responses/`：

- `valid_diff.txt` — 合法 unified diff in ` ```diff ` 块
- `valid_files.txt` — `## File: src/a.py` + 围栏代码块
- `anonymous_blocks.txt` — N 个匿名代码块
- `garbage.txt` — 纯散文
- `malformed_diff.txt` — 声称是 diff 但格式破损

加载方式（在 `conftest.py` 提供 helper）：

```python
@pytest.fixture
def llm_response(fixtures_dir: Path):
    def _load(name: str) -> str:
        return (fixtures_dir / "llm_responses" / name).read_text(encoding="utf-8")
    return _load
```

## 反模式（不要做）

- ❌ 直接 patch `harness.runner.call_model` —— 跳过了被测逻辑
- ❌ 在单元测试里启动真实子进程跑 git —— 应放在 integration 层
- ❌ 用 `responses` / `httpretty` 等 HTTP 层 mock —— SDK 层 mock 更稳
- ❌ 让 mock 直接抛 `Exception` 而不带具体类型 —— 重试逻辑要测特定异常
