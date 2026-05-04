"""generate_test_patch — LLM 生成 unified diff 测试补丁（最复杂的 generator）。

含格式验证 + 1 次重试 + [GENERATION_FAILED] 标记。
"""

from __future__ import annotations

from pathlib import Path

from taskprep.llm import LLMConfig, call

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _is_valid_unified_diff(text: str) -> bool:
    has_diff_header = False
    has_hunk = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--- a/") or stripped.startswith("--- /"):
            has_diff_header = True
        if stripped.startswith("+++ b/") or stripped.startswith("+++ /"):
            has_diff_header = True
        if stripped.startswith("@@"):
            has_hunk = True
    return has_diff_header and has_hunk


def generate_test_patch(
    debug_doc: str,
    reference_diff: str,
    main_files_content: dict[str, str],
    similar_test_samples: list[tuple[str, str]],
    project_test_framework: str,
    llm: LLMConfig,
) -> str:
    system = (_PROMPTS_DIR / "test_patch.txt").read_text(encoding="utf-8")

    samples_text = ""
    for path, content in similar_test_samples:
        samples_text += f"\n### {path}\n```\n{content}\n```\n"

    main_text = ""
    for path, content in main_files_content.items():
        main_text += f"\n### {path}\n```\n{content}\n```\n"

    user = (
        f"## Bug 描述\n\n{debug_doc}\n\n"
        f"## 参考修复 Diff\n\n```diff\n{reference_diff}\n```\n\n"
        f"## 主要文件的当前内容\n{main_text}\n"
        f"## 相似测试样本\n{samples_text}\n"
        f"## 项目测试框架\n\n{project_test_framework}\n"
    )

    for attempt in range(2):
        response = call(llm, system, user)
        if _is_valid_unified_diff(response):
            return response
        if attempt == 1:
            return f"# [GENERATION_FAILED] LLM 输出非合法 unified diff，需人工修正\n\n{response}"

    return ""  # unreachable
