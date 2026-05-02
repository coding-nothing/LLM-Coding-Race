"""TC-31 ~ TC-37：harness/grader.py 的 grade_run + _isolated_worktree。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.conftest import SampleTask


def _write_run_json(
    output_dir: Path, model: str, task: str, run_index: int, *,
    extracted_diff: str = "", output_format: str = "diff",
) -> Path:
    target = output_dir / model / task
    target.mkdir(parents=True, exist_ok=True)
    p = target / f"run_{run_index}.json"
    p.write_text(
        json.dumps({
            "model": model,
            "task": task,
            "run_index": run_index,
            "extracted_diff": extracted_diff,
            "output_format": output_format,
            "raw_blocks_count": 1 if extracted_diff else 0,
            "raw_response": "...",
        }),
        encoding="utf-8",
    )
    return p


# ──────────────────────────────────────────────
# TC-31：合法 reference.diff 作为答卷 → diff_applies=true, tests_pass=true
# ──────────────────────────────────────────────
def test_tc31_correct_diff_passes_tests(
    sample_task: SampleTask, tmp_path: Path
) -> None:
    from harness.grader import grade_run

    ref_diff = (sample_task.task_dir / "reference.diff").read_text(encoding="utf-8")
    output_dir = tmp_path / "outputs"
    run_json_path = _write_run_json(
        output_dir, "model-a", "sample-fix", 0,
        extracted_diff=ref_diff, output_format="diff",
    )

    grade_run(
        run_json_path=run_json_path,
        task_dir=sample_task.task_dir,
        repo_path=sample_task.repo.path,
    )

    grade = json.loads(
        (run_json_path.parent / "grade_0.json").read_text(encoding="utf-8")
    )
    assert grade["diff_applies"] is True
    assert grade["tests_pass"] is True
    assert grade["human_scores"]["correctness"] is None
    assert grade["human_scores"]["code_quality"] is None
    assert grade["human_scores"]["context_awareness"] is None


# ──────────────────────────────────────────────
# TC-32：上下文不匹配的 diff → diff_applies=false, tests_pass=null
# ──────────────────────────────────────────────
def test_tc32_unappliable_diff(sample_task: SampleTask, tmp_path: Path) -> None:
    from harness.grader import grade_run

    bad_diff = (
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -100,3 +100,3 @@\n"
        " context_that_does_not_exist\n"
        "-old\n"
        "+new\n"
    )
    output_dir = tmp_path / "outputs"
    run_json_path = _write_run_json(
        output_dir, "model-a", "sample-fix", 0,
        extracted_diff=bad_diff,
    )

    grade_run(
        run_json_path=run_json_path,
        task_dir=sample_task.task_dir,
        repo_path=sample_task.repo.path,
    )
    grade = json.loads(
        (run_json_path.parent / "grade_0.json").read_text(encoding="utf-8")
    )
    assert grade["diff_applies"] is False
    assert grade["tests_pass"] is None


# ──────────────────────────────────────────────
# TC-33：任务无 test_patch.diff → tests_pass=null
# ──────────────────────────────────────────────
def test_tc33_no_test_patch(sample_task: SampleTask, tmp_path: Path) -> None:
    from harness.grader import grade_run

    (sample_task.task_dir / "test_patch.diff").unlink()
    ref_diff = (sample_task.task_dir / "reference.diff").read_text(encoding="utf-8")
    output_dir = tmp_path / "outputs"
    run_json_path = _write_run_json(
        output_dir, "model-a", "sample-fix", 0, extracted_diff=ref_diff,
    )

    grade_run(
        run_json_path=run_json_path,
        task_dir=sample_task.task_dir,
        repo_path=sample_task.repo.path,
    )
    grade = json.loads(
        (run_json_path.parent / "grade_0.json").read_text(encoding="utf-8")
    )
    assert grade["tests_pass"] is None
    assert grade["verify_log_tail"] is None


# ──────────────────────────────────────────────
# TC-34：任务无 verify.sh → tests_pass=null
# ──────────────────────────────────────────────
def test_tc34_no_verify_sh(sample_task: SampleTask, tmp_path: Path) -> None:
    from harness.grader import grade_run

    (sample_task.task_dir / "verify.sh").unlink()
    ref_diff = (sample_task.task_dir / "reference.diff").read_text(encoding="utf-8")
    output_dir = tmp_path / "outputs"
    run_json_path = _write_run_json(
        output_dir, "model-a", "sample-fix", 0, extracted_diff=ref_diff,
    )

    grade_run(
        run_json_path=run_json_path,
        task_dir=sample_task.task_dir,
        repo_path=sample_task.repo.path,
    )
    grade = json.loads(
        (run_json_path.parent / "grade_0.json").read_text(encoding="utf-8")
    )
    assert grade["tests_pass"] is None
    assert grade["verify_log_tail"] is None


# ──────────────────────────────────────────────
# TC-35：_isolated_worktree 正常退出 → worktree 不再存在
# ──────────────────────────────────────────────
def test_tc35_isolated_worktree_cleaned_on_normal_exit(
    sample_task: SampleTask,
) -> None:
    from harness.grader import _isolated_worktree

    repo_path = sample_task.repo.path
    base_commit = sample_task.repo.init_commit

    with _isolated_worktree(repo_path, base_commit) as wt:
        assert wt.exists()
        wt_path_str = str(wt)

    list_out = subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "list"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert wt_path_str.replace("\\", "/") not in list_out.replace("\\", "/")
    assert not Path(wt_path_str).exists() or not any(Path(wt_path_str).iterdir())


# ──────────────────────────────────────────────
# TC-36：_isolated_worktree 内部异常 → 仍清理
# ──────────────────────────────────────────────
def test_tc36_isolated_worktree_cleaned_on_exception(
    sample_task: SampleTask,
) -> None:
    from harness.grader import _isolated_worktree

    repo_path = sample_task.repo.path
    base_commit = sample_task.repo.init_commit

    captured_path: list[Path] = []
    with pytest.raises(RuntimeError, match="boom"):
        with _isolated_worktree(repo_path, base_commit) as wt:
            captured_path.append(wt)
            raise RuntimeError("boom")

    list_out = subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "list"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert str(captured_path[0]).replace("\\", "/") not in list_out.replace("\\", "/")


# ──────────────────────────────────────────────
# TC-37：verify.sh 超时 → tests_pass=false 且 verify_log_tail 含 timeout
# ──────────────────────────────────────────────
def test_tc37_verify_timeout(
    sample_task: SampleTask, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness import grader as grader_module

    # 把 verify.sh 改成 sleep 60，再把 GRADE_TIMEOUT_SECONDS patch 到 1
    (sample_task.task_dir / "verify.sh").write_text(
        '#!/usr/bin/env bash\nset -e\ncd "$1"\nsleep 60\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(grader_module, "GRADE_TIMEOUT_SECONDS", 1, raising=False)

    ref_diff = (sample_task.task_dir / "reference.diff").read_text(encoding="utf-8")
    output_dir = tmp_path / "outputs"
    run_json_path = _write_run_json(
        output_dir, "model-a", "sample-fix", 0, extracted_diff=ref_diff,
    )

    grader_module.grade_run(
        run_json_path=run_json_path,
        task_dir=sample_task.task_dir,
        repo_path=sample_task.repo.path,
    )
    grade = json.loads(
        (run_json_path.parent / "grade_0.json").read_text(encoding="utf-8")
    )
    assert grade["tests_pass"] is False
    tail = (grade.get("verify_log_tail") or "").lower()
    assert "timeout" in tail or "timed out" in tail
