"""git worktree 隔离 + apply test_patch + apply 模型 diff + 跑 verify.sh。

不变量（PRD §B4.5 / Coding Plan）：
- _isolated_worktree 用 contextmanager 保证 worktree 在任意路径下被清理。
- diff apply 失败时 diff_applies=false, tests_pass=null（跳过 verify）。
- 任务无 test_patch 或无 verify.sh 时 tests_pass=null, verify_log_tail=null。
- verify.sh 超时 → tests_pass=false, verify_log_tail 含 'timeout'。
- verify_log_tail 截断到 4000 字符。
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

from harness import config as _config

# 模块级常量（测试通过 monkeypatch 直接改本模块属性来调小超时）
GRADE_TIMEOUT_SECONDS: int = _config.GRADE_TIMEOUT_SECONDS
_LOG_TAIL_BYTES = 4000


@contextlib.contextmanager
def _isolated_worktree(repo_path: Path, base_commit: str) -> Iterator[Path]:
    repo_path = Path(repo_path).resolve()
    worktrees_dir = repo_path / ".worktrees"
    worktrees_dir.mkdir(exist_ok=True)
    wt_path = worktrees_dir / f"wt_{uuid.uuid4().hex[:8]}"

    subprocess.run(
        [
            "git", "-C", str(repo_path),
            "worktree", "add", "--detach", str(wt_path), base_commit,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        yield wt_path
    finally:
        subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(wt_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)
        subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "prune"],
            check=False,
            capture_output=True,
            text=True,
        )


def _apply_patch(wt: Path, patch_text: str) -> bool:
    patch_text = patch_text.replace("\r\n", "\n").replace("\r", "\n")
    if not patch_text.endswith("\n"):
        patch_text += "\n"
    patch_file = wt / ".patch_tmp.diff"
    patch_file.write_text(patch_text, encoding="utf-8")
    try:
        result = subprocess.run(
            ["git", "-C", str(wt), "apply", "--whitespace=nowarn", str(patch_file)],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    finally:
        try:
            patch_file.unlink()
        except OSError:
            pass


def _apply_required_patch(wt: Path, patch_path: Path) -> None:
    text = patch_path.read_text(encoding="utf-8")
    if not _apply_patch(wt, text):
        raise RuntimeError(
            f"任务必备 patch 无法在 base 上应用：{patch_path}"
        )


def _truncate_tail(text: str) -> str:
    if len(text) <= _LOG_TAIL_BYTES:
        return text
    return text[-_LOG_TAIL_BYTES:]


def grade_run(run_json_path: Path, task_dir: Path, repo_path: Path) -> None:
    run_json_path = Path(run_json_path)
    task_dir = Path(task_dir)
    repo_path = Path(repo_path)

    run_data = json.loads(run_json_path.read_text(encoding="utf-8"))
    extracted_diff = (run_data.get("extracted_diff") or "").strip()
    run_index = run_data.get("run_index", 0)

    meta_path = task_dir / "meta.json"
    base_commit = "HEAD"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            base_commit = meta.get("base_commit") or "HEAD"
        except (OSError, json.JSONDecodeError):
            pass

    test_patch_path = task_dir / "test_patch.diff"
    verify_path = task_dir / "verify.sh"
    has_test_patch = (
        test_patch_path.is_file()
        and test_patch_path.read_text(encoding="utf-8").strip() != ""
    )
    has_verify = verify_path.is_file()

    diff_applies = False
    tests_pass: bool | None = None
    verify_log_tail: str | None = None

    with _isolated_worktree(repo_path, base_commit) as wt:
        if has_test_patch:
            _apply_required_patch(wt, test_patch_path)

        if extracted_diff:
            diff_applies = _apply_patch(wt, extracted_diff)

        if diff_applies and has_test_patch and has_verify:
            try:
                proc = subprocess.run(
                    ["bash", str(verify_path), str(wt)],
                    capture_output=True,
                    text=True,
                    timeout=GRADE_TIMEOUT_SECONDS,
                )
                tests_pass = proc.returncode == 0
                combined = (proc.stdout or "") + (proc.stderr or "")
                verify_log_tail = _truncate_tail(combined)
            except subprocess.TimeoutExpired as exc:
                tests_pass = False
                stdout = _decode(exc.stdout)
                stderr = _decode(exc.stderr)
                tail = (
                    f"timeout after {GRADE_TIMEOUT_SECONDS}s\n{stdout}{stderr}"
                )
                verify_log_tail = _truncate_tail(tail)

    grade = {
        "diff_applies": diff_applies,
        "tests_pass": tests_pass,
        "verify_log_tail": verify_log_tail,
        "human_scores": {
            "correctness": None,
            "code_quality": None,
            "context_awareness": None,
        },
        "human_notes": None,
    }
    grade_path = run_json_path.parent / f"grade_{run_index}.json"
    grade_path.write_text(
        json.dumps(grade, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _decode(payload: object) -> str:
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return str(payload)


def grade_all(
    output_dir: Path, tasks_dir: Path, repo_paths: dict[str, Path]
) -> None:
    output_dir = Path(output_dir)
    tasks_dir = Path(tasks_dir)
    if not output_dir.exists():
        return

    for model_dir in sorted(p for p in output_dir.iterdir() if p.is_dir()):
        for task_dir_out in sorted(p for p in model_dir.iterdir() if p.is_dir()):
            task_id = task_dir_out.name
            task_def = tasks_dir / task_id
            repo_path = repo_paths.get(task_id)
            if not task_def.exists() or repo_path is None:
                continue
            for run_file in sorted(task_dir_out.glob("run_*.json")):
                try:
                    idx = int(run_file.stem.split("_", 1)[1])
                except (IndexError, ValueError):
                    continue
                grade_path = task_dir_out / f"grade_{idx}.json"
                if grade_path.exists():
                    continue
                grade_run(run_file, task_def, repo_path)
