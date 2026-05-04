"""TC-94：taskprep → harness 端到端测试。

Phase 2 /gen-test 阶段新建。taskprep 模块尚未实现，导入会失败——预期在 /implement 后转绿。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.conftest import (
    FixtureRepo,
    _git,
    make_anthropic_message,
    make_openai_completion,
)

SEVEN_SECTIONS = ["目标", "当前行为", "复现步骤", "错误信息", "期望行为", "验收标准", "约束"]


def test_tc94_e2e_taskprep_to_harness(
    tmp_path: Path,
    make_repo,
    monkeypatch: pytest.MonkeyPatch,
    mock_taskprep_anthropic: MagicMock,
    mock_openai: MagicMock,
) -> None:
    """完整链路：taskprep draft → 去 .draft → harness all → 验证输出。"""
    # ── 准备 ──
    repo = make_repo()

    # debug doc
    debug_doc = tmp_path / "debug-doc.md"
    debug_doc.write_text(
        "# 调试文档\n\n## 现象\n\nadd(1,2) 返回 -1\n\n"
        "## 复现步骤\n\n运行 python -c \"from src.a import add; print(add(1,2))\"\n\n"
        "## 错误信息\n\n无\n\n## 约束\n\n不修改签名\n",
        encoding="utf-8",
    )

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()

    # mock taskprep LLM（3 次调用）
    mock_taskprep_anthropic.messages.create.side_effect = [
        make_anthropic_message("\n".join(f"# {s}\n\nmock" for s in SEVEN_SECTIONS)),
        make_anthropic_message("src/b.ts\n\n# --- LLM Recommendation Notes ---\n# note"),
        make_anthropic_message(
            "--- a/tests/test_add.py\n+++ b/tests/test_add.py\n"
            "@@ -0,0 +1,4 @@\n+from src.a import add\n+\n+def test_add():\n+    assert add(1, 2) == 3\n"
        ),
    ]

    # ── Step 1: taskprep draft ──
    monkeypatch.chdir(tmp_path)
    from taskprep.cli import main as taskprep_main

    exit_code = taskprep_main([
        "draft",
        "--repo-url", f"file://{repo.path.as_posix()}",
        "--commit", repo.fix_commit,
        "--local-repo", str(repo.path),
        "--debug-doc", str(debug_doc),
        "--task-id", "e2e-fix",
        "--output-dir", str(tasks_dir),
        "--skip-sanity",
    ])
    assert exit_code == 0

    task_dir = tasks_dir / "e2e-fix"
    assert task_dir / "meta.json" in task_dir.iterdir()
    assert task_dir / "reference.diff" in task_dir.iterdir()
    assert task_dir / "prompt.md.draft" in task_dir.iterdir()
    assert task_dir / "target_files.txt.draft" in task_dir.iterdir()
    assert task_dir / "test_patch.diff.draft" in task_dir.iterdir()
    assert task_dir / "verify.sh.draft" in task_dir.iterdir()

    # ── Step 2: 去 .draft（模拟人工审核）──
    for f in list(task_dir.iterdir()):
        if f.suffix == ".draft":
            f.rename(f.with_suffix(""))

    assert (task_dir / "prompt.md").exists()
    assert (task_dir / "target_files.txt").exists()
    assert (task_dir / "test_patch.diff").exists()
    assert (task_dir / "verify.sh").exists()
    assert not any(f.suffix == ".draft" for f in task_dir.iterdir())

    # 补全 meta.json 可能缺失的字段（repo_url, base_commit）
    meta = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
    meta.setdefault("repo_url", f"file://{repo.path.as_posix()}")
    meta.setdefault("base_commit", repo.init_commit)
    (task_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # ── Step 3: harness all ──
    # mock harness runner LLM
    mock_openai.chat.completions.create.return_value = make_openai_completion(
        "```diff\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n```"
    )

    from harness.cli import main as harness_main

    exit_code = harness_main([
        "all",
        "--models", "deepseek-v4-pro",
        "--tasks-dir", str(tasks_dir),
        "--output-dir", str(outputs_dir),
        "--reports-dir", str(reports_dir),
        "--repos-dir", str(tmp_path / "repos"),
    ])
    assert exit_code == 0

    # ── Step 4: 验证输出 ──
    run_json = outputs_dir / "deepseek-v4-pro" / "e2e-fix" / "run_0.json"
    assert run_json.exists(), f"missing {run_json}"
    grade_json = outputs_dir / "deepseek-v4-pro" / "e2e-fix" / "grade_0.json"
    assert grade_json.exists(), f"missing {grade_json}"
    report_md = reports_dir / "report.md"
    assert report_md.exists(), f"missing {report_md}"
    report_text = report_md.read_text(encoding="utf-8")
    assert "e2e-fix" in report_text

    # ── Step 5: 幂等回放 ──
    call_count_before = mock_openai.messages.create.call_count
    exit_code = harness_main([
        "run",
        "--models", "deepseek-v4-pro",
        "--tasks-dir", str(tasks_dir),
        "--output-dir", str(outputs_dir),
    ])
    assert exit_code == 0
    # 幂等：没有新的 SDK 调用
    assert mock_openai.messages.create.call_count == call_count_before
