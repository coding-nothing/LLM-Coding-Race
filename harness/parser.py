"""模型输出解析：把 raw 文本转为可应用的 unified diff。

四级 fallback（PRD §B4.4）：
1. 单/多个 ```diff 块 → 取最后一个非空块
2. ## File: <path> + 紧随的代码块 → 转 unified diff
3. N 个匿名代码块且 N == len(main_files) → 按顺序映射
4. 其余 → format=none, diff_text=""

任意失败都不抛错；返回 dict 含 format / diff_text / raw_blocks_count。
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

_BLOCK_RE = re.compile(r"```([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)
_FILE_HEADER_RE = re.compile(r"^##\s+File:\s+(.+?)\s*$", re.MULTILINE)


def extract_changes(raw: str, main_files: list[str], repo_path: Path) -> dict:
    repo_path = Path(repo_path)
    blocks = _extract_code_blocks(raw)
    raw_blocks_count = len(blocks)

    # 优先级 1：```diff 块
    diff_blocks = [b for b in blocks if b["lang"] == "diff" and b["text"].strip()]
    if diff_blocks:
        last_diff = diff_blocks[-1]["text"]
        if _looks_like_unified_diff(last_diff):
            return {
                "format": "diff",
                "diff_text": _normalize_diff(last_diff),
                "raw_blocks_count": raw_blocks_count,
            }

    # 优先级 2：## File: <path> + 紧随代码块
    file_sections = _extract_file_sections(raw)
    if file_sections:
        filtered = {p: c for p, c in file_sections.items() if p in main_files}
        if filtered:
            unified = _files_to_unified_diff(filtered, repo_path)
            if unified.strip():
                return {
                    "format": "files",
                    "diff_text": unified,
                    "raw_blocks_count": raw_blocks_count,
                }

    # 优先级 3：匿名代码块按 main_files 顺序映射
    if not file_sections:
        anon_blocks = [b for b in blocks if b["lang"] != "diff" and b["text"].strip()]
        if anon_blocks and main_files:
            n = min(len(anon_blocks), len(main_files))
            mapped = {main_files[i]: anon_blocks[i]["text"] for i in range(n)}
            unified = _files_to_unified_diff(mapped, repo_path)
            if unified.strip():
                return {
                    "format": "files",
                    "diff_text": unified,
                    "raw_blocks_count": raw_blocks_count,
                }

    return {
        "format": "none",
        "diff_text": "",
        "raw_blocks_count": raw_blocks_count,
    }


def _extract_code_blocks(raw: str) -> list[dict]:
    out: list[dict] = []
    for m in _BLOCK_RE.finditer(raw):
        out.append({"lang": m.group(1).lower(), "text": m.group(2)})
    return out


def _looks_like_unified_diff(text: str) -> bool:
    has_headers = "--- " in text and "+++ " in text
    is_git_diff = text.lstrip().startswith("diff --git")
    return has_headers or is_git_diff


def _normalize_diff(text: str) -> str:
    """统一行尾为 LF，确保末尾有换行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def _extract_file_sections(raw: str) -> dict[str, str]:
    """匹配 '## File: <path>' 后紧随的第一个代码块。"""
    sections: dict[str, str] = {}
    for header in _FILE_HEADER_RE.finditer(raw):
        path = header.group(1).strip()
        rest = raw[header.end():]
        block = _BLOCK_RE.search(rest)
        if block:
            sections[path] = block.group(2)
    return sections


def _files_to_unified_diff(files: dict[str, str], repo_path: Path) -> str:
    parts: list[str] = []
    for rel, new_content in files.items():
        old_path = repo_path / rel
        if old_path.is_file():
            try:
                old = old_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                old = old_path.read_text(encoding="utf-8", errors="replace")
        else:
            old = ""
        if not new_content.endswith("\n"):
            new_content = new_content + "\n"
        if old and not old.endswith("\n"):
            old = old + "\n"
        diff_lines = list(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                n=3,
            )
        )
        parts.append("".join(diff_lines))
    return "".join(parts)
