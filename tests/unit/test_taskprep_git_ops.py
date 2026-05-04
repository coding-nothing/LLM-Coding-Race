"""TC-74 ~ TC-79：taskprep git_ops 单元测试。

Phase 2 /gen-test 阶段新建。taskprep 模块尚未实现，导入会失败——预期在 /implement 后转绿。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import FixtureRepo, _git


# ── TC-74：resolve_base_commit 返回父 commit ──


def test_tc74_resolve_base_commit_returns_parent(make_repo) -> None:
    """`resolve_base_commit(repo, fix_commit)` 返回 init_commit 完整 hash（== fix_commit^）。"""
    from taskprep.git_ops import resolve_base_commit

    repo = make_repo()
    result = resolve_base_commit(repo.path, repo.fix_commit)
    assert result == repo.init_commit
    assert len(result) == 40


# ── TC-75：首个 commit 无父 → 抛错 ──


def test_tc75_resolve_base_commit_raises_on_first_commit(make_repo) -> None:
    """`resolve_base_commit(repo, init_commit)` 抛 RuntimeError（首个 commit 无父）。"""
    from taskprep.git_ops import resolve_base_commit

    repo = make_repo()
    with pytest.raises(RuntimeError):
        resolve_base_commit(repo.path, repo.init_commit)


# ── TC-76：merge commit → 返回 first-parent ──


def test_tc76_resolve_base_commit_merge_first_parent(make_repo_with_merge) -> None:
    """`resolve_base_commit(repo, merge_commit)` 返回 main 侧父 commit（first-parent）。"""
    from taskprep.git_ops import resolve_base_commit

    repo = make_repo_with_merge()
    result = resolve_base_commit(repo.path, repo.fix_commit)
    # first-parent 应该是 main 侧，即 init_commit
    assert result == repo.init_commit


# ── TC-77：detect_test_framework → vitest ──


def test_tc77_detect_test_framework_vitest(make_repo_with_manifest) -> None:
    """package.json 含 vitest devDep → 返回 "vitest"。"""
    from taskprep.git_ops import detect_test_framework

    repo = make_repo_with_manifest(manifest="package.json", name="repo_vitest")
    result = detect_test_framework(repo.path)
    assert result == "vitest"


# ── TC-78：detect_test_framework → pytest ──


def test_tc78_detect_test_framework_pytest(make_repo_with_manifest) -> None:
    """pyproject.toml 含 [tool.pytest.ini_options] → 返回 "pytest"。"""
    from taskprep.git_ops import detect_test_framework

    repo = make_repo_with_manifest(manifest="pyproject.toml", name="repo_pytest")
    result = detect_test_framework(repo.path)
    assert result == "pytest"


# ── TC-79：detect_test_framework → unknown ──


def test_tc79_detect_test_framework_unknown(make_repo) -> None:
    """仓库无任何 manifest → 返回 "unknown"。"""
    from taskprep.git_ops import detect_test_framework

    repo = make_repo()
    result = detect_test_framework(repo.path)
    assert result == "unknown"
