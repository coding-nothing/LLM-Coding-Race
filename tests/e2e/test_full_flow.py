"""TC-73：端到端 — taskprep draft → 人工 rename → harness all。

mock 所有 LLM 调用、用 fixture 仓库；只走文件系统契约。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.conftest import (
    SampleTask,
    make_openai_completion,
)


def test_tc73_taskprep_to_harness_full_flow(
    sample_task: SampleTask,
    tmp_path: Path,
    mock_openai: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对应 PRD §A11.6 + §B7.4 的端到端验收。

    流程（详见 references/test-plan-llm-coding-harness.md §E2E 测试场景）：
      1) sample_task fixture 已等价于 taskprep draft + 人工审核后的产物
         （Phase 1 阶段 taskprep 还未实现，先用 fixture 替代）
      2) harness cli all 跑 fetch→run→grade→report
      3) 断言 outputs/<m>/<task>/run_0.json + grade_0.json + reports/report.md
      4) 再跑一次 cli all，无新调用（幂等）
    """
    from harness.cli import main

    ref_diff = (sample_task.task_dir / "reference.diff").read_text(encoding="utf-8")
    raw = f"```diff\n{ref_diff}```\n"
    mock_openai.chat.completions.create.return_value = make_openai_completion(raw)

    output_dir = tmp_path / "outputs"
    repos_dir = tmp_path / "repos"
    reports_dir = tmp_path / "reports"
    repos_dir.mkdir()

    common_args = [
        "all",
        "--models", "deepseek-v4-pro",
        "--tasks-dir", str(sample_task.task_dir.parent),
        "--output-dir", str(output_dir),
        "--repos-dir", str(repos_dir),
        "--reports-dir", str(reports_dir),
        "--repo-path", f"sample-fix={sample_task.repo.path}",
        "--runs", "1",
    ]

    # Round 1
    rc1 = main(common_args)
    assert rc1 == 0
    run_json = output_dir / "deepseek-v4-pro" / "sample-fix" / "run_0.json"
    grade_json = output_dir / "deepseek-v4-pro" / "sample-fix" / "grade_0.json"
    report_md = reports_dir / "report.md"
    assert run_json.is_file()
    assert grade_json.is_file()
    assert report_md.is_file()
    assert "sample-fix" in report_md.read_text(encoding="utf-8")

    # Round 2 — 幂等：SDK 调用次数不再增加
    call_count_before = mock_openai.chat.completions.create.call_count
    rc2 = main(common_args)
    assert rc2 == 0
    assert mock_openai.chat.completions.create.call_count == call_count_before, (
        "幂等：第二次 cli all 不应再调用 SDK"
    )


def test_tc73_draft_files_block_e2e(
    sample_task: SampleTask, tmp_path: Path
) -> None:
    """补充：若 .draft 残留未被人工审核掉，整个 e2e 链路应被阻断。"""
    from harness.cli import main

    (sample_task.task_dir / "prompt.md.draft").write_text("d", encoding="utf-8")

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
    assert rc != 0
