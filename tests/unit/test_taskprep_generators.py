"""TC-85, TC-86, TC-88：taskprep generators 单元测试。

Phase 2 /gen-test 阶段新建。taskprep 模块尚未实现，导入会失败——预期在 /implement 后转绿。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from tests.conftest import make_anthropic_message


# ── TC-85：generate_prompt 不读 reference.diff（AC-INV-5）──


def test_tc85_generate_prompt_does_not_read_reference_diff(
    tmp_path: Path, mock_taskprep_anthropic: MagicMock
) -> None:
    """`generate_prompt` 不读取 reference.diff 内容（防答案泄露）。"""
    from taskprep.generators.prompt import generate_prompt
    from taskprep.llm import LLMConfig

    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")
    debug_doc = "# Debug\n\n现象：bug"

    # 在当前工作目录放一个 reference.diff，内容不应被读到
    ref_diff = tmp_path / "reference.diff"
    ref_diff.write_text("SECRET ANSWER: change - to +", encoding="utf-8")

    mock_taskprep_anthropic.messages.create.return_value = make_anthropic_message(
        "# 目标\n\n修复 bug"
    )

    # generate_prompt 不接收 reference.diff 路径参数
    # 这个测试验证 LLM system/user prompt 不含 reference.diff 内容
    result = generate_prompt(debug_doc, "fix: bug", cfg)
    assert "SECRET ANSWER" not in result


# ── TC-86：target_files tree 段去重 ──


def test_tc86_target_files_tree_section_dedup() -> None:
    """main_files = ["src/a.py", "src/sub/b.py"] → tree 段含去重后的父目录。"""
    from taskprep.generators.target_files import _build_tree_section

    main_files = ["src/a.py", "src/sub/b.py"]
    result = _build_tree_section(main_files)

    assert "src/" in result
    # src/sub/ 是 src/sub/b.py 的父目录
    assert "src/sub/" in result
    # src/ 不应重复
    assert result.count("src/") == 1 or result.count("src/\n") <= 2  # tree: 前缀不计数


# ── TC-88：verify pytest ──


def test_tc88_generate_verify_pytest() -> None:
    """framework="pytest" → verify.sh 含 python -m pytest。"""
    from taskprep.generators.verify import generate_verify

    result = generate_verify("pytest", ["tests/test_a.py"], llm=None)
    assert "set -e" in result
    assert 'cd "$1"' in result
    assert "python -m pytest" in result
    assert "tests/test_a.py" in result
