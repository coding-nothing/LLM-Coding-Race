"""run_sanity_check — worktree 隔离验证 test_patch + reference.diff。

复用 harness.grader._isolated_worktree，保证 worktree 在任何路径下被清理（AC-INV-2）。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harness.grader import _isolated_worktree

GRADE_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class SanityResult:
    test_fails_on_base: bool
    test_passes_on_fix: bool
    log_base: str
    log_fix: str
    verdict: Literal["TRUSTWORTHY", "RED_FLAG", "SKIP"]


def _apply_patch(wt: Path, patch_path: Path) -> None:
    subprocess.run(
        ["git", "-C", str(wt), "apply", str(patch_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _run_verify(wt: Path, verify_path: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["bash", str(verify_path), str(wt)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GRADE_TIMEOUT_SECONDS,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_sanity_check(
    repo_path: Path,
    base_commit: str,
    test_patch_path: Path,
    reference_diff_path: Path,
    verify_sh_path: Path,
) -> SanityResult:
    if not verify_sh_path.exists():
        return SanityResult(
            test_fails_on_base=False,
            test_passes_on_fix=False,
            log_base="",
            log_fix="",
            verdict="SKIP",
        )

    # ── 检查 1：仅 apply test_patch，期望 verify 失败 ──
    try:
        with _isolated_worktree(repo_path, base_commit) as wt:
            _apply_patch(wt, test_patch_path)
            rc1, log1 = _run_verify(wt, verify_sh_path)
    except subprocess.CalledProcessError as e:
        return SanityResult(
            test_fails_on_base=False,
            test_passes_on_fix=False,
            log_base=(e.stderr or "") + (e.stdout or ""),
            log_fix="",
            verdict="SKIP",
        )

    # ── 检查 2：apply test_patch + reference.diff，期望 verify 通过 ──
    try:
        with _isolated_worktree(repo_path, base_commit) as wt:
            _apply_patch(wt, test_patch_path)
            _apply_patch(wt, reference_diff_path)
            rc2, log2 = _run_verify(wt, verify_sh_path)
    except subprocess.CalledProcessError as e:
        return SanityResult(
            test_fails_on_base=rc1 != 0,
            test_passes_on_fix=False,
            log_base=log1,
            log_fix=(e.stderr or "") + (e.stdout or ""),
            verdict="SKIP",
        )

    fails_on_base = rc1 != 0
    passes_on_fix = rc2 == 0
    verdict: Literal["TRUSTWORTHY", "RED_FLAG", "SKIP"]
    if fails_on_base and passes_on_fix:
        verdict = "TRUSTWORTHY"
    else:
        verdict = "RED_FLAG"

    return SanityResult(
        test_fails_on_base=fails_on_base,
        test_passes_on_fix=passes_on_fix,
        log_base=log1,
        log_fix=log2,
        verdict=verdict,
    )
