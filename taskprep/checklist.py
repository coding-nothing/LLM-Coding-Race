"""generate_checklist — 生成 _review_checklist.md。"""

from __future__ import annotations

from pathlib import Path

from taskprep.sanity import SanityResult


def generate_checklist(
    task_dir: Path,
    sanity: SanityResult,
    red_flags: list[str],
    info_notes: list[str],
) -> str:
    lines: list[str] = []

    # RED_FLAG 顶部高亮
    if sanity.verdict == "RED_FLAG" or red_flags:
        lines.append("## ⚠️ RED_FLAG 警告")
        lines.append("")
        if sanity.verdict == "RED_FLAG":
            lines.append("sanity check 判定为 RED_FLAG：测试补丁可能存在问题，请仔细审核。")
        for rf in red_flags:
            lines.append(f"- {rf}")
        lines.append("")

    # 产物 checklist
    lines.append("## 产物审核清单")
    lines.append("")
    lines.append("请逐项审核以下产物，确认无误后勾选：")
    lines.append("")

    products = [
        ("prompt.md", "任务描述是否清晰、7 个 section 是否完整"),
        ("target_files.txt", "目标文件列表是否准确、参考文件是否有价值"),
        ("test_patch.diff", "测试补丁是否合理、是否覆盖核心场景"),
        ("verify.sh", "验证脚本是否可执行、框架命令是否正确"),
    ]

    for name, desc in products:
        lines.append(f"- [ ] **{name}** — {desc}")

    lines.append("")

    # INFO 段
    if info_notes:
        lines.append("## INFO")
        lines.append("")
        for note in info_notes:
            lines.append(f"- {note}")
        lines.append("")

    # Sanity 结果
    lines.append("## Sanity Check 结果")
    lines.append("")
    lines.append(f"- 判定：**{sanity.verdict}**")
    lines.append(f"- 测试在 base commit 上失败：{'是' if sanity.test_fails_on_base else '否'}")
    lines.append(f"- 测试在 fix commit 上通过：{'是' if sanity.test_passes_on_fix else '否'}")
    lines.append("")

    # 操作步骤
    lines.append("## 完成审核后的操作步骤")
    lines.append("")
    lines.append("1. 确认所有产物无误后，移除 `.draft` 后缀：")
    lines.append("   ```bash")
    lines.append("   for f in *.draft; do mv \"$f\" \"${f%.draft}\"; done")
    lines.append("   ```")
    lines.append("2. 删除本审核清单：")
    lines.append("   ```bash")
    lines.append("   rm _review_checklist.md")
    lines.append("   ```")

    return "\n".join(lines) + "\n"
