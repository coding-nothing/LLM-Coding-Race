"""generate_target_files — 生成 target_files.txt（main / reference / tree）。"""

from __future__ import annotations

from pathlib import Path

from taskprep.git_ops import changed_files
from taskprep.llm import LLMConfig, call

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _build_tree_section(main_files: list[str]) -> str:
    dirs: set[str] = set()
    for f in main_files:
        p = Path(f)
        parent = str(p.parent).replace("\\", "/")
        if parent and parent != ".":
            dirs.add(parent + "/")
            grandparent = str(p.parent.parent).replace("\\", "/")
            if grandparent and grandparent != ".":
                dirs.add(grandparent + "/")
    return "tree:\n" + "\n".join(sorted(dirs))


def generate_target_files(
    repo_path: Path, source_commit: str, llm: LLMConfig
) -> str:
    files = changed_files(repo_path, source_commit, exclude_tests=True)
    main_section = "main:\n" + "\n".join(files)

    tree_section = _build_tree_section(files)

    # LLM 推荐参考文件
    system = (_PROMPTS_DIR / "target_files.txt").read_text(encoding="utf-8")
    user = f"Main files (bug fix涉及的主要文件):\n" + "\n".join(files)
    llm_recommendation = call(llm, system, user)

    return f"{main_section}\n\nreference:\n{llm_recommendation}\n\n{tree_section}\n"
