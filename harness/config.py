"""模型配置、全局常量与 .env 加载器。

PRD §B3.2 冻结 schema；本模块只是把 schema 转成 Python 数据。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TEMPERATURE: float = 0.2
MAX_OUTPUT_TOKENS: int = 16000
RUNS_PER_TASK: int = 2
GRADE_TIMEOUT_SECONDS: int = 300
RETRY_BACKOFF: list[int] = [2, 4, 8]


@dataclass(frozen=True)
class ModelConfig:
    name: str
    provider: Literal["anthropic", "openai_compat"]
    model_id: str
    base_url: str | None
    api_key_env: str
    extra_params: dict
    supports_prompt_cache: bool


MODELS: list[ModelConfig] = [
    ModelConfig(
        name="claude-opus-4-7",
        provider="anthropic",
        model_id="claude-opus-4-7",
        base_url=None,
        api_key_env="ANTHROPIC_API_KEY",
        extra_params={},
        supports_prompt_cache=True,
    ),
    ModelConfig(
        name="deepseek-v4-pro",
        provider="openai_compat",
        model_id="deepseek-v4-pro",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        extra_params={"reasoning_effort": "high"},
        supports_prompt_cache=False,
    ),
    ModelConfig(
        name="glm-5.1",
        provider="openai_compat",
        model_id="glm-5.1",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_env="ZHIPU_API_KEY",
        extra_params={},
        supports_prompt_cache=False,
    ),
]


def load_dotenv(project_root: Path) -> None:
    """读取 project_root/.env，把未设置的键写入 os.environ。

    - 已存在的 env 不覆盖
    - 注释行 / 空行 / 缺等号行忽略
    - 文件不存在静默跳过
    """
    env_path = Path(project_root) / ".env"
    if not env_path.is_file():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
