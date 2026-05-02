"""TC-12 ~ TC-16：harness/context.py 的 build_context / estimate_tokens。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import FixtureRepo, SampleTask


# ──────────────────────────────────────────────
# TC-12：build_context 不读取 reference.diff / test_patch.diff / verify.sh（防答案泄露）
# ──────────────────────────────────────────────
def test_tc12_build_context_does_not_read_answer_files(
    sample_task: SampleTask, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness import context as ctx_module

    opened: list[str] = []
    real_read_text = Path.read_text

    def _spy_read_text(self: Path, *args: object, **kwargs: object) -> str:
        opened.append(str(self).replace("\\", "/"))
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", _spy_read_text)

    system, user = ctx_module.build_context(
        sample_task.repo.path, sample_task.task_dir
    )
    assert isinstance(system, str) and len(system) > 0
    assert isinstance(user, str) and len(user) > 0

    forbidden = ("reference.diff", "test_patch.diff", "verify.sh")
    for path in opened:
        for forbid in forbidden:
            assert forbid not in path, f"build_context 不应读取 {forbid}（实际读了 {path}）"


# ──────────────────────────────────────────────
# TC-13：user_prompt 含 ## File: 段且按 main → reference → tree 顺序
# ──────────────────────────────────────────────
def test_tc13_user_prompt_section_order(sample_task: SampleTask) -> None:
    from harness import context as ctx_module

    _, user = ctx_module.build_context(sample_task.repo.path, sample_task.task_dir)

    assert "## File: src/a.py" in user
    assert "## File: src/b.ts" in user

    main_idx = user.index("## File: src/a.py")
    ref_idx = user.index("## File: src/b.ts")
    assert main_idx < ref_idx, "main 文件应排在 reference 之前"

    assert "# Files to modify" in user
    assert "# Reference files" in user
    files_idx = user.index("# Files to modify")
    ref_section_idx = user.index("# Reference files")
    assert files_idx < ref_section_idx


def test_tc13_user_prompt_uses_fenced_blocks(sample_task: SampleTask) -> None:
    from harness import context as ctx_module

    _, user = ctx_module.build_context(sample_task.repo.path, sample_task.task_dir)
    # Python 文件应在 ```python 围栏块内
    assert "```python" in user


# ──────────────────────────────────────────────
# TC-14：围栏语言按文件后缀
# ──────────────────────────────────────────────
@pytest.mark.parametrize(
    "filename,expected_lang",
    [("a.py", "python"), ("b.ts", "typescript"), ("c.unknown", "")],
)
def test_tc14_fence_language_by_extension(
    tmp_path: Path,
    make_repo: Callable[..., FixtureRepo],
    filename: str,
    expected_lang: str,
) -> None:
    from harness import context as ctx_module

    repo = make_repo(name=f"repo_{filename.replace('.', '_')}")
    # 给 repo 添加目标文件
    target = repo.path / filename
    target.write_text("placeholder content\n", encoding="utf-8")

    task_dir = tmp_path / f"task_{filename}"
    task_dir.mkdir()
    (task_dir / "prompt.md").write_text("# T\n", encoding="utf-8")
    (task_dir / "target_files.txt").write_text(
        f"main:{filename}\ntree:./\n", encoding="utf-8"
    )

    _, user = ctx_module.build_context(repo.path, task_dir)
    if expected_lang:
        assert f"```{expected_lang}" in user
    else:
        # 未知后缀应回落到无语言标记的围栏（仅 ``` 紧跟文件 header）
        header = f"## File: {filename}"
        assert header in user
        block_start = user.index(header)
        # header 之后第一段围栏应为裸 ```
        snippet = user[block_start : block_start + 200]
        assert "```\n" in snippet or snippet.rstrip().endswith("```")


# ──────────────────────────────────────────────
# TC-15：缺 prompt.md 抛 FileNotFoundError
# ──────────────────────────────────────────────
def test_tc15_missing_prompt_md_raises(
    tmp_path: Path, make_repo: Callable[..., FixtureRepo]
) -> None:
    from harness import context as ctx_module

    repo = make_repo()
    task_dir = tmp_path / "incomplete_task"
    task_dir.mkdir()
    (task_dir / "target_files.txt").write_text("main:src/a.py\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        ctx_module.build_context(repo.path, task_dir)


def test_tc15_missing_target_files_raises(
    tmp_path: Path, make_repo: Callable[..., FixtureRepo]
) -> None:
    from harness import context as ctx_module

    repo = make_repo()
    task_dir = tmp_path / "incomplete_task2"
    task_dir.mkdir()
    (task_dir / "prompt.md").write_text("# T\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        ctx_module.build_context(repo.path, task_dir)


# ──────────────────────────────────────────────
# TC-16：estimate_tokens = len // 4
# ──────────────────────────────────────────────
def test_tc16_estimate_tokens() -> None:
    from harness.context import estimate_tokens

    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("") == 0
    assert estimate_tokens("ab") == 0  # len // 4 → 0
