"""统一 LLM 调用入口 + 批量 run 协调。

PRD §B4.3 / §B5：
- anthropic 路径用 messages.create，system 用 list 形式（便于挂 cache_control）。
- openai_compat 路径走 OpenAI SDK，extra_params 通过 extra_body 透传。
- 错误重试：指数退避 [2, 4, 8] 秒；最终失败不抛异常，返回 dict 含 error。
- 幂等：run_<n>.json 已存在则跳过。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
import openai

from harness.config import (
    MAX_OUTPUT_TOKENS,
    RETRY_BACKOFF,
    TEMPERATURE,
    ModelConfig,
)
from harness.context import build_context, estimate_tokens
from harness.parser import extract_changes


def _split_user_for_cache(user: str) -> tuple[str, str]:
    """把 user prompt 拆为 prefix + cacheable suffix（# Files to modify 起点）。"""
    marker = "# Files to modify"
    idx = user.find(marker)
    if idx <= 0:
        return user, ""
    return user[:idx], user[idx:]


def _call_anthropic(cfg: ModelConfig, system: str, user: str) -> dict:
    client = anthropic.Anthropic(api_key=os.environ.get(cfg.api_key_env, ""))

    if cfg.supports_prompt_cache:
        prefix, cache_suffix = _split_user_for_cache(user)
        if cache_suffix:
            user_content: list[dict] | str = [
                {"type": "text", "text": prefix},
                {
                    "type": "text",
                    "text": cache_suffix,
                    "cache_control": {"type": "ephemeral"},
                },
            ]
        else:
            user_content = [
                {
                    "type": "text",
                    "text": user,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
    else:
        user_content = user

    system_blocks = [{"type": "text", "text": system}]

    msg = client.messages.create(
        model=cfg.model_id,
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=TEMPERATURE,
        system=system_blocks,
        messages=[{"role": "user", "content": user_content}],
    )

    text_parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", "") or "")
    raw_text = "".join(text_parts)
    usage = msg.usage
    return {
        "raw_response": raw_text,
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        },
    }


def _call_openai_compat(cfg: ModelConfig, system: str, user: str) -> dict:
    client = openai.OpenAI(
        api_key=os.environ.get(cfg.api_key_env, ""),
        base_url=cfg.base_url,
    )

    kwargs: dict[str, Any] = {
        "model": cfg.model_id,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": TEMPERATURE,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if cfg.extra_params:
        kwargs["extra_body"] = dict(cfg.extra_params)

    completion = client.chat.completions.create(**kwargs)

    text = ""
    if completion.choices:
        text = completion.choices[0].message.content or ""
    usage = completion.usage
    cached = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    return {
        "raw_response": text,
        "usage": {
            "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "cache_read_tokens": cached,
        },
    }


def call_model(cfg: ModelConfig, system: str, user: str) -> dict:
    """对外的统一调用入口。最终失败也不抛异常，返回 dict 含 error 字段。"""
    last_error: BaseException | None = None
    start = time.time()
    attempts = len(RETRY_BACKOFF)

    for attempt in range(attempts):
        try:
            if cfg.provider == "anthropic":
                result = _call_anthropic(cfg, system, user)
            else:
                result = _call_openai_compat(cfg, system, user)
            result["latency_seconds"] = time.time() - start
            result["error"] = None
            return result
        except Exception as exc:  # noqa: BLE001 — runner 必须吞所有 SDK 异常
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(RETRY_BACKOFF[attempt])

    return {
        "raw_response": "",
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
        "latency_seconds": time.time() - start,
        "error": f"{type(last_error).__name__}: {last_error}",
    }


def _read_main_files(task_dir: Path) -> list[str]:
    out: list[str] = []
    text = (task_dir / "target_files.txt").read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        kind, _, val = line.partition(":")
        if kind.strip().lower() == "main":
            v = val.strip()
            if v:
                out.append(v)
    return out


def run_all(
    tasks_dir: Path,
    repo_paths: dict[str, Path],
    output_dir: Path,
    models: list[ModelConfig],
    runs: int,
) -> None:
    tasks_dir = Path(tasks_dir)
    output_dir = Path(output_dir)

    if not tasks_dir.exists():
        return

    for task_dir in sorted(p for p in tasks_dir.iterdir() if p.is_dir()):
        task_id = task_dir.name
        repo_path = repo_paths.get(task_id)
        if repo_path is None:
            continue

        try:
            system, user = build_context(repo_path, task_dir)
        except FileNotFoundError:
            continue
        try:
            main_files = _read_main_files(task_dir)
        except OSError:
            main_files = []

        for cfg in models:
            for run_idx in range(runs):
                out_dir = output_dir / cfg.name / task_id
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / f"run_{run_idx}.json"
                if out_file.exists():
                    continue

                result = call_model(cfg, system, user)
                extracted = extract_changes(
                    result.get("raw_response") or "", main_files, repo_path
                )

                payload = {
                    "model": cfg.name,
                    "task": task_id,
                    "run_index": run_idx,
                    "timestamp_iso": datetime.now(timezone.utc).isoformat(),
                    "prompt_input_chars": len(user),
                    "prompt_input_tokens_estimated": estimate_tokens(user),
                    "raw_response": result.get("raw_response", ""),
                    "extracted_diff": extracted["diff_text"],
                    "output_format": extracted["format"],
                    "raw_blocks_count": extracted["raw_blocks_count"],
                    "usage": result.get("usage", {}),
                    "latency_seconds": result.get("latency_seconds", 0),
                    "error": result.get("error"),
                }
                out_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
