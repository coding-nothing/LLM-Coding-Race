"""TC-51 ~ TC-72：taskprep（Project A）集成/单元测试。

Phase 2 /gen-test 阶段：所有 skip 已移除，补全真实断言。
taskprep 模块尚未实现，导入会失败——预期在 /implement 后转绿。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.conftest import FixtureRepo, SampleTask, make_anthropic_message, make_openai_completion


# ══════════════════════════════════════════════
# git_ops
# ══════════════════════════════════════════════


def test_tc51_show_diff_excludes_tests(make_repo) -> None:
    """`git_ops.show_diff(commit, include_tests=False)` 输出 diff 不含测试文件。"""
    from taskprep.git_ops import show_diff

    repo = make_repo()
    diff = show_diff(repo.path, repo.fix_commit, include_tests=False)
    assert "tests/" not in diff
    assert "test_a.py" not in diff
    assert "src/a.py" in diff


def test_tc52_show_diff_includes_tests_when_flag(make_repo) -> None:
    """`include_tests=True` → diff 含测试文件。"""
    from taskprep.git_ops import show_diff

    repo = make_repo()
    diff = show_diff(repo.path, repo.fix_commit, include_tests=True)
    assert "tests/test_a.py" in diff


def test_tc53_changed_files_excludes_tests(make_repo) -> None:
    """`changed_files(commit, exclude_tests=True)` 不含测试文件路径。"""
    from taskprep.git_ops import changed_files

    repo = make_repo()
    files = changed_files(repo.path, repo.fix_commit, exclude_tests=True)
    assert any("tests/" in f or "test_" in f for f in files) is False
    assert any("src/a.py" in f for f in files)


# ══════════════════════════════════════════════
# llm
# ══════════════════════════════════════════════


def test_tc54_llm_call_retries_on_failure(
    mock_taskprep_anthropic: MagicMock, fast_sleep: list[float]
) -> None:
    """`taskprep.llm.call` 前 2 次失败、第 3 次成功；sleep 顺序 [2, 4]。"""
    from taskprep.llm import LLMConfig, call

    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")
    mock_taskprep_anthropic.messages.create.side_effect = [
        RuntimeError("fail 1"),
        RuntimeError("fail 2"),
        make_anthropic_message("success", input_tokens=200, output_tokens=80),
    ]

    result = call(cfg, "sys", "usr")
    assert result == "success"
    assert mock_taskprep_anthropic.messages.create.call_count == 3
    assert fast_sleep == [2, 4]


def test_tc55_llm_call_dispatches_by_provider(
    mock_taskprep_anthropic: MagicMock,
    mock_taskprep_openai: MagicMock,
) -> None:
    """LLMConfig 指向 anthropic / openai_compat 时分别走对应 SDK。"""
    from taskprep.llm import LLMConfig, call

    # anthropic
    cfg_anthro = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY", provider="anthropic")
    mock_taskprep_anthropic.messages.create.return_value = make_anthropic_message("anthro")
    assert call(cfg_anthro, "sys", "usr") == "anthro"
    mock_taskprep_anthropic.messages.create.assert_called_once()

    # openai_compat
    cfg_openai = LLMConfig(
        model_id="deepseek-v4-pro",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        provider="openai_compat",
    )
    mock_taskprep_openai.chat.completions.create.return_value = make_openai_completion("openai")
    assert call(cfg_openai, "sys", "usr") == "openai"
    mock_taskprep_openai.chat.completions.create.assert_called_once()

    # assert openai 客户端收到 base_url
    mock_taskprep_openai._factory.assert_called_once()
    _, kwargs = mock_taskprep_openai._factory.call_args
    assert kwargs.get("base_url") == "https://api.deepseek.com"


# ══════════════════════════════════════════════
# generators/prompt
# ══════════════════════════════════════════════

SEVEN_SECTIONS = ["目标", "当前行为", "复现步骤", "错误信息", "期望行为", "验收标准", "约束"]


def test_tc56_generate_prompt_writes_seven_sections(
    tmp_path: Path, debug_doc_sample: Path, mock_taskprep_anthropic: MagicMock
) -> None:
    """`generate_prompt` 写入 prompt.md.draft，含 7 个 section；缺失标 [需要补充]。"""
    from taskprep.generators.prompt import generate_prompt
    from taskprep.llm import LLMConfig

    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")
    full_text = debug_doc_sample.read_text(encoding="utf-8")

    # 构造含全部 7 段的 LLM 响应
    mock_taskprep_anthropic.messages.create.return_value = make_anthropic_message(
        "\n".join(f"# {s}\n\nmock content for {s}" for s in SEVEN_SECTIONS)
    )

    result = generate_prompt(full_text, "fix: repair add function", cfg)
    assert isinstance(result, str)
    for section in SEVEN_SECTIONS:
        assert section in result, f"缺少 section: {section}"


def test_tc57_generate_target_files_main_section(make_repo) -> None:
    """`generate_target_files` main: 段路径与 git show --name-only 一致并去除测试。"""
    from taskprep.git_ops import changed_files
    from taskprep.generators.target_files import generate_target_files
    from taskprep.llm import LLMConfig

    repo = make_repo()
    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")

    result = generate_target_files(repo.path, repo.fix_commit, cfg)

    # main: 段
    assert "main:" in result
    changed = changed_files(repo.path, repo.fix_commit, exclude_tests=True)
    for f in changed:
        assert f in result


def test_tc58_generate_target_files_reference_recommendations(
    make_repo, mock_taskprep_anthropic: MagicMock
) -> None:
    """reference: 段含 LLM 推荐 1-3 项 + 末尾 `# --- LLM Recommendation Notes ---`。"""
    from taskprep.generators.target_files import generate_target_files
    from taskprep.llm import LLMConfig

    repo = make_repo()
    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")

    mock_taskprep_anthropic.messages.create.return_value = make_anthropic_message(
        "src/b.ts\nsrc/utils/helpers.ts\n\n# --- LLM Recommendation Notes (please review) ---\n"
        "# src/b.ts: 与 src/a.py 同目录，是最近的参考文件\n"
    )

    result = generate_target_files(repo.path, repo.fix_commit, cfg)

    assert "reference:" in result
    assert "tree:" in result
    assert "# --- LLM Recommendation Notes" in result


def test_tc59_generate_test_patch_returns_applicable_diff(
    tmp_path: Path, make_repo, mock_taskprep_anthropic: MagicMock
) -> None:
    """`generate_test_patch` 输出能被 `git apply --check` 接受。"""
    from taskprep.generators.test_patch import generate_test_patch
    from taskprep.llm import LLMConfig

    repo = make_repo()
    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")

    valid_diff = (
        "--- a/tests/test_add.py\n"
        "+++ b/tests/test_add.py\n"
        "@@ -0,0 +1,4 @@\n"
        "+from src.a import add\n"
        "+\n"
        "+def test_add():\n"
        "+    assert add(1, 2) == 3\n"
    )
    mock_taskprep_anthropic.messages.create.return_value = make_anthropic_message(valid_diff)

    result = generate_test_patch(
        debug_doc="bug: add returns a-b",
        reference_diff="diff --git a/src/a.py ...",
        main_files_content={"src/a.py": "def add(a, b):\n    return a - b\n"},
        similar_test_samples=[],
        project_test_framework="pytest",
        llm=cfg,
    )

    # 写入临时文件，用 git apply --check 验证
    patch_file = tmp_path / "test.patch"
    patch_file.write_text(result, encoding="utf-8")
    checkout = subprocess.run(
        ["git", "-C", str(repo.path), "checkout", repo.fix_commit],
        capture_output=True, text=True,
    )
    # 如果 checkout 失败（可能已在 fix_commit），忽略
    r = subprocess.run(
        ["git", "-C", str(repo.path), "apply", "--check", str(patch_file)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"git apply --check failed: {r.stderr}"


def test_tc60_generate_test_patch_marks_failure(
    mock_taskprep_anthropic: MagicMock,
) -> None:
    """LLM 两次返回非 diff → 输出标 [GENERATION_FAILED]，原始输出保留。"""
    from taskprep.generators.test_patch import generate_test_patch
    from taskprep.llm import LLMConfig

    cfg = LLMConfig(model_id="claude-opus-4-7", api_key_env="ANTHROPIC_API_KEY")
    prose = "Here is a nice test you should write..."
    mock_taskprep_anthropic.messages.create.return_value = make_anthropic_message(prose)

    result = generate_test_patch(
        debug_doc="bug: add returns a-b",
        reference_diff="diff --git a/src/a.py ...",
        main_files_content={"src/a.py": "def add(a, b):\n    return a - b\n"},
        similar_test_samples=[],
        project_test_framework="pytest",
        llm=cfg,
    )

    assert "[GENERATION_FAILED]" in result
    assert prose in result
    assert mock_taskprep_anthropic.messages.create.call_count == 2


def test_tc61_generate_verify_for_vitest() -> None:
    """vitest 项目 → verify.sh 含 set -e / cd "$1" / pnpm install / pnpm test。"""
    from taskprep.generators.verify import generate_verify

    result = generate_verify("vitest", ["tests/foo.test.ts"], llm=None)
    assert "set -e" in result
    assert 'cd "$1"' in result
    assert "pnpm install" in result
    assert "pnpm test" in result
    assert "tests/foo.test.ts" in result


def test_tc62_generate_verify_unknown_framework() -> None:
    """unknown 框架 → verify.sh 含 [需要人工填写] 占位。"""
    from taskprep.generators.verify import generate_verify

    result = generate_verify("unknown", [], llm=None)
    assert "[需要人工填写]" in result


# ══════════════════════════════════════════════
# sanity
# ══════════════════════════════════════════════


def test_tc63_sanity_check_trustworthy(sample_task: SampleTask) -> None:
    """正确 reference.diff → verdict=TRUSTWORTHY；test_fails_on_base=True；test_passes_on_fix=True。"""
    from taskprep.sanity import run_sanity_check

    t = sample_task
    result = run_sanity_check(
        repo_path=t.repo.path,
        base_commit=t.repo.init_commit,
        test_patch_path=t.task_dir / "test_patch.diff",
        reference_diff_path=t.task_dir / "reference.diff",
        verify_sh_path=t.task_dir / "verify.sh",
    )
    assert result.verdict == "TRUSTWORTHY"
    assert result.test_fails_on_base is True
    assert result.test_passes_on_fix is True


def test_tc64_sanity_check_red_flag(sample_task: SampleTask) -> None:
    """改坏 reference.diff → verdict=RED_FLAG（check 2 失败）。"""
    from taskprep.sanity import run_sanity_check

    t = sample_task
    # 写入一个无效的 reference.diff（修改无关变量名）
    bad_ref = t.task_dir / "reference.diff.broken"
    bad_ref.write_text(
        "diff --git a/src/a.py b/src/a.py\n"
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a - b  # bug\n"
        "+    return a * b  # wrong fix\n",
        encoding="utf-8",
    )

    result = run_sanity_check(
        repo_path=t.repo.path,
        base_commit=t.repo.init_commit,
        test_patch_path=t.task_dir / "test_patch.diff",
        reference_diff_path=bad_ref,
        verify_sh_path=t.task_dir / "verify.sh",
    )
    assert result.verdict == "RED_FLAG"


def test_tc65_sanity_check_skip_when_no_verify(sample_task: SampleTask) -> None:
    """无 verify.sh → verdict=SKIP。"""
    from taskprep.sanity import run_sanity_check

    t = sample_task
    nonexistent = t.task_dir / "nonexistent_verify.sh"
    result = run_sanity_check(
        repo_path=t.repo.path,
        base_commit=t.repo.init_commit,
        test_patch_path=t.task_dir / "test_patch.diff",
        reference_diff_path=t.task_dir / "reference.diff",
        verify_sh_path=nonexistent,
    )
    assert result.verdict == "SKIP"


def test_tc66_sanity_check_worktree_cleaned_on_exception(
    sample_task: SampleTask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sanity 中途 raise → worktree 被清理（AC-INV-2）。"""
    from taskprep.sanity import run_sanity_check
    import subprocess as sp_mod

    t = sample_task

    # 在 _isolated_worktree 的 subprocess.run 第二次调用时抛异常
    orig_run = sp_mod.run
    call_count = [0]

    def _failing_run(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 3:  # 在 _run_verify 时抛异常（check 1 的 verify 调用）
            raise RuntimeError("injected error for TC-66")
        return orig_run(*args, **kwargs)

    monkeypatch.setattr(sp_mod, "run", _failing_run)

    with pytest.raises((RuntimeError, Exception)):
        run_sanity_check(
            repo_path=t.repo.path,
            base_commit=t.repo.init_commit,
            test_patch_path=t.task_dir / "test_patch.diff",
            reference_diff_path=t.task_dir / "reference.diff",
            verify_sh_path=t.task_dir / "verify.sh",
        )

    # worktree 不应残留（只应剩主仓库一行）
    wt_list = subprocess.run(
        ["git", "-C", str(t.repo.path), "worktree", "list"],
        capture_output=True, text=True,
    ).stdout
    wt_lines = [l for l in wt_list.splitlines() if l.strip()]
    assert len(wt_lines) == 1, f"expected 1 worktree, got {len(wt_lines)}: {wt_lines}"


# ══════════════════════════════════════════════
# checklist
# ══════════════════════════════════════════════


def test_tc67_generate_checklist_items(tmp_path: Path) -> None:
    """`generate_checklist` 输出含每个产物的 checkbox。"""
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

    result = generate_checklist(task_dir, sanity, red_flags=[], info_notes=[])
    assert "- [ ]" in result
    for product in ["prompt.md", "target_files.txt", "test_patch.diff", "verify.sh"]:
        assert product in result, f"checklist 缺少 {product}"


def test_tc68_generate_checklist_red_flag_highlighted(tmp_path: Path) -> None:
    """RED_FLAG 在 _review_checklist.md 顶部高亮。"""
    from taskprep.checklist import generate_checklist
    from taskprep.sanity import SanityResult

    task_dir = tmp_path / "tasks" / "test-fix"
    task_dir.mkdir(parents=True)
    sanity = SanityResult(
        test_fails_on_base=False,
        test_passes_on_fix=False,
        log_base="...",
        log_fix="...",
        verdict="RED_FLAG",
    )

    result = generate_checklist(task_dir, sanity, red_flags=["bad ref"], info_notes=[])
    assert "RED_FLAG" in result
    assert "⚠️" in result
    # RED_FLAG 应在顶部附近（前 200 字符内）
    assert "RED_FLAG" in result[:200]


# ══════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════


def test_tc69_cli_draft_produces_all_files(
    tmp_path: Path,
    make_repo,
    debug_doc_sample: Path,
    mock_taskprep_anthropic: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`taskprep cli draft` → tasks/<id>/ 下出现全部规约文件，.draft 后缀齐全。"""
    from taskprep.cli import main

    repo = make_repo()
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # mock 3 个 LLM 调用（prompt / target_files / test_patch）按序返回
    mock_taskprep_anthropic.messages.create.side_effect = [
        make_anthropic_message(
            "\n".join(f"# {s}\n\nmock" for s in SEVEN_SECTIONS)
        ),
        make_anthropic_message("src/b.ts\n\n# --- LLM Recommendation Notes ---\n# note"),
        make_anthropic_message(
            "--- a/tests/test_add.py\n+++ b/tests/test_add.py\n"
            "@@ -0,0 +1,4 @@\n+from src.a import add\n+\n+def test_add():\n+    assert add(1, 2) == 3\n"
        ),
    ]

    monkeypatch.chdir(tmp_path)
    exit_code = main([
        "draft",
        "--repo-url", f"file://{repo.path.as_posix()}",
        "--commit", repo.fix_commit,
        "--local-repo", str(repo.path),
        "--debug-doc", str(debug_doc_sample),
        "--task-id", "e2e-fix",
        "--output-dir", str(tasks_dir),
        "--skip-sanity",
    ])
    assert exit_code == 0

    task_dir = tasks_dir / "e2e-fix"
    # 无 .draft 后缀文件
    assert (task_dir / "meta.json").exists()
    assert (task_dir / "reference.diff").exists()
    assert (task_dir / "debug-doc.md").exists()
    # .draft 后缀文件
    assert (task_dir / "prompt.md.draft").exists()
    assert (task_dir / "target_files.txt.draft").exists()
    assert (task_dir / "test_patch.diff.draft").exists()
    assert (task_dir / "verify.sh.draft").exists()
    # checklist
    assert (task_dir / "_review_checklist.md").exists()


def test_tc70_cli_regen_only_target(
    tmp_path: Path,
    make_repo,
    debug_doc_sample: Path,
    mock_taskprep_anthropic: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cli regen --target test_patch` 仅覆盖 test_patch.diff.draft，其他 mtime 不变。"""
    from taskprep.cli import main

    repo = make_repo()
    tasks_dir = tmp_path / "tasks"

    mock_taskprep_anthropic.messages.create.side_effect = [
        make_anthropic_message("\n".join(f"# {s}\n\nmock" for s in SEVEN_SECTIONS)),
        make_anthropic_message("src/b.ts\n\n# --- LLM Recommendation Notes ---\n# note"),
        make_anthropic_message(
            "--- a/tests/test_add.py\n+++ b/tests/test_add.py\n"
            "@@ -0,0 +1,4 @@\n+from src.a import add\n+\n+def test_add():\n+    assert add(1, 2) == 3\n"
        ),
    ]

    monkeypatch.chdir(tmp_path)
    main([
        "draft", "--repo-url", f"file://{repo.path.as_posix()}",
        "--commit", repo.fix_commit, "--local-repo", str(repo.path),
        "--debug-doc", str(debug_doc_sample), "--task-id", "e2e-fix",
        "--output-dir", str(tasks_dir), "--skip-sanity",
    ])

    task_dir = tasks_dir / "e2e-fix"
    # 记录 mtime
    mt_before = {
        p.name: p.stat().st_mtime_ns
        for p in task_dir.iterdir()
        if p.suffix == ".draft"
    }

    # 追加 mock 供 regen 用（合法 diff，一次即通过）
    mock_taskprep_anthropic.messages.create.side_effect = [
        make_anthropic_message(
            "--- a/tests/test_new.py\n"
            "+++ b/tests/test_new.py\n"
            "@@ -0,0 +1,4 @@\n"
            "+from src.a import add\n"
            "+\n"
            "+def test_new():\n"
            "+    assert add(0, 0) == 0\n"
        ),
    ]
    main(["regen", "--task-id", "e2e-fix", "--target", "test_patch",
          "--output-dir", str(tasks_dir)])

    # test_patch.diff.draft mtime 应变
    assert task_dir / "test_patch.diff.draft" in task_dir.iterdir()
    new_mt = (task_dir / "test_patch.diff.draft").stat().st_mtime_ns
    assert new_mt != mt_before["test_patch.diff.draft"]

    # 其他 .draft 文件 mtime 不变
    for f in task_dir.iterdir():
        if f.suffix == ".draft" and f.name != "test_patch.diff.draft":
            assert f.stat().st_mtime_ns == mt_before[f.name], f"{f.name} mtime 不应变"


def test_tc71_cli_check_reruns_sanity(
    tmp_path: Path,
    make_repo,
    debug_doc_sample: Path,
    mock_taskprep_anthropic: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cli check` 重跑 sanity 并更新 checklist。"""
    from taskprep.cli import main

    repo = make_repo()
    tasks_dir = tmp_path / "tasks"

    mock_taskprep_anthropic.messages.create.side_effect = [
        make_anthropic_message("\n".join(f"# {s}\n\nmock" for s in SEVEN_SECTIONS)),
        make_anthropic_message("src/b.ts\n\n# --- LLM Recommendation Notes ---\n# note"),
        make_anthropic_message(
            "--- a/tests/test_add.py\n+++ b/tests/test_add.py\n"
            "@@ -0,0 +1,4 @@\n+from src.a import add\n+\n+def test_add():\n+    assert add(1, 2) == 3\n"
        ),
    ]

    monkeypatch.chdir(tmp_path)
    main([
        "draft", "--repo-url", f"file://{repo.path.as_posix()}",
        "--commit", repo.fix_commit, "--local-repo", str(repo.path),
        "--debug-doc", str(debug_doc_sample), "--task-id", "e2e-fix",
        "--output-dir", str(tasks_dir), "--skip-sanity",
    ])

    task_dir = tasks_dir / "e2e-fix"
    checklist = task_dir / "_review_checklist.md"
    mt_before = checklist.stat().st_mtime_ns

    main(["check", "--task-id", "e2e-fix", "--output-dir", str(tasks_dir)])

    mt_after = checklist.stat().st_mtime_ns
    assert mt_after != mt_before
    content = checklist.read_text(encoding="utf-8")
    assert "TRUSTWORTHY" in content or "RED_FLAG" in content or "SKIP" in content


def test_tc72_cli_status_lists_tasks(tmp_path: Path, capsys) -> None:
    """`cli status` 列出每个任务及其 .draft 状态。"""
    from taskprep.cli import main

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 创建含 .draft 文件的任务
    draft_task = tasks_dir / "task-draft"
    draft_task.mkdir()
    (draft_task / "prompt.md.draft").write_text("draft", encoding="utf-8")
    (draft_task / "meta.json").write_text("{}", encoding="utf-8")

    # 创建无 .draft 文件的任务
    ready_task = tasks_dir / "task-ready"
    ready_task.mkdir()
    (ready_task / "prompt.md").write_text("ready", encoding="utf-8")
    (ready_task / "meta.json").write_text("{}", encoding="utf-8")

    exit_code = main(["status", "--output-dir", str(tasks_dir)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "task-draft" in captured.out
    assert "task-ready" in captured.out
    assert "draft" in captured.out.lower()
