"""taskprep CLI — draft / regen / check / status 四个子命令。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from taskprep.checklist import generate_checklist
from taskprep.generators.prompt import generate_prompt
from taskprep.generators.target_files import generate_target_files
from taskprep.generators.test_patch import generate_test_patch
from taskprep.generators.verify import generate_verify
from taskprep.git_ops import (
    changed_files,
    detect_test_framework,
    find_similar_tests,
    resolve_base_commit,
    show_diff,
)
from taskprep.llm import DEFAULT_DRAFT_MODEL, LLMConfig, call
from taskprep.sanity import run_sanity_check


def _resolve_model(model_id: str) -> LLMConfig:
    """根据 model_id 查找对应配置。默认返回 DEFAULT_DRAFT_MODEL。"""
    from harness.config import MODELS

    for m in MODELS:
        if m.model_id == model_id:
            return LLMConfig(
                model_id=m.model_id,
                api_key_env=m.api_key_env,
                base_url=m.base_url,
                provider=m.provider,
            )
    return DEFAULT_DRAFT_MODEL


def _check_api_key(cfg: LLMConfig) -> None:
    if cfg.api_key_env not in os.environ:
        print(f"错误：缺少环境变量 {cfg.api_key_env}，请先设置 API key。", file=sys.stderr)
        sys.exit(1)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cmd_draft(args: argparse.Namespace) -> int:
    local_repo = Path(args.local_repo)
    if not (local_repo / ".git").exists():
        print(f"错误：{local_repo} 不是 git 仓库", file=sys.stderr)
        return 1

    try:
        subprocess.run(
            ["git", "-C", str(local_repo), "rev-parse", args.commit],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError:
        print(f"错误：commit {args.commit} 不存在", file=sys.stderr)
        return 1

    llm = _resolve_model(args.draft_model)
    try:
        _check_api_key(llm)
    except SystemExit:
        return 1

    try:
        base_commit = resolve_base_commit(local_repo, args.commit)
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    task_dir = Path(args.output_dir) / args.task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # 获取 commit message
    try:
        commit_msg = subprocess.run(
            ["git", "-C", str(local_repo), "log", "-1", "--format=%s", args.commit],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        commit_msg = args.commit

    red_flags: list[str] = []
    info_notes: list[str] = []

    # ── [1/6] 直接产物（无 .draft）──
    print("[1/6] 生成 reference.diff ...")
    ref_diff = show_diff(local_repo, args.commit, include_tests=args.include_tests_in_reference)
    ref_path = task_dir / "reference.diff"
    ref_path.write_text(ref_diff, encoding="utf-8")

    debug_doc_src = Path(args.debug_doc)
    debug_doc_text = debug_doc_src.read_text(encoding="utf-8")
    dest_debug = task_dir / "debug-doc.md"
    shutil.copyfile(debug_doc_src, dest_debug)

    meta = {
        "task_id": args.task_id,
        "repo_url": args.repo_url,
        "base_commit": base_commit,
        "source_commit": args.commit,
        "draft_generator": {
            "model": llm.model_id,
            "version": "1.0",
            "input_files": {
                "debug_doc_sha256": _sha256(debug_doc_src),
                "reference_diff_sha256": _sha256(ref_path),
            },
        },
    }
    (task_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── [2/6] prompt.md.draft ──
    print("[2/6] 生成 prompt.md.draft ...")
    try:
        prompt_text = generate_prompt(debug_doc_text, commit_msg, llm)
        (task_dir / "prompt.md.draft").write_text(prompt_text, encoding="utf-8")
    except RuntimeError as e:
        red_flags.append(f"prompt 生成失败：{e}")
        (task_dir / "prompt.md.draft").write_text(
            f"# [GENERATION_FAILED]\n\n{e}", encoding="utf-8"
        )

    # ── [3/6] target_files.txt.draft ──
    print("[3/6] 生成 target_files.txt.draft ...")
    try:
        target_text = generate_target_files(local_repo, args.commit, llm)
        (task_dir / "target_files.txt.draft").write_text(target_text, encoding="utf-8")
    except RuntimeError as e:
        red_flags.append(f"target_files 生成失败：{e}")

    # ── [4/6] test_patch.diff.draft ──
    print("[4/6] 生成 test_patch.diff.draft ...")
    try:
        main_files = changed_files(local_repo, args.commit, exclude_tests=True)
        main_content = {}
        for mf in main_files:
            fpath = local_repo / mf
            if fpath.exists():
                main_content[mf] = fpath.read_text(encoding="utf-8")

        framework = detect_test_framework(local_repo)
        samples = find_similar_tests(local_repo, main_files, max_samples=3)
        info_notes.append(f"测试框架={framework}，相似测试样本数={len(samples)}")

        test_patch_text = generate_test_patch(
            debug_doc=debug_doc_text,
            reference_diff=ref_diff,
            main_files_content=main_content,
            similar_test_samples=samples,
            project_test_framework=framework,
            llm=llm,
        )
        (task_dir / "test_patch.diff.draft").write_text(test_patch_text, encoding="utf-8")
    except RuntimeError as e:
        red_flags.append(f"test_patch 生成失败：{e}")

    # ── [5/6] verify.sh.draft ──
    print("[5/6] 生成 verify.sh.draft ...")
    try:
        framework = detect_test_framework(local_repo)
        test_paths = [
            f for f in changed_files(local_repo, args.commit, exclude_tests=False)
            if _is_testish(f)
        ]
        verify_text = generate_verify(framework, test_paths, llm=None)
        (task_dir / "verify.sh.draft").write_text(verify_text, encoding="utf-8")
    except RuntimeError as e:
        red_flags.append(f"verify 生成失败：{e}")

    # ── [6/6] sanity + checklist ──
    sanity_result = None
    if not args.skip_sanity and (task_dir / "verify.sh.draft").exists():
        print("[6/6] 运行 sanity check ...")
        test_patch_draft = task_dir / "test_patch.diff.draft"
        verify_draft = task_dir / "verify.sh.draft"
        if test_patch_draft.exists() and verify_draft.exists():
            sanity_result = run_sanity_check(
                repo_path=local_repo,
                base_commit=base_commit,
                test_patch_path=test_patch_draft,
                reference_diff_path=ref_path,
                verify_sh_path=verify_draft,
            )
    else:
        print("[6/6] 跳过 sanity check")

    if sanity_result is None:
        from taskprep.sanity import SanityResult
        sanity_result = SanityResult(
            test_fails_on_base=False,
            test_passes_on_fix=False,
            log_base="",
            log_fix="",
            verdict="SKIP",
        )

    checklist_text = generate_checklist(task_dir, sanity_result, red_flags, info_notes)
    (task_dir / "_review_checklist.md").write_text(checklist_text, encoding="utf-8")

    print(f"任务 {args.task_id} 草稿生成完毕 → {task_dir}")
    return 0


def _is_testish(path: str) -> bool:
    name = Path(path).name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def _cmd_regen(args: argparse.Namespace) -> int:
    task_dir = Path(args.output_dir) / args.task_id
    if not task_dir.exists():
        print(f"错误：任务目录 {task_dir} 不存在", file=sys.stderr)
        return 1

    llm = _resolve_model(args.draft_model)
    try:
        _check_api_key(llm)
    except SystemExit:
        return 1

    meta = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
    debug_doc_text = (task_dir / "debug-doc.md").read_text(encoding="utf-8")
    commit_msg = meta.get("source_commit", meta.get("task_id", ""))
    ref_diff = (task_dir / "reference.diff").read_text(encoding="utf-8")

    target = args.target
    if target == "prompt":
        text = generate_prompt(debug_doc_text, commit_msg, llm)
        (task_dir / "prompt.md.draft").write_text(text, encoding="utf-8")
        print(f"已重新生成 prompt.md.draft")
    elif target == "target_files":
        local_repo = Path(meta.get("repo_url", "").replace("file://", ""))
        text = generate_target_files(local_repo, meta.get("source_commit", ""), llm)
        (task_dir / "target_files.txt.draft").write_text(text, encoding="utf-8")
        print(f"已重新生成 target_files.txt.draft")
    elif target == "test_patch":
        local_repo = Path(meta.get("repo_url", "").replace("file://", ""))
        main_files = changed_files(local_repo, meta.get("source_commit", ""), exclude_tests=True)
        main_content = {}
        for mf in main_files:
            fpath = local_repo / mf
            if fpath.exists():
                main_content[mf] = fpath.read_text(encoding="utf-8")
        framework = detect_test_framework(local_repo)
        samples = find_similar_tests(local_repo, main_files, max_samples=3)
        text = generate_test_patch(
            debug_doc=debug_doc_text,
            reference_diff=ref_diff,
            main_files_content=main_content,
            similar_test_samples=samples,
            project_test_framework=framework,
            llm=llm,
        )
        (task_dir / "test_patch.diff.draft").write_text(text, encoding="utf-8")
        print(f"已重新生成 test_patch.diff.draft")
    elif target == "verify":
        local_repo = Path(meta.get("repo_url", "").replace("file://", ""))
        framework = detect_test_framework(local_repo)
        test_paths = [
            f for f in changed_files(local_repo, meta.get("source_commit", ""), exclude_tests=False)
            if _is_testish(f)
        ]
        text = generate_verify(framework, test_paths, llm=None)
        (task_dir / "verify.sh.draft").write_text(text, encoding="utf-8")
        print(f"已重新生成 verify.sh.draft")

    # 更新 meta.json version
    meta.setdefault("draft_generator", {})["version"] = "1.0"
    (task_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    task_dir = Path(args.output_dir) / args.task_id
    if not task_dir.exists():
        print(f"错误：任务目录 {task_dir} 不存在", file=sys.stderr)
        return 1

    meta = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
    base_commit = meta["base_commit"]
    repo_url = meta.get("repo_url", "")
    local_repo = Path(repo_url.replace("file://", ""))

    test_patch_path = task_dir / "test_patch.diff.draft"
    verify_path = task_dir / "verify.sh.draft"
    ref_path = task_dir / "reference.diff"

    sanity_result = run_sanity_check(
        repo_path=local_repo,
        base_commit=base_commit,
        test_patch_path=test_patch_path,
        reference_diff_path=ref_path,
        verify_sh_path=verify_path,
    )

    red_flags: list[str] = []
    info_notes: list[str] = []
    checklist_text = generate_checklist(task_dir, sanity_result, red_flags, info_notes)
    (task_dir / "_review_checklist.md").write_text(checklist_text, encoding="utf-8")

    print(f"sanity 结果：{sanity_result.verdict}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print("没有任务目录。")
        return 0

    for task_dir in sorted(output_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        meta_file = task_dir / "meta.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        task_id = meta.get("task_id", task_dir.name)
        drafts = list(task_dir.glob("*.draft"))
        status = "draft" if drafts else "ready"
        print(f"{task_id:30s}  {status}  ({len(drafts)} .draft 文件)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="taskprep", description="taskprep — LLM 编码评测任务草稿生成器"
    )
    sub = parser.add_subparsers(dest="command")

    # draft
    d = sub.add_parser("draft", help="从 debug doc 生成完整任务草稿")
    d.add_argument("--repo-url", required=True)
    d.add_argument("--commit", required=True)
    d.add_argument("--local-repo", required=True)
    d.add_argument("--debug-doc", required=True)
    d.add_argument("--task-id", required=True)
    d.add_argument("--draft-model", default=DEFAULT_DRAFT_MODEL.model_id)
    d.add_argument("--output-dir", default="tasks")
    d.add_argument("--include-tests-in-reference", action="store_true")
    d.add_argument("--skip-sanity", action="store_true")

    # regen
    r = sub.add_parser("regen", help="重新生成单个产物")
    r.add_argument("--task-id", required=True)
    r.add_argument("--target", required=True,
                   choices=["test_patch", "prompt", "target_files", "verify"])
    r.add_argument("--output-dir", default="tasks")
    r.add_argument("--draft-model", default=DEFAULT_DRAFT_MODEL.model_id)

    # check
    c = sub.add_parser("check", help="重新运行 sanity check 并更新 checklist")
    c.add_argument("--task-id", required=True)
    c.add_argument("--output-dir", default="tasks")

    # status
    s = sub.add_parser("status", help="列出所有任务及其 .draft 状态")
    s.add_argument("--output-dir", default="tasks")

    args = parser.parse_args(argv)

    if args.command == "draft":
        return _cmd_draft(args)
    elif args.command == "regen":
        return _cmd_regen(args)
    elif args.command == "check":
        return _cmd_check(args)
    elif args.command == "status":
        _cmd_status(args)
        return 0
    else:
        parser.print_help()
        return 1
