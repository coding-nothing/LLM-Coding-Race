"""根据任务目录构造 system + user prompt。

防答案泄露：仅读取 prompt.md / target_files.txt 与目标仓库内的源文件，
绝不读取 reference.diff / test_patch.diff / verify.sh。
"""

from __future__ import annotations

from pathlib import Path

_LANG_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".sh": "bash",
    ".md": "markdown",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
}


def estimate_tokens(text: str) -> int:
    """粗估 token 数（4 chars ≈ 1 token）。"""
    return len(text) // 4


def _read_target_files(task_dir: Path) -> dict[str, list[str]]:
    text = (task_dir / "target_files.txt").read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {"main": [], "reference": [], "tree": []}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        kind, _, val = line.partition(":")
        kind = kind.strip().lower()
        val = val.strip()
        if kind in sections and val:
            sections[kind].append(val)
    return sections


def _file_block(repo_path: Path, rel: str) -> str:
    target = repo_path / rel
    ext = Path(rel).suffix.lower()
    lang = _LANG_BY_EXT.get(ext, "")
    if target.is_file():
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = target.read_text(encoding="utf-8", errors="replace")
    else:
        content = "(file not found)"
    fence = f"```{lang}" if lang else "```"
    return f"## File: {rel}\n\n{fence}\n{content}\n```\n"


def _list_tree(repo_path: Path, dirs: list[str]) -> str:
    out: list[str] = []
    for d in dirs:
        target = repo_path / d
        if not target.exists() or not target.is_dir():
            continue
        entries: list[str] = []
        for p in sorted(target.rglob("*")):
            try:
                rel = p.relative_to(repo_path)
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel.parts):
                continue
            if p.is_file():
                entries.append(rel.as_posix())
        out.append(f"### {d}\n\n" + "\n".join(f"- {e}" for e in entries))
    return "\n\n".join(out)


def build_context(repo_path: Path, task_dir: Path) -> tuple[str, str]:
    repo_path = Path(repo_path)
    task_dir = Path(task_dir)
    prompt_md = task_dir / "prompt.md"
    target_files = task_dir / "target_files.txt"
    if not prompt_md.is_file():
        raise FileNotFoundError(f"missing {prompt_md}")
    if not target_files.is_file():
        raise FileNotFoundError(f"missing {target_files}")

    prompt_text = prompt_md.read_text(encoding="utf-8")
    sections = _read_target_files(task_dir)

    system = (
        "You are an expert software engineer.\n"
        "Read the task description and the provided source files, then output a "
        "unified diff that fixes the issue.\n\n"
        "Output format requirements:\n"
        "- Wrap the diff in a ```diff fenced code block.\n"
        "- Use unified diff with `--- a/<path>` and `+++ b/<path>` headers.\n"
        "- Modify only files listed under `# Files to modify`.\n"
        "- Keep the diff minimal; do not reformat unrelated code.\n"
    )

    parts: list[str] = []
    parts.append("# Task")
    parts.append("")
    parts.append(prompt_text.rstrip() + "\n")
    parts.append("# Files to modify")
    parts.append("")
    if sections["main"]:
        for rel in sections["main"]:
            parts.append(_file_block(repo_path, rel))
    if sections["reference"]:
        parts.append("# Reference files")
        parts.append("")
        for rel in sections["reference"]:
            parts.append(_file_block(repo_path, rel))
    if sections["tree"]:
        parts.append("# Project tree")
        parts.append("")
        parts.append(_list_tree(repo_path, sections["tree"]))

    user = "\n".join(parts)
    return system, user
