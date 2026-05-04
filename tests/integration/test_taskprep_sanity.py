"""TC-89：taskprep sanity 集成测试。

Phase 2 /gen-test 阶段新建。taskprep 模块尚未实现，导入会失败——预期在 /implement 后转绿。
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import SampleTask, _git


# ── TC-89：test_patch apply 失败 → SKIP ──


def test_tc89_sanity_skip_on_test_patch_conflict(sample_task: SampleTask) -> None:
    """构造一个与仓库冲突的 test_patch → `git apply` 失败 → verdict=SKIP。"""
    from taskprep.sanity import run_sanity_check

    t = sample_task

    # 写入一个不可能 apply 的 test_patch（修改不存在的文件）
    bad_patch = t.task_dir / "test_patch.bad.diff"
    bad_patch.write_text(
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -50,6 +50,6 @@\n"
        " def add(a, b):\n"
        "-    return a - b\n"
        "+    return a + b\n",
        encoding="utf-8",
    )

    result = run_sanity_check(
        repo_path=t.repo.path,
        base_commit=t.repo.init_commit,
        test_patch_path=bad_patch,
        reference_diff_path=t.task_dir / "reference.diff",
        verify_sh_path=t.task_dir / "verify.sh",
    )
    assert result.verdict == "SKIP"
    # log_base 应有 git apply 的 stderr 信息
    assert len(result.log_base) > 0
