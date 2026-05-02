"""汇总 outputs/<model>/<task>/ 下的 run+grade JSON，输出 markdown 报告。

报告结构（PRD §B4.6 + Coding Plan §决策5）：
- 总览表：每条 (task, model, run) 的 format / diff_applies / tests_pass / 延迟
- 按模型聚合：平均延迟、总 token、输出格式合规率（保留 2 位小数）、tests pass rate
- 按任务前缀聚合：取 task_id 第一个 '-' 前段
- 失败附录：列出每个 diff_applies=false 或 tests_pass=false 的 run + verify_log_tail
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_runs(output_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not output_dir.exists():
        return rows
    for model_dir in sorted(p for p in output_dir.iterdir() if p.is_dir()):
        for task_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
            for run_file in sorted(task_dir.glob("run_*.json")):
                try:
                    run = json.loads(run_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                idx = run.get("run_index", 0)
                grade_file = task_dir / f"grade_{idx}.json"
                grade: dict[str, Any] = {}
                if grade_file.is_file():
                    try:
                        grade = json.loads(grade_file.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        grade = {}
                usage = run.get("usage") or {}
                rows.append(
                    {
                        "model": model_dir.name,
                        "task": task_dir.name,
                        "run_index": idx,
                        "output_format": run.get("output_format", "none"),
                        "latency": float(run.get("latency_seconds") or 0),
                        "input_tokens": int(usage.get("input_tokens") or 0),
                        "output_tokens": int(usage.get("output_tokens") or 0),
                        "diff_applies": grade.get("diff_applies"),
                        "tests_pass": grade.get("tests_pass"),
                        "verify_log_tail": grade.get("verify_log_tail"),
                        "error": run.get("error"),
                    }
                )
    return rows


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return "—"
    return "✓" if value else "✗"


def _task_prefix(task_id: str) -> str:
    if "-" in task_id:
        return task_id.split("-", 1)[0]
    return task_id


def generate_report(output_dir: Path, report_path: Path) -> None:
    output_dir = Path(output_dir)
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    rows = _load_runs(output_dir)
    lines: list[str] = ["# 评测报告", ""]

    # 总览表
    lines.append("## 总览")
    lines.append("")
    lines.append(
        "| Task | Model | Run | Format | Diff Applies | Tests Pass | Latency (s) | "
        "Input Tokens | Output Tokens |"
    )
    lines.append(
        "|------|-------|-----|--------|--------------|------------|-------------|"
        "--------------|----------------|"
    )
    for r in rows:
        lines.append(
            f"| {r['task']} | {r['model']} | {r['run_index']} | {r['output_format']} | "
            f"{_fmt_bool(r['diff_applies'])} | {_fmt_bool(r['tests_pass'])} | "
            f"{r['latency']:.2f} | {r['input_tokens']} | {r['output_tokens']} |"
        )
    lines.append("")

    # 按模型聚合
    lines.append("## 按模型聚合")
    lines.append("")
    lines.append(
        "| Model | Runs | Avg Latency (s) | Total Input Tokens | Total Output Tokens | "
        "Format Compliance | Tests Pass Rate |"
    )
    lines.append(
        "|-------|------|-----------------|--------------------|---------------------|"
        "-------------------|------------------|"
    )
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    for model, items in sorted(by_model.items()):
        n = len(items)
        avg_lat = sum(i["latency"] for i in items) / n if n else 0.0
        total_in = sum(i["input_tokens"] for i in items)
        total_out = sum(i["output_tokens"] for i in items)
        compliant = sum(1 for i in items if i["output_format"] != "none")
        compl_pct = (compliant / n) * 100 if n else 0.0
        tested = [i["tests_pass"] for i in items if i["tests_pass"] is not None]
        if tested:
            pass_rate = (sum(1 for t in tested if t) / len(tested)) * 100
            pass_str = f"{pass_rate:.2f}%"
        else:
            pass_str = "—"
        lines.append(
            f"| {model} | {n} | {avg_lat:.2f} | {total_in} | {total_out} | "
            f"{compl_pct:.2f}% | {pass_str} |"
        )
    lines.append("")

    # 按任务前缀聚合
    lines.append("## 按任务前缀聚合")
    lines.append("")
    lines.append("| Prefix | Runs | Tests Pass Rate |")
    lines.append("|--------|------|-----------------|")
    by_prefix: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_prefix[_task_prefix(r["task"])].append(r)
    for prefix, items in sorted(by_prefix.items()):
        tested = [i["tests_pass"] for i in items if i["tests_pass"] is not None]
        if tested:
            pass_rate = (sum(1 for t in tested if t) / len(tested)) * 100
            pass_str = f"{pass_rate:.2f}%"
        else:
            pass_str = "—"
        lines.append(f"| {prefix} | {len(items)} | {pass_str} |")
    lines.append("")

    # 失败附录
    failures = [
        r for r in rows
        if r["diff_applies"] is False or r["tests_pass"] is False or r.get("error")
    ]
    if failures:
        lines.append("## 失败附录")
        lines.append("")
        for r in failures:
            lines.append(
                f"### {r['task']} / {r['model']} / run {r['run_index']}"
            )
            lines.append("")
            lines.append(f"- diff_applies: {_fmt_bool(r['diff_applies'])}")
            lines.append(f"- tests_pass: {_fmt_bool(r['tests_pass'])}")
            if r.get("error"):
                lines.append(f"- error: `{r['error']}`")
            tail = r.get("verify_log_tail")
            if tail:
                lines.append("")
                lines.append("```")
                lines.append(str(tail))
                lines.append("```")
            lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
