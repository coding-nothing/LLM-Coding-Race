"""TC-84, TC-87：taskprep generators 集成测试。

Phase 2 /gen-test 阶段新建。taskprep 模块尚未实现，导入会失败——预期在 /implement 后转绿。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from tests.conftest import make_anthropic_message


# ── TC-84：prompt 缺失 section → 标 [需要补充] ──


def test_tc84_generate_prompt_missing_section_placeholder(
    tmp_path: Path, mock_taskprep_anthropic: MagicMock
) -> None:
    """mock LLM 返回缺失"复现步骤"段 → 缺失 section 标 `[需要补充]`。"""
    from taskprep.generators.prompt import generate_prompt
    from taskprep.llm import LLMConfig

    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")
    debug_doc = "# Debug\n\n现象：bug"

    # LLM 响应缺少"复现步骤"
    mock_taskprep_anthropic.messages.create.return_value = make_anthropic_message(
        "# 目标\n\n修复 bug\n\n"
        "# 当前行为\n\n错误\n\n"
        "# 错误信息\n\n无\n\n"
        "# 期望行为\n\n正确\n\n"
        "# 验收标准\n\n通过\n\n"
        "# 约束\n\n不变\n"
    )

    result = generate_prompt(debug_doc, "fix: bug", cfg)
    assert "[需要补充]" in result


# ── TC-87：test_patch 第 1 次非法、第 2 次合法 ──


def test_tc87_generate_test_patch_retry_succeeds(
    mock_taskprep_anthropic: MagicMock,
) -> None:
    """mock LLM 第 1 次非法、第 2 次合法 → 输出合法 diff，无 GENERATION_FAILED 标记。"""
    from taskprep.generators.test_patch import generate_test_patch
    from taskprep.llm import LLMConfig

    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")

    valid_diff = (
        "--- a/tests/test_add.py\n"
        "+++ b/tests/test_add.py\n"
        "@@ -0,0 +1,4 @@\n"
        "+from src.a import add\n"
        "+\n"
        "+def test_add():\n"
        "+    assert add(1, 2) == 3\n"
    )
    mock_taskprep_anthropic.messages.create.side_effect = [
        make_anthropic_message("not a diff, just prose"),
        make_anthropic_message(valid_diff),
    ]

    result = generate_test_patch(
        debug_doc="bug: add returns a-b",
        reference_diff="diff --git a/src/a.py ...",
        main_files_content={"src/a.py": "def add(a, b):\n    return a - b\n"},
        similar_test_samples=[],
        project_test_framework="pytest",
        llm=cfg,
    )

    assert "[GENERATION_FAILED]" not in result
    assert "--- a/" in result
    assert "+++ b/" in result
    assert mock_taskprep_anthropic.messages.create.call_count == 2
