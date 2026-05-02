"""TC-51 ~ TC-72：taskprep（Project A）测试 — 占位 skip。

PRD §C1 要求"先 Phase 1（harness）后 Phase 2（taskprep）"，所以此处仅占位
保留 TC 编号体系完整性。Phase 2 启动前把这些 skip 改为真实测试即可。

每条 skip 的 reason 含对应 TC ID 与 PRD §A11 引用，便于审计。
"""

from __future__ import annotations

import pytest

PHASE_2_SKIP_REASON = (
    "Phase 2（taskprep）尚未启动；按 PRD §C1，B 完成 ship 后再补此用例。"
)


# ──────────────────────────────────────────────
# git_ops 相关
# ──────────────────────────────────────────────
@pytest.mark.skip(reason=f"TC-51 — {PHASE_2_SKIP_REASON}")
def test_tc51_show_diff_excludes_tests() -> None:
    """`git_ops.show_diff(commit, include_tests=False)` 输出 diff 不含测试文件。"""


@pytest.mark.skip(reason=f"TC-52 — {PHASE_2_SKIP_REASON}")
def test_tc52_show_diff_includes_tests_when_flag() -> None:
    """`include_tests=True` → diff 含测试文件。"""


@pytest.mark.skip(reason=f"TC-53 — {PHASE_2_SKIP_REASON}")
def test_tc53_changed_files_excludes_tests() -> None:
    """`changed_files(commit, exclude_tests=True)` 不含测试文件路径。"""


# ──────────────────────────────────────────────
# llm 相关
# ──────────────────────────────────────────────
@pytest.mark.skip(reason=f"TC-54 — {PHASE_2_SKIP_REASON}")
def test_tc54_llm_call_retries_on_failure() -> None:
    """`taskprep.llm.call` 前 2 次失败、第 3 次成功。"""


@pytest.mark.skip(reason=f"TC-55 — {PHASE_2_SKIP_REASON}")
def test_tc55_llm_call_dispatches_by_provider() -> None:
    """LLMConfig 指向 anthropic / openai_compat 时分别走对应 SDK。"""


# ──────────────────────────────────────────────
# generators
# ──────────────────────────────────────────────
@pytest.mark.skip(reason=f"TC-56 — {PHASE_2_SKIP_REASON}")
def test_tc56_generate_prompt_writes_seven_sections() -> None:
    """`generate_prompt` 写入 prompt.md.draft，含 7 个 section；缺失标 [需要补充]。"""


@pytest.mark.skip(reason=f"TC-57 — {PHASE_2_SKIP_REASON}")
def test_tc57_generate_target_files_main_section() -> None:
    """`generate_target_files` main: 段路径与 git show --name-only 一致并去除测试。"""


@pytest.mark.skip(reason=f"TC-58 — {PHASE_2_SKIP_REASON}")
def test_tc58_generate_target_files_reference_recommendations() -> None:
    """reference: 段含 LLM 推荐 1-3 项 + 末尾 `# --- LLM Recommendation Notes ---`。"""


@pytest.mark.skip(reason=f"TC-59 — {PHASE_2_SKIP_REASON}")
def test_tc59_generate_test_patch_returns_applicable_diff() -> None:
    """`generate_test_patch` 输出能被 `git apply --check` 接受。"""


@pytest.mark.skip(reason=f"TC-60 — {PHASE_2_SKIP_REASON}")
def test_tc60_generate_test_patch_marks_failure() -> None:
    """LLM 两次返回非 diff → 输出标 [GENERATION_FAILED]，原始输出保留。"""


@pytest.mark.skip(reason=f"TC-61 — {PHASE_2_SKIP_REASON}")
def test_tc61_generate_verify_for_vitest() -> None:
    """vitest 项目 → verify.sh 含 set -e / cd "$1" / pnpm install / pnpm test。"""


@pytest.mark.skip(reason=f"TC-62 — {PHASE_2_SKIP_REASON}")
def test_tc62_generate_verify_unknown_framework() -> None:
    """unknown 框架 → verify.sh 含 [需要人工填写] 占位。"""


# ──────────────────────────────────────────────
# sanity
# ──────────────────────────────────────────────
@pytest.mark.skip(reason=f"TC-63 — {PHASE_2_SKIP_REASON}")
def test_tc63_sanity_check_trustworthy() -> None:
    """正确 reference.diff → verdict=TRUSTWORTHY。"""


@pytest.mark.skip(reason=f"TC-64 — {PHASE_2_SKIP_REASON}")
def test_tc64_sanity_check_red_flag() -> None:
    """改坏 reference.diff → verdict=RED_FLAG（check 2 失败）。"""


@pytest.mark.skip(reason=f"TC-65 — {PHASE_2_SKIP_REASON}")
def test_tc65_sanity_check_skip_when_no_verify() -> None:
    """无 verify.sh → verdict=SKIP。"""


@pytest.mark.skip(reason=f"TC-66 — {PHASE_2_SKIP_REASON}")
def test_tc66_sanity_check_worktree_cleaned_on_exception() -> None:
    """sanity 中途 raise → worktree 被清理（AC-INV-2）。"""


# ──────────────────────────────────────────────
# checklist
# ──────────────────────────────────────────────
@pytest.mark.skip(reason=f"TC-67 — {PHASE_2_SKIP_REASON}")
def test_tc67_generate_checklist_items() -> None:
    """`generate_checklist` 输出含每个产物的 checkbox。"""


@pytest.mark.skip(reason=f"TC-68 — {PHASE_2_SKIP_REASON}")
def test_tc68_generate_checklist_red_flag_highlighted() -> None:
    """RED_FLAG 在 _review_checklist.md 顶部高亮。"""


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
@pytest.mark.skip(reason=f"TC-69 — {PHASE_2_SKIP_REASON}")
def test_tc69_cli_draft_produces_all_files() -> None:
    """`taskprep cli draft` → tasks/<id>/ 下出现全部规约文件，.draft 后缀齐全。"""


@pytest.mark.skip(reason=f"TC-70 — {PHASE_2_SKIP_REASON}")
def test_tc70_cli_regen_only_target() -> None:
    """`cli regen --target test_patch` 仅覆盖 test_patch.diff.draft，其他 mtime 不变。"""


@pytest.mark.skip(reason=f"TC-71 — {PHASE_2_SKIP_REASON}")
def test_tc71_cli_check_reruns_sanity() -> None:
    """`cli check` 重跑 sanity 并更新 checklist。"""


@pytest.mark.skip(reason=f"TC-72 — {PHASE_2_SKIP_REASON}")
def test_tc72_cli_status_lists_tasks() -> None:
    """`cli status` 列出每个任务及其 .draft 状态。"""
