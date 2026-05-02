"""TC-23 ~ TC-28：harness/runner.py 的 call_model（含 retry / cache_control / extra_body）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.conftest import make_anthropic_message, make_openai_completion


# ──────────────────────────────────────────────
# TC-23：anthropic 路径走 anthropic SDK，system 用 list 形式
# ──────────────────────────────────────────────
def test_tc23_anthropic_path_uses_list_system(mock_anthropic: MagicMock) -> None:
    from harness.config import ModelConfig
    from harness.runner import call_model

    cfg = ModelConfig(
        name="claude-x", provider="anthropic", model_id="claude-x",
        base_url=None, api_key_env="ANTHROPIC_API_KEY",
        extra_params={}, supports_prompt_cache=False,
    )
    mock_anthropic.messages.create.return_value = make_anthropic_message("done")

    result = call_model(cfg, "SYS", "USR")

    assert result.get("error") is None
    assert mock_anthropic.messages.create.called
    kwargs = mock_anthropic.messages.create.call_args.kwargs
    assert isinstance(kwargs["system"], list), "anthropic system 必须 list 形式"
    # messages 中含 user prompt
    user_msg = next(m for m in kwargs["messages"] if m["role"] == "user")
    assert "USR" in str(user_msg)


# ──────────────────────────────────────────────
# TC-24：openai_compat 路径走 openai SDK，base_url 透传
# ──────────────────────────────────────────────
def test_tc24_openai_compat_path(mock_openai: MagicMock) -> None:
    from harness.config import ModelConfig
    from harness.runner import call_model

    cfg = ModelConfig(
        name="deepseek-x", provider="openai_compat", model_id="deepseek-x",
        base_url="https://api.example.com",
        api_key_env="DEEPSEEK_API_KEY",
        extra_params={}, supports_prompt_cache=False,
    )
    mock_openai.chat.completions.create.return_value = make_openai_completion("done")

    result = call_model(cfg, "SYS", "USR")

    assert result.get("error") is None
    # 构造 OpenAI() 时应传入 base_url
    factory_call = mock_openai._factory.call_args
    assert factory_call.kwargs.get("base_url") == "https://api.example.com"
    assert mock_openai.chat.completions.create.called


# ──────────────────────────────────────────────
# TC-25：前两次失败、第三次成功；sleep 顺序 [2, 4]
# ──────────────────────────────────────────────
def test_tc25_retry_with_exponential_backoff(
    mock_openai: MagicMock, fast_sleep: list[float]
) -> None:
    from harness.config import ModelConfig
    from harness.runner import call_model

    cfg = ModelConfig(
        name="x", provider="openai_compat", model_id="x",
        base_url="https://api.example.com", api_key_env="DEEPSEEK_API_KEY",
        extra_params={}, supports_prompt_cache=False,
    )

    mock_openai.chat.completions.create.side_effect = [
        RuntimeError("net 1"),
        RuntimeError("net 2"),
        make_openai_completion("ok"),
    ]

    result = call_model(cfg, "SYS", "USR")

    assert result.get("error") is None
    assert mock_openai.chat.completions.create.call_count == 3
    assert fast_sleep[:2] == [2, 4]


# ──────────────────────────────────────────────
# TC-26：始终失败 → 不抛异常，返回 dict 含 error
# ──────────────────────────────────────────────
def test_tc26_persistent_failure_returns_error_dict(
    mock_openai: MagicMock, fast_sleep: list[float]
) -> None:
    from harness.config import ModelConfig
    from harness.runner import call_model

    cfg = ModelConfig(
        name="x", provider="openai_compat", model_id="x",
        base_url="https://api.example.com", api_key_env="DEEPSEEK_API_KEY",
        extra_params={}, supports_prompt_cache=False,
    )
    mock_openai.chat.completions.create.side_effect = RuntimeError("permanent fail")

    result = call_model(cfg, "SYS", "USR")

    assert isinstance(result, dict)
    assert result.get("error") is not None
    assert "permanent fail" in str(result["error"]) or "RuntimeError" in str(result["error"])


# ──────────────────────────────────────────────
# TC-27：anthropic + supports_prompt_cache → system 长内容段标 cache_control
# ──────────────────────────────────────────────
def test_tc27_prompt_cache_control_set(mock_anthropic: MagicMock) -> None:
    from harness.config import ModelConfig
    from harness.runner import call_model

    cfg = ModelConfig(
        name="claude-x", provider="anthropic", model_id="claude-x",
        base_url=None, api_key_env="ANTHROPIC_API_KEY",
        extra_params={}, supports_prompt_cache=True,
    )
    mock_anthropic.messages.create.return_value = make_anthropic_message("ok")

    long_user = "# Files to modify\n" + "x" * 5000
    call_model(cfg, "SYS", long_user)

    kwargs = mock_anthropic.messages.create.call_args.kwargs
    # 在 messages 列表中找带 cache_control 的 block
    found_cache_control = False
    for m in kwargs["messages"]:
        content = m.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("cache_control") == {
                    "type": "ephemeral"
                }:
                    found_cache_control = True
                    break
    # 也可能放在 system 列表上
    sys_list = kwargs.get("system")
    if isinstance(sys_list, list):
        for block in sys_list:
            if isinstance(block, dict) and block.get("cache_control") == {
                "type": "ephemeral"
            }:
                found_cache_control = True

    assert found_cache_control, "cache_control={'type':'ephemeral'} 应出现在长内容段"


# ──────────────────────────────────────────────
# TC-28：extra_params 通过 extra_body 传 reasoning_effort
# ──────────────────────────────────────────────
def test_tc28_extra_params_via_extra_body(mock_openai: MagicMock) -> None:
    from harness.config import ModelConfig
    from harness.runner import call_model

    cfg = ModelConfig(
        name="deepseek-x", provider="openai_compat", model_id="deepseek-x",
        base_url="https://api.example.com",
        api_key_env="DEEPSEEK_API_KEY",
        extra_params={"reasoning_effort": "high"},
        supports_prompt_cache=False,
    )
    mock_openai.chat.completions.create.return_value = make_openai_completion("ok")

    call_model(cfg, "SYS", "USR")

    kwargs = mock_openai.chat.completions.create.call_args.kwargs
    extra_body = kwargs.get("extra_body") or {}
    # 允许 extra_params 也直接展开为 top-level kwargs 的实现
    assert (
        extra_body.get("reasoning_effort") == "high"
        or kwargs.get("reasoning_effort") == "high"
    )


# ──────────────────────────────────────────────
# 补充：返回 dict 含 PRD §B3.3 关键字段
# ──────────────────────────────────────────────
def test_call_model_return_dict_schema(mock_openai: MagicMock) -> None:
    from harness.config import ModelConfig
    from harness.runner import call_model

    cfg = ModelConfig(
        name="x", provider="openai_compat", model_id="x",
        base_url="https://api.example.com", api_key_env="DEEPSEEK_API_KEY",
        extra_params={}, supports_prompt_cache=False,
    )
    mock_openai.chat.completions.create.return_value = make_openai_completion(
        "ok", prompt_tokens=123, completion_tokens=45
    )

    result = call_model(cfg, "SYS", "USR")
    assert "raw_response" in result
    assert "usage" in result
    assert "latency_seconds" in result
    assert result["raw_response"] == "ok"
    assert result["usage"]["input_tokens"] == 123
    assert result["usage"]["output_tokens"] == 45
