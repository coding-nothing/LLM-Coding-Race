"""argparse 命令行入口：fetch / run / grade / report / all。

启动检查（PRD §B7.7）：
- 扫描 tasks_dir 下任何 .draft 文件 → 警告并退出非 0；--allow-drafts 跳过此检查
- run / all 在调用前检查所选模型的 API key 是否在环境变量中
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from harness.config import (
    MODELS,
    RUNS_PER_TASK,
    ModelConfig,
    load_dotenv,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="clone 仓库到 dest-root")
    p_fetch.add_argument("--repo", default=None, help="repo URL")
    p_fetch.add_argument("--ref", default=None, help="commit / branch / tag")
    p_fetch.add_argument("--task", default=None, help="task id（从 meta.json 读 repo+ref）")
    p_fetch.add_argument("--tasks-dir", default="tasks")
    p_fetch.add_argument("--dest-root", default="repos")

    for name in ("run", "grade", "report", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("--models", default="", help="逗号分隔模型 name 列表，留空=全部")
        sp.add_argument("--tasks", default="", help="逗号分隔 task_id，留空=全部")
        sp.add_argument("--tasks-dir", default="tasks")
        sp.add_argument("--output-dir", default="outputs")
        sp.add_argument("--repos-dir", default="repos")
        sp.add_argument("--reports-dir", default="reports")
        sp.add_argument(
            "--repo-path",
            action="append",
            default=[],
            help="task_id=path 形式的覆盖；用来在测试或自定义场景下绕过 fetch",
        )
        sp.add_argument("--runs", type=int, default=RUNS_PER_TASK)
        sp.add_argument("--allow-drafts", action="store_true")

    args = parser.parse_args(argv)
    load_dotenv(Path.cwd())

    if args.cmd == "fetch":
        return _cmd_fetch(args)

    selected_models = _select_models(args.models)
    if not selected_models:
        print("❌ 没有匹配的模型可执行", file=sys.stderr)
        return 6

    if args.cmd in ("run", "all"):
        missing = [m for m in selected_models if not os.environ.get(m.api_key_env)]
        if missing:
            for m in missing:
                print(
                    f"❌ 缺少 API key 环境变量 {m.api_key_env}（模型 {m.name}）",
                    file=sys.stderr,
                )
            return 2

    tasks_dir = Path(args.tasks_dir)
    drafts: list[Path] = []
    if tasks_dir.exists():
        drafts = sorted(tasks_dir.rglob("*.draft"))
    if drafts:
        print(
            f"⚠️  draft warning: 检测到 {len(drafts)} 个 .draft 文件（任务尚未审核完成）",
            file=sys.stderr,
        )
        for f in drafts[:5]:
            print(f"   - {f}", file=sys.stderr)
        if not args.allow_drafts:
            print(
                "❌ 拒绝执行；通过 --allow-drafts 跳过此检查（不推荐）",
                file=sys.stderr,
            )
            return 3

    selected_tasks = [t.strip() for t in args.tasks.split(",") if t.strip()] or None
    repo_paths = _parse_repo_paths(args.repo_path)

    if args.cmd == "run":
        return _cmd_run(args, selected_models, selected_tasks, repo_paths)
    if args.cmd == "grade":
        return _cmd_grade(args, selected_tasks, repo_paths)
    if args.cmd == "report":
        return _cmd_report(args)
    if args.cmd == "all":
        rc = _cmd_run(args, selected_models, selected_tasks, repo_paths)
        if rc != 0:
            return rc
        rc = _cmd_grade(args, selected_tasks, repo_paths)
        if rc != 0:
            return rc
        return _cmd_report(args)
    return 0


def _select_models(spec: str) -> list[ModelConfig]:
    if not spec:
        return list(MODELS)
    wanted = {s.strip() for s in spec.split(",") if s.strip()}
    return [m for m in MODELS if m.name in wanted]


def _parse_repo_paths(items: list[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for item in items:
        if "=" not in item:
            continue
        task, _, path = item.partition("=")
        task = task.strip()
        path = path.strip()
        if task and path:
            out[task] = Path(path)
    return out


def _cmd_fetch(args: argparse.Namespace) -> int:
    from harness.fetch import clone_repo

    dest_root = Path(args.dest_root)
    if args.task:
        meta_path = Path(args.tasks_dir) / args.task / "meta.json"
        if not meta_path.is_file():
            print(f"❌ 找不到 {meta_path}", file=sys.stderr)
            return 4
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"❌ meta.json 解析失败：{exc}", file=sys.stderr)
            return 4
        repo_url = meta.get("repo_url")
        ref = meta.get("base_commit")
        if not repo_url or not ref:
            print("❌ meta.json 缺少 repo_url 或 base_commit", file=sys.stderr)
            return 4
        path = clone_repo(repo_url, ref, dest_root)
        print(str(path))
        return 0

    if args.repo and args.ref:
        path = clone_repo(args.repo, args.ref, dest_root)
        print(str(path))
        return 0

    print("❌ fetch 需要 --repo+--ref 或 --task", file=sys.stderr)
    return 5


def _resolve_repo_paths(
    args: argparse.Namespace,
    selected_tasks: list[str] | None,
    repo_paths: dict[str, Path],
) -> dict[str, Path]:
    """对 selected_tasks 中尚未在 repo_paths 里的 task，按 meta.json 自动 fetch。"""
    from harness.fetch import clone_repo

    tasks_dir = Path(args.tasks_dir)
    if not tasks_dir.exists():
        return repo_paths

    candidate_tasks: list[str] = []
    for d in tasks_dir.iterdir():
        if not d.is_dir():
            continue
        if selected_tasks and d.name not in selected_tasks:
            continue
        candidate_tasks.append(d.name)

    repos_dir = Path(args.repos_dir)
    for task_id in candidate_tasks:
        if task_id in repo_paths:
            continue
        meta_path = tasks_dir / task_id / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        url = meta.get("repo_url")
        ref = meta.get("base_commit")
        if not url or not ref:
            continue
        repo_paths[task_id] = clone_repo(url, ref, repos_dir)
    return repo_paths


def _cmd_run(
    args: argparse.Namespace,
    models: list[ModelConfig],
    selected_tasks: list[str] | None,
    repo_paths: dict[str, Path],
) -> int:
    from harness.runner import run_all

    repo_paths = _resolve_repo_paths(args, selected_tasks, dict(repo_paths))

    run_all(
        tasks_dir=Path(args.tasks_dir),
        repo_paths=repo_paths,
        output_dir=Path(args.output_dir),
        models=models,
        runs=args.runs,
    )
    return 0


def _cmd_grade(
    args: argparse.Namespace,
    selected_tasks: list[str] | None,
    repo_paths: dict[str, Path],
) -> int:
    from harness.grader import grade_all

    repo_paths = _resolve_repo_paths(args, selected_tasks, dict(repo_paths))
    grade_all(
        output_dir=Path(args.output_dir),
        tasks_dir=Path(args.tasks_dir),
        repo_paths=repo_paths,
    )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from harness.report import generate_report

    report_path = Path(args.reports_dir) / "report.md"
    generate_report(
        output_dir=Path(args.output_dir),
        report_path=report_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
