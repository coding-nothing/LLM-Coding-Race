"""TC-91 ~ TC-93：taskprep CLI 集成测试。

Phase 2 /gen-test 阶段新建。taskprep 模块尚未实现，导入会失败——预期在 /implement 后转绿。
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ── TC-91：local-repo 不是 git 仓库 → 退出非 0 ──


def test_tc91_cli_draft_non_repo_exits(
    tmp_path: Path, debug_doc_sample: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """local-repo 不是 git 仓库 → 启动阶段退出非 0，stderr 含错误说明。"""
    from taskprep.cli import main

    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()
    tasks_dir = tmp_path / "tasks"

    monkeypatch.chdir(tmp_path)
    exit_code = main([
        "draft",
        "--repo-url", f"file://{non_repo.as_posix()}",
        "--commit", "abc123",
        "--local-repo", str(non_repo),
        "--debug-doc", str(debug_doc_sample),
        "--task-id", "test-fix",
        "--output-dir", str(tasks_dir),
    ])
    assert exit_code != 0


# ── TC-92：commit 不存在 → 退出非 0 ──


def test_tc92_cli_draft_bad_commit_exits(
    tmp_path: Path, make_repo, debug_doc_sample: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """commit hash 不存在 → 启动阶段退出非 0。"""
    from taskprep.cli import main

    repo = make_repo()
    tasks_dir = tmp_path / "tasks"

    monkeypatch.chdir(tmp_path)
    exit_code = main([
        "draft",
        "--repo-url", f"file://{repo.path.as_posix()}",
        "--commit", "deadbeef" * 5,  # 40 位不存在的 hash
        "--local-repo", str(repo.path),
        "--debug-doc", str(debug_doc_sample),
        "--task-id", "test-fix",
        "--output-dir", str(tasks_dir),
    ])
    assert exit_code != 0


# ── TC-93：缺 API key → 退出非 0 ──


def test_tc93_cli_draft_missing_api_key_exits(
    tmp_path: Path,
    make_repo,
    debug_doc_sample: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺 ANTHROPIC_API_KEY → 启动阶段退出非 0，提示缺 key。"""
    from taskprep.cli import main

    repo = make_repo()
    tasks_dir = tmp_path / "tasks"

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = main([
        "draft",
        "--repo-url", f"file://{repo.path.as_posix()}",
        "--commit", repo.fix_commit,
        "--local-repo", str(repo.path),
        "--debug-doc", str(debug_doc_sample),
        "--task-id", "test-fix",
        "--output-dir", str(tasks_dir),
    ])
    assert exit_code != 0
