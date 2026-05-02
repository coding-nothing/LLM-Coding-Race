"""TC-29 ~ TC-30：harness/runner.py 的 run_all 集成行为（幂等 + run JSON schema）。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.conftest import (
    SampleTask,
    make_anthropic_message,
    make_openai_completion,
)


# ──────────────────────────────────────────────
# TC-29：outputs/<m>/<t>/run_0.json 已存在 → SDK 不被调用
# ──────────────────────────────────────────────
def test_tc29_run_all_skips_existing_output(
    sample_task: SampleTask,
    tmp_path: Path,
    mock_openai: MagicMock,
) -> None:
    from harness.config import ModelConfig
    from harness.runner import run_all

    cfg = ModelConfig(
        name="deepseek-test", provider="openai_compat", model_id="dx",
        base_url="https://api.example.com",
        api_key_env="DEEPSEEK_API_KEY",
        extra_params={}, supports_prompt_cache=False,
    )

    output_dir = tmp_path / "outputs"
    target = output_dir / "deepseek-test" / "sample-fix"
    target.mkdir(parents=True)
    # 预先放一个 run_0.json 占位
    (target / "run_0.json").write_text(
        json.dumps({"sentinel": "preexisting"}), encoding="utf-8"
    )

    tasks_dir = sample_task.task_dir.parent  # tasks/

    run_all(
        tasks_dir=tasks_dir,
        repo_paths={"sample-fix": sample_task.repo.path},
        output_dir=output_dir,
        models=[cfg],
        runs=1,
    )

    assert mock_openai.chat.completions.create.call_count == 0
    # 占位文件未被覆盖
    payload = json.loads((target / "run_0.json").read_text(encoding="utf-8"))
    assert payload == {"sentinel": "preexisting"}


# ──────────────────────────────────────────────
# TC-30：run_all 写入的 run_0.json 含 PRD §B3.3 全部字段
# ──────────────────────────────────────────────
def test_tc30_run_all_writes_full_schema(
    sample_task: SampleTask,
    tmp_path: Path,
    mock_openai: MagicMock,
) -> None:
    from harness.config import ModelConfig
    from harness.runner import run_all

    cfg = ModelConfig(
        name="deepseek-test", provider="openai_compat", model_id="dx",
        base_url="https://api.example.com",
        api_key_env="DEEPSEEK_API_KEY",
        extra_params={}, supports_prompt_cache=False,
    )
    raw = (
        "Here's the fix:\n\n"
        "```diff\n"
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a - b  # bug\n"
        "+    return a + b\n"
        "```\n"
    )
    mock_openai.chat.completions.create.return_value = make_openai_completion(
        raw, prompt_tokens=200, completion_tokens=80
    )

    output_dir = tmp_path / "outputs"
    tasks_dir = sample_task.task_dir.parent

    run_all(
        tasks_dir=tasks_dir,
        repo_paths={"sample-fix": sample_task.repo.path},
        output_dir=output_dir,
        models=[cfg],
        runs=1,
    )

    out = output_dir / "deepseek-test" / "sample-fix" / "run_0.json"
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))

    required = {
        "model", "task", "run_index",
        "timestamp_iso", "prompt_input_chars", "prompt_input_tokens_estimated",
        "raw_response", "extracted_diff", "output_format", "raw_blocks_count",
        "usage", "latency_seconds", "error",
    }
    missing = required - data.keys()
    assert not missing, f"run_<n>.json 缺少字段：{missing}"

    assert data["model"] == "deepseek-test"
    assert data["task"] == "sample-fix"
    assert data["run_index"] == 0
    assert data["output_format"] == "diff"
    assert "diff" in data["extracted_diff"] or "+++ b/src/a.py" in data["extracted_diff"]
    assert data["error"] is None
    assert "input_tokens" in data["usage"]
