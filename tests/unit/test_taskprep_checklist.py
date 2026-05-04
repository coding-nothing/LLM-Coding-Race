"""TC-90：taskprep checklist 单元测试。

Phase 2 /gen-test 阶段新建。taskprep 模块尚未实现，导入会失败——预期在 /implement 后转绿。
"""

from __future__ import annotations

from pathlib import Path


# ── TC-90：checklist 含 info_notes ──


def test_tc90_generate_checklist_info_notes(tmp_path: Path) -> None:
    """`info_notes=["相似测试样本数=0"]` → 输出含 INFO 段。"""
    from taskprep.checklist import generate_checklist
    from taskprep.sanity import SanityResult

    task_dir = tmp_path / "tasks" / "test-fix"
    task_dir.mkdir(parents=True)
    sanity = SanityResult(
        test_fails_on_base=True,
        test_passes_on_fix=True,
        log_base="FAILED",
        log_fix="PASSED",
        verdict="TRUSTWORTHY",
    )

    result = generate_checklist(
        task_dir, sanity,
        red_flags=[],
        info_notes=["相似测试样本数=0"],
    )
    assert "相似测试样本数=0" in result
