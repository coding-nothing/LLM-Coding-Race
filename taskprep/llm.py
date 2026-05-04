"""taskprep LLM 调用模块 — 统一 Anthropic / OpenAI 兼容双 provider 入口。

与 harness.runner.call_model 解耦：taskprep 只要纯文本响应，语义/错误处理/重试预算均不同。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Literal

import anthropic
import openai

RETRY_BACKOFF = [2, 4]


@dataclass
class LLMConfig:
    model_id: str
    api_key_env: str
    base_url: str | None = None
    provider: Literal["anthropic", "openai_compat"] = "anthropic"


DEFAULT_DRAFT_MODEL = LLMConfig(
    model_id="claude-opus-4-7",
    api_key_env="ANTHROPIC_API_KEY",
    provider="anthropic",
)


def call(
    cfg: LLMConfig,
    system: str,
    user: str,
    *,
    max_tokens: int = 8000,
    temperature: float = 0.3,
) -> str:
    api_key = os.environ.get(cfg.api_key_env)
    if not api_key:
        raise RuntimeError(f"API key not found: env var {cfg.api_key_env} is not set")

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            if cfg.provider == "anthropic":
                client = anthropic.Anthropic(api_key=api_key)
                msg = client.messages.create(
                    model=cfg.model_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return msg.content[0].text
            else:
                client = openai.OpenAI(api_key=api_key, base_url=cfg.base_url)
                completion = client.chat.completions.create(
                    model=cfg.model_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return completion.choices[0].message.content
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(RETRY_BACKOFF[attempt])

    raise RuntimeError(
        f"LLM call failed after 3 attempts: {last_error}"
    ) from last_error
