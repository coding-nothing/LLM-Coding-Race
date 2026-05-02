"""TC-44 ~ TC-50：harness/cli.py 的子命令集成测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.conftest import (
    FixtureRepo,
    SampleTask,
    make_openai_completion,
)


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """通过子进程跑 `python -m harness.cli`，避免 sys.argv 污染。"""
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


# ──────────────────────────────────────────────
# TC-44：cli fetch --repo --ref 退出 0 + 路径打印
# ──────────────────────────────────────────────
def test_tc44_cli_fetch_with_repo_ref(
    make_repo: Callable[..., FixtureRepo], tmp_path: Path
) -> None:
    from harness.cli import main

    repo = make_repo()
    monkey_cwd = tmp_path / "workspace"
    monkey_cwd.mkdir()

    # 走进程内调用，避免 stdout 编码问题
    rc = main([
        "fetch",
        "--repo", f"file://{repo.path.as_posix()}",
        "--ref", repo.fix_commit,
        "--dest-root", str(monkey_cwd / "repos"),
    ])
    assert rc == 0
    cloned = list((monkey_cwd / "repos").iterdir())
    assert cloned, "fetch 应在 dest-root 下创建仓库目录"


# ──────────────────────────────────────────────
# TC-45：cli fetch --task <id> 从 meta.json 读 repo_url + base_commit
# ──────────────────────────────────────────────
def test_tc45_cli_fetch_by_task_id(sample_task: SampleTask, tmp_path: Path) -> None:
    from harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    rc = main([
        "fetch",
        "--task", "sample-fix",
        "--tasks-dir", str(sample_task.task_dir.parent),
        "--dest-root", str(workspace / "repos"),
    ])
    assert rc == 0
    cloned = list((workspace / "repos").iterdir())
    assert cloned


# ──────────────────────────────────────────────
# TC-46：--models deepseek,glm 应排除 claude
# ──────────────────────────────────────────────
def test_tc46_models_filter_excludes_claude(
    sample_task: SampleTask,
    tmp_path: Path,
    mock_openai: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.cli import main

    # 让 anthropic SDK 一旦被实例化就报错（证明 claude 没被调用）
    fail_if_called = MagicMock(side_effect=RuntimeError("claude must not be called"))
    monkeypatch.setattr("harness.runner.anthropic.Anthropic", fail_if_called, raising=False)

    mock_openai.chat.completions.create.return_value = make_openai_completion(
        "```diff\n--- a/x\n+++ b/x\n@@\n-old\n+new\n```\n"
    )

    output_dir = tmp_path / "outputs"
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    rc = main([
        "run",
        "--models", "deepseek-v4-pro,glm-5.1",
        "--tasks-dir", str(sample_task.task_dir.parent),
        "--output-dir", str(output_dir),
        "--repos-dir", str(repos_dir),
        "--repo-path", f"sample-fix={sample_task.repo.path}",
        "--runs", "1",
    ])
    assert rc == 0
    fail_if_called.assert_not_called()


# ──────────────────────────────────────────────
# TC-47：tasks/<id>/prompt.md.draft 存在 → run 退出非 0
# ──────────────────────────────────────────────
def test_tc47_draft_file_blocks_run(
    sample_task: SampleTask, tmp_path: Path
) -> None:
    from harness.cli import main

    # 制造一个 .draft 残留
    draft_path = sample_task.task_dir / "prompt.md.draft"
    draft_path.write_text("draft content", encoding="utf-8")

    output_dir = tmp_path / "outputs"
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    rc = main([
        "run",
        "--models", "deepseek-v4-pro",
        "--tasks-dir", str(sample_task.task_dir.parent),
        "--output-dir", str(output_dir),
        "--repos-dir", str(repos_dir),
        "--repo-path", f"sample-fix={sample_task.repo.path}",
        "--runs", "1",
    ])
    assert rc != 0


# ──────────────────────────────────────────────
# TC-48：--allow-drafts 跳过 .draft 检查
# ──────────────────────────────────────────────
def test_tc48_allow_drafts_bypasses_check(
    sample_task: SampleTask,
    tmp_path: Path,
    mock_openai: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from harness.cli import main

    (sample_task.task_dir / "prompt.md.draft").write_text(
        "draft", encoding="utf-8"
    )
    mock_openai.chat.completions.create.return_value = make_openai_completion(
        "```diff\n--- a/x\n+++ b/x\n@@\n-old\n+new\n```\n"
    )

    output_dir = tmp_path / "outputs"
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    rc = main([
        "run",
        "--models", "deepseek-v4-pro",
        "--tasks-dir", str(sample_task.task_dir.parent),
        "--output-dir", str(output_dir),
        "--repos-dir", str(repos_dir),
        "--repo-path", f"sample-fix={sample_task.repo.path}",
        "--runs", "1",
        "--allow-drafts",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    # 即便允许，也应在 stderr 给出警告
    combined = (captured.err + captured.out).lower()
    assert "draft" in combined or "warning" in combined


# ──────────────────────────────────────────────
# TC-49：缺 DEEPSEEK_API_KEY → run 启动阶段退出非 0
# ──────────────────────────────────────────────
def test_tc49_missing_api_key_aborts(
    sample_task: SampleTask,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.cli import main

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    output_dir = tmp_path / "outputs"
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    rc = main([
        "run",
        "--models", "deepseek-v4-pro",
        "--tasks-dir", str(sample_task.task_dir.parent),
        "--output-dir", str(output_dir),
        "--repos-dir", str(repos_dir),
        "--repo-path", f"sample-fix={sample_task.repo.path}",
        "--runs", "1",
    ])
    assert rc != 0


# ──────────────────────────────────────────────
# TC-50：cli all 顺序跑 fetch→run→grade→report，最终生成 reports/report.md
# ──────────────────────────────────────────────
def test_tc50_cli_all_end_to_end(
    sample_task: SampleTask,
    tmp_path: Path,
    mock_openai: MagicMock,
) -> None:
    from harness.cli import main

    ref_diff = (sample_task.task_dir / "reference.diff").read_text(encoding="utf-8")
    raw = f"修复方案：\n\n```diff\n{ref_diff}```\n"
    mock_openai.chat.completions.create.return_value = make_openai_completion(raw)

    output_dir = tmp_path / "outputs"
    repos_dir = tmp_path / "repos"
    reports_dir = tmp_path / "reports"
    repos_dir.mkdir()

    rc = main([
        "all",
        "--models", "deepseek-v4-pro",
        "--tasks-dir", str(sample_task.task_dir.parent),
        "--output-dir", str(output_dir),
        "--repos-dir", str(repos_dir),
        "--reports-dir", str(reports_dir),
        "--repo-path", f"sample-fix={sample_task.repo.path}",
        "--runs", "1",
    ])
    assert rc == 0
    report = reports_dir / "report.md"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "sample-fix" in text
    assert "deepseek-v4-pro" in text
