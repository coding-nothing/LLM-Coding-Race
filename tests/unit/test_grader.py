"""TC-38：grader 的 verify_log_tail 截断到 4000 字符。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.conftest import SampleTask


# ──────────────────────────────────────────────
# TC-38：8000 字符 stdout → verify_log_tail ≤ 4000
# ──────────────────────────────────────────────
def test_tc38_verify_log_tail_truncated_to_4000(
    sample_task: SampleTask, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness import grader as grader_module

    # 构造一个会写出 run_<n>.json 的最小输出目录
    output_dir = tmp_path / "outputs" / "x-model" / "sample-fix"
    output_dir.mkdir(parents=True)
    run_json_path = output_dir / "run_0.json"
    # extracted_diff 用 reference.diff 内容（保证可应用）
    ref_diff = (sample_task.task_dir / "reference.diff").read_text(encoding="utf-8")
    run_json_path.write_text(
        json.dumps({
            "model": "x-model",
            "task": "sample-fix",
            "run_index": 0,
            "extracted_diff": ref_diff,
            "output_format": "diff",
            "raw_blocks_count": 1,
            "raw_response": "...",
        }),
        encoding="utf-8",
    )

    # Mock subprocess.run，让 verify.sh 调用返回 8000 字符 stdout
    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        # 仅拦截 bash verify.sh ... 调用
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "verify.sh" in cmd_str or (isinstance(cmd, (list, tuple)) and any(
            "verify.sh" in str(c) for c in cmd
        )):
            result = MagicMock(spec=subprocess.CompletedProcess)
            result.returncode = 0
            result.stdout = "X" * 8000
            result.stderr = ""
            return result
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("subprocess.run", _fake_run)

    grader_module.grade_run(
        run_json_path=run_json_path,
        task_dir=sample_task.task_dir,
        repo_path=sample_task.repo.path,
    )

    grade_json = json.loads((output_dir / "grade_0.json").read_text(encoding="utf-8"))
    tail = grade_json.get("verify_log_tail") or ""
    assert len(tail) <= 4000


# ──────────────────────────────────────────────
# 补充：grade_<n>.json 含 PRD §B3.4 全部字段
# ──────────────────────────────────────────────
def test_grade_json_schema(
    sample_task: SampleTask, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness import grader as grader_module

    output_dir = tmp_path / "outputs" / "x-model" / "sample-fix"
    output_dir.mkdir(parents=True)
    run_json_path = output_dir / "run_0.json"
    run_json_path.write_text(
        json.dumps({
            "model": "x-model",
            "task": "sample-fix",
            "run_index": 0,
            "extracted_diff": "",
            "output_format": "none",
            "raw_blocks_count": 0,
        }),
        encoding="utf-8",
    )

    grader_module.grade_run(
        run_json_path=run_json_path,
        task_dir=sample_task.task_dir,
        repo_path=sample_task.repo.path,
    )

    grade = json.loads((output_dir / "grade_0.json").read_text(encoding="utf-8"))
    assert "diff_applies" in grade
    assert "tests_pass" in grade
    assert "verify_log_tail" in grade
    assert "human_scores" in grade
    assert grade["human_scores"] == {
        "correctness": None,
        "code_quality": None,
        "context_awareness": None,
    }
    assert grade["human_notes"] is None
