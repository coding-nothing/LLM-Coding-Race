"""TC-01 ~ TC-05：harness/config.py 的 ModelConfig / MODELS / load_dotenv。"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest


# ──────────────────────────────────────────────
# TC-01：ModelConfig 是 frozen dataclass
# ──────────────────────────────────────────────
def test_tc01_model_config_is_frozen() -> None:
    from harness.config import ModelConfig

    cfg = ModelConfig(
        name="x",
        provider="anthropic",
        model_id="x",
        base_url=None,
        api_key_env="X_KEY",
        extra_params={},
        supports_prompt_cache=False,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.name = "y"  # type: ignore[misc]


# ──────────────────────────────────────────────
# TC-02：MODELS 三模型配置与 PRD §B3.2 完全一致
# ──────────────────────────────────────────────
def test_tc02_models_match_prd_spec() -> None:
    from harness.config import MODELS

    assert len(MODELS) == 3
    by_name = {m.name: m for m in MODELS}

    assert "claude-opus-4-7" in by_name
    claude = by_name["claude-opus-4-7"]
    assert claude.provider == "anthropic"
    assert claude.model_id == "claude-opus-4-7"
    assert claude.base_url is None
    assert claude.api_key_env == "ANTHROPIC_API_KEY"
    assert claude.supports_prompt_cache is True

    assert "deepseek-v4-pro" in by_name
    deepseek = by_name["deepseek-v4-pro"]
    assert deepseek.provider == "openai_compat"
    assert deepseek.model_id == "deepseek-v4-pro"
    assert deepseek.base_url == "https://api.deepseek.com"
    assert deepseek.api_key_env == "DEEPSEEK_API_KEY"
    assert deepseek.extra_params.get("reasoning_effort") == "high"

    assert "glm-5.1" in by_name
    glm = by_name["glm-5.1"]
    assert glm.provider == "openai_compat"
    assert glm.model_id == "glm-5.1"
    assert glm.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert glm.api_key_env == "ZHIPU_API_KEY"


def test_tc02_global_constants() -> None:
    from harness import config

    assert config.TEMPERATURE == 0.2
    assert config.MAX_OUTPUT_TOKENS == 16000
    assert config.RUNS_PER_TASK == 2


# ──────────────────────────────────────────────
# TC-03：load_dotenv 写入未设置的键
# ──────────────────────────────────────────────
def test_tc03_load_dotenv_sets_missing_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.config import load_dotenv

    monkeypatch.delenv("MY_FRESH_KEY", raising=False)
    (tmp_path / ".env").write_text("MY_FRESH_KEY=hello_world\n", encoding="utf-8")

    load_dotenv(tmp_path)
    assert os.environ["MY_FRESH_KEY"] == "hello_world"


# ──────────────────────────────────────────────
# TC-04：load_dotenv 不覆盖已有 env
# ──────────────────────────────────────────────
def test_tc04_load_dotenv_does_not_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.config import load_dotenv

    monkeypatch.setenv("ALREADY_SET", "original")
    (tmp_path / ".env").write_text("ALREADY_SET=overridden\n", encoding="utf-8")

    load_dotenv(tmp_path)
    assert os.environ["ALREADY_SET"] == "original"


# ──────────────────────────────────────────────
# TC-05：load_dotenv 在 .env 不存在时静默跳过
# ──────────────────────────────────────────────
def test_tc05_load_dotenv_no_env_file(tmp_path: Path) -> None:
    from harness.config import load_dotenv

    assert not (tmp_path / ".env").exists()
    load_dotenv(tmp_path)


def test_tc05_load_dotenv_handles_blank_and_comment_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """补充：空行 / 注释行 / 等号缺失行不应报错。"""
    from harness.config import load_dotenv

    monkeypatch.delenv("VALID_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "\n# this is a comment\n   \nVALID_KEY=ok\nINVALID_LINE_NO_EQUALS\n",
        encoding="utf-8",
    )
    load_dotenv(tmp_path)
    assert os.environ["VALID_KEY"] == "ok"
