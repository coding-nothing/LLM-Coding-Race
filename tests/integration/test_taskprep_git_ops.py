"""TC-80 ~ TC-81：taskprep git_ops 集成测试。

Phase 2 /gen-test 阶段新建。taskprep 模块尚未实现，导入会失败——预期在 /implement 后转绿。
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import FixtureRepo, _git


# ── TC-80：find_similar_tests 按最近修改排序 ──


def test_tc80_find_similar_tests_returns_recent(tmp_path: Path, make_repo) -> None:
    """fixture 仓库（main_files 邻近多个测试文件）→ 返回最多 3 个，最近修改优先。"""
    from taskprep.git_ops import find_similar_tests

    repo = make_repo(name="repo_similar")

    # 在 fix commit 上额外创建多个测试文件
    _git(repo.path, "checkout", "-q", repo.fix_commit)

    (repo.path / "tests" / "test_a.py").write_text("import pytest\n", encoding="utf-8")
    (repo.path / "tests" / "test_b.py").write_text("import pytest\n", encoding="utf-8")
    (repo.path / "tests" / "test_c.py").write_text("import pytest\n", encoding="utf-8")
    (repo.path / "tests" / "test_d.py").write_text("import pytest\n", encoding="utf-8")
    _git(repo.path, "add", "-A")
    _git(repo.path, "commit", "-q", "-m", "add more tests")

    results = find_similar_tests(repo.path, ["src/a.py"], max_samples=3)
    assert isinstance(results, list)
    assert len(results) <= 3
    assert len(results) >= 1  # 至少能找到 test_a.py
    for path, content in results:
        assert isinstance(path, str)
        assert isinstance(content, str)
        assert path.endswith(".py")


# ── TC-81：find_similar_tests 无测试文件返回空 ──


def test_tc81_find_similar_tests_empty_when_no_tests(tmp_path: Path) -> None:
    """仓库无任何测试文件 → 返回空列表（不抛错）。"""
    from taskprep.git_ops import find_similar_tests
    from tests.conftest import _git_init

    repo = tmp_path / "empty_repo"
    repo.mkdir()
    _git_init(repo)

    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    results = find_similar_tests(repo, ["src/main.py"], max_samples=3)
    assert results == []
