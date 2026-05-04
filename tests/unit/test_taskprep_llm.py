"""TC-82 ~ TC-83：taskprep llm 单元测试。

Phase 2 /gen-test 阶段新建。taskprep 模块尚未实现，导入会失败——预期在 /implement 后转绿。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.conftest import make_anthropic_message


# ── TC-82：3 次重试全部失败 → 抛 RuntimeError ──


def test_tc82_llm_call_raises_after_all_retries(
    mock_taskprep_anthropic: MagicMock, fast_sleep: list[float]
) -> None:
    """mock SDK 始终抛错 → `llm.call` 3 次重试后抛 RuntimeError。"""
    from taskprep.llm import LLMConfig, call

    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")
    mock_taskprep_anthropic.messages.create.side_effect = RuntimeError("API down")

    with pytest.raises(RuntimeError):
        call(cfg, "sys", "usr")

    assert mock_taskprep_anthropic.messages.create.call_count == 3
    assert fast_sleep == [2, 4]


# ── TC-83：Anthropic 客户端构造参数 ──


def test_tc83_llm_call_constructs_anthropic_correctly(
    mock_taskprep_anthropic: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLMConfig(provider="anthropic", api_key_env="ANTHROPIC_API_KEY") → Anthropic(api_key=...)。"""
    from taskprep.llm import LLMConfig, call

    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")
    mock_taskprep_anthropic.messages.create.return_value = make_anthropic_message("ok")

    call(cfg, "sys", "usr")

    mock_taskprep_anthropic._factory.assert_called_once()
    _, kwargs = mock_taskprep_anthropic._factory.call_args
    assert kwargs.get("api_key") == "test_anthropic_key"
