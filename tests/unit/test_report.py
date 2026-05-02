"""TC-39 ~ TC-43：harness/report.py 的 generate_report。"""

from __future__ import annotations

import json
from pathlib import Path


def _write_run_grade(
    output_dir: Path,
    model: str,
    task: str,
    run_index: int,
    *,
    output_format: str = "diff",
    diff_applies: bool = True,
    tests_pass: bool | None = True,
    verify_log_tail: str | None = "all good",
    latency: float = 1.0,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> None:
    target = output_dir / model / task
    target.mkdir(parents=True, exist_ok=True)
    (target / f"run_{run_index}.json").write_text(
        json.dumps({
            "model": model,
            "task": task,
            "run_index": run_index,
            "timestamp_iso": "2026-04-29T00:00:00Z",
            "prompt_input_chars": 1000,
            "prompt_input_tokens_estimated": 250,
            "raw_response": "...",
            "extracted_diff": "diff content",
            "output_format": output_format,
            "raw_blocks_count": 1,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": 0,
            },
            "latency_seconds": latency,
            "error": None,
        }),
        encoding="utf-8",
    )
    (target / f"grade_{run_index}.json").write_text(
        json.dumps({
            "diff_applies": diff_applies,
            "tests_pass": tests_pass,
            "verify_log_tail": verify_log_tail,
            "human_scores": {
                "correctness": None,
                "code_quality": None,
                "context_awareness": None,
            },
            "human_notes": None,
        }),
        encoding="utf-8",
    )


# ──────────────────────────────────────────────
# TC-39：总览表覆盖 (task, model) 全组合
# ──────────────────────────────────────────────
def test_tc39_overview_table_covers_all_combinations(tmp_path: Path) -> None:
    from harness.report import generate_report

    output_dir = tmp_path / "outputs"
    for model in ["claude-opus-4-7", "deepseek-v4-pro", "glm-5.1"]:
        for task in ["fix-01", "feature-02"]:
            for n in range(2):
                _write_run_grade(output_dir, model, task, n)

    report_path = tmp_path / "reports" / "report.md"
    generate_report(output_dir=output_dir, report_path=report_path)

    text = report_path.read_text(encoding="utf-8")
    for model in ["claude-opus-4-7", "deepseek-v4-pro", "glm-5.1"]:
        for task in ["fix-01", "feature-02"]:
            assert model in text
            assert task in text


# ──────────────────────────────────────────────
# TC-40：按模型聚合 — 平均延迟 / 总 token / 输出格式合规率
# ──────────────────────────────────────────────
def test_tc40_per_model_aggregation(tmp_path: Path) -> None:
    from harness.report import generate_report

    output_dir = tmp_path / "outputs"
    # 模型 A：2 个 run，全部 format=diff
    _write_run_grade(output_dir, "model-a", "t1", 0, output_format="diff", latency=2.0)
    _write_run_grade(output_dir, "model-a", "t1", 1, output_format="diff", latency=4.0)
    # 模型 B：2 个 run，1 个 diff、1 个 none → 合规率 50%
    _write_run_grade(output_dir, "model-b", "t1", 0, output_format="diff", latency=1.0)
    _write_run_grade(output_dir, "model-b", "t1", 1, output_format="none", latency=3.0)

    report_path = tmp_path / "reports" / "report.md"
    generate_report(output_dir=output_dir, report_path=report_path)
    text = report_path.read_text(encoding="utf-8")

    assert "model-a" in text and "model-b" in text
    # 合规率应保留 2 位小数
    assert "50.00" in text or "50.0%" in text or "0.50" in text


# ──────────────────────────────────────────────
# TC-41：失败附录列出每个失败 run 的 verify_log_tail
# ──────────────────────────────────────────────
def test_tc41_failures_appendix(tmp_path: Path) -> None:
    from harness.report import generate_report

    output_dir = tmp_path / "outputs"
    _write_run_grade(
        output_dir, "model-a", "fix-01", 0,
        diff_applies=False, tests_pass=None,
        verify_log_tail="UNIQUE_FAIL_TOKEN_42",
    )
    _write_run_grade(
        output_dir, "model-a", "fix-01", 1,
        diff_applies=True, tests_pass=False,
        verify_log_tail="ASSERTION_FAIL_99",
    )

    report_path = tmp_path / "reports" / "report.md"
    generate_report(output_dir=output_dir, report_path=report_path)
    text = report_path.read_text(encoding="utf-8")
    assert "UNIQUE_FAIL_TOKEN_42" in text
    assert "ASSERTION_FAIL_99" in text


# ──────────────────────────────────────────────
# TC-42：tests_pass=null 不计入分母
# ──────────────────────────────────────────────
def test_tc42_null_tests_pass_excluded_from_pass_rate(tmp_path: Path) -> None:
    from harness.report import generate_report

    output_dir = tmp_path / "outputs"
    # 4 个 run：1 pass / 1 fail / 2 null → 通过率应为 1/2 = 50%（不含 null）
    _write_run_grade(output_dir, "model-x", "t1", 0, tests_pass=True)
    _write_run_grade(output_dir, "model-x", "t1", 1, tests_pass=False)
    _write_run_grade(output_dir, "model-x", "t1", 2, tests_pass=None)
    _write_run_grade(output_dir, "model-x", "t1", 3, tests_pass=None)

    report_path = tmp_path / "reports" / "report.md"
    generate_report(output_dir=output_dir, report_path=report_path)
    text = report_path.read_text(encoding="utf-8")
    # 50% 通过率（精确格式由实现决定）
    assert "50" in text


# ──────────────────────────────────────────────
# TC-43：按 task_id 前缀（fix-/refactor-/feature-）聚合
# ──────────────────────────────────────────────
def test_tc43_aggregate_by_task_prefix(tmp_path: Path) -> None:
    from harness.report import generate_report

    output_dir = tmp_path / "outputs"
    _write_run_grade(output_dir, "m", "fix-001", 0)
    _write_run_grade(output_dir, "m", "refactor-002", 0)
    _write_run_grade(output_dir, "m", "feature-003", 0)

    report_path = tmp_path / "reports" / "report.md"
    generate_report(output_dir=output_dir, report_path=report_path)
    text = report_path.read_text(encoding="utf-8")
    assert "fix" in text
    assert "refactor" in text
    assert "feature" in text
