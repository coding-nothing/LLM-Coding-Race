"""generate_prompt — 将 debug doc 重组为 7 段式 prompt.md。"""

from __future__ import annotations

from pathlib import Path

from taskprep.llm import LLMConfig, call

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

REQUIRED_SECTIONS = [
    "目标",
    "当前行为",
    "复现步骤",
    "错误信息",
    "期望行为",
    "验收标准",
    "约束",
]


def generate_prompt(debug_doc: str, commit_message: str, llm: LLMConfig) -> str:
    system = (_PROMPTS_DIR / "prompt_md.txt").read_text(encoding="utf-8")
    user = f"## Commit Message\n\n{commit_message}\n\n## Debug Document\n\n{debug_doc}"

    response = call(llm, system, user)

    for section in REQUIRED_SECTIONS:
        if f"# {section}" not in response:
            response += f"\n\n# {section}\n\n[需要补充]\n"

    return response
