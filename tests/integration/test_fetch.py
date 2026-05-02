"""TC-06 ~ TC-11：harness/fetch.py 的 clone_repo / resolve_ref / token 清理。"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import FixtureRepo


# ──────────────────────────────────────────────
# TC-06：resolve_ref("HEAD") → 完整 40 字符 hash
# ──────────────────────────────────────────────
def test_tc06_resolve_ref_head(make_repo: Callable[..., FixtureRepo]) -> None:
    from harness.fetch import resolve_ref

    repo = make_repo()
    head_hash = resolve_ref(repo.path, "HEAD")
    assert isinstance(head_hash, str)
    assert len(head_hash) == 40
    assert all(c in "0123456789abcdef" for c in head_hash)


def test_tc06_resolve_ref_short_hash(make_repo: Callable[..., FixtureRepo]) -> None:
    from harness.fetch import resolve_ref

    repo = make_repo()
    short = repo.fix_commit[:7]
    resolved = resolve_ref(repo.path, short)
    assert resolved == repo.fix_commit


# ──────────────────────────────────────────────
# TC-07：resolve_ref 不存在的 ref → RuntimeError
# ──────────────────────────────────────────────
def test_tc07_resolve_ref_missing(make_repo: Callable[..., FixtureRepo]) -> None:
    from harness.fetch import resolve_ref

    repo = make_repo()
    with pytest.raises(RuntimeError):
        resolve_ref(repo.path, "no-such-ref-xyzzy")


# ──────────────────────────────────────────────
# TC-08：clone_repo file:// URL → dest 出现 partial clone，HEAD == 指定 commit
# ──────────────────────────────────────────────
def test_tc08_clone_repo_basic(
    make_repo: Callable[..., FixtureRepo], tmp_path: Path
) -> None:
    from harness.fetch import clone_repo

    repo = make_repo()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    result_path = clone_repo(
        repo_url=f"file://{repo.path.as_posix()}",
        ref=repo.fix_commit,
        dest_root=dest_root,
    )

    assert result_path.exists()
    assert (result_path / ".git").is_dir()
    head = subprocess.run(
        ["git", "-C", str(result_path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert head == repo.fix_commit


# ──────────────────────────────────────────────
# TC-09：dest 已存在且 HEAD 匹配 → 复用，不重新 clone
# ──────────────────────────────────────────────
def test_tc09_clone_repo_idempotent(
    make_repo: Callable[..., FixtureRepo], tmp_path: Path
) -> None:
    from harness.fetch import clone_repo

    repo = make_repo()
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    p1 = clone_repo(
        repo_url=f"file://{repo.path.as_posix()}",
        ref=repo.fix_commit, dest_root=dest_root,
    )
    marker = p1 / "_idempotency_marker.txt"
    marker.write_text("kept", encoding="utf-8")

    p2 = clone_repo(
        repo_url=f"file://{repo.path.as_posix()}",
        ref=repo.fix_commit, dest_root=dest_root,
    )
    assert p1 == p2
    # 复用证据：marker 文件未被擦除
    assert marker.exists() and marker.read_text(encoding="utf-8") == "kept"


# ──────────────────────────────────────────────
# TC-10：HTTPS + GITHUB_TOKEN → clone 后 .git/config 不含 token
# ──────────────────────────────────────────────
def test_tc10_token_not_left_in_git_config(
    make_repo: Callable[..., FixtureRepo],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness import fetch as fetch_module

    repo = make_repo()
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_FAKE_TOKEN_DO_NOT_LEAK")
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    fake_https_url = "https://github.com/example/example-repo.git"

    # 拦截 git 子进程，让它"假装"是 HTTPS clone（实际从 fixture 仓库拉）
    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        cmd_list = list(cmd) if isinstance(cmd, (list, tuple)) else [cmd]
        # 替换 git clone 时的 URL 为本地 fixture
        rewritten = []
        for c in cmd_list:
            s = str(c)
            if s.startswith("https://") and "ghp_FAKE_TOKEN_DO_NOT_LEAK" in s:
                # token 注入路径：内部把 token 拼进 URL，再调 clone
                # 这里把它替换为本地 fixture，模拟"clone 成功"
                rewritten.append(f"file://{repo.path.as_posix()}")
            elif s == fake_https_url:
                rewritten.append(f"file://{repo.path.as_posix()}")
            else:
                rewritten.append(c)
        return real_run(rewritten, *args, **kwargs)

    monkeypatch.setattr("subprocess.run", _fake_run)

    fetch_module.clone_repo(
        repo_url=fake_https_url, ref=repo.fix_commit, dest_root=dest_root
    )

    # 找到 dest 下的实际仓库目录
    cloned_dirs = [p for p in dest_root.iterdir() if p.is_dir()]
    assert cloned_dirs
    git_config = (cloned_dirs[0] / ".git" / "config").read_text(encoding="utf-8")
    assert "ghp_FAKE_TOKEN_DO_NOT_LEAK" not in git_config


# ──────────────────────────────────────────────
# TC-11：fetch 中途失败也不留 token 在 config
# ──────────────────────────────────────────────
def test_tc11_token_clean_on_fetch_failure(
    make_repo: Callable[..., FixtureRepo],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness import fetch as fetch_module

    repo = make_repo()
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_LEAK_GUARD_TOKEN")
    dest_root = tmp_path / "dest"
    dest_root.mkdir()

    fake_https_url = "https://github.com/example/example-repo.git"
    real_run = subprocess.run
    state = {"clone_done": False}

    def _fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        cmd_list = list(cmd) if isinstance(cmd, (list, tuple)) else [cmd]
        cmd_str = " ".join(str(c) for c in cmd_list)
        # 让 clone 成功（用本地 fixture 替换）
        if "clone" in cmd_list and not state["clone_done"]:
            rewritten = [
                f"file://{repo.path.as_posix()}" if (
                    str(c).startswith("https://") or "ghp_LEAK_GUARD_TOKEN" in str(c)
                ) else c
                for c in cmd_list
            ]
            state["clone_done"] = True
            return real_run(rewritten, *args, **kwargs)
        # 让 fetch 失败
        if "fetch" in cmd_list:
            raise subprocess.CalledProcessError(
                returncode=128, cmd=cmd_list, stderr=b"fatal: simulated fetch failure"
            )
        return real_run(cmd_list, *args, **kwargs)

    monkeypatch.setattr("subprocess.run", _fake_run)

    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        fetch_module.clone_repo(
            repo_url=fake_https_url, ref=repo.fix_commit, dest_root=dest_root
        )

    cloned_dirs = [p for p in dest_root.iterdir() if p.is_dir() and (p / ".git").exists()]
    if cloned_dirs:  # clone 成功了才有 .git/config
        cfg = (cloned_dirs[0] / ".git" / "config").read_text(encoding="utf-8")
        assert "ghp_LEAK_GUARD_TOKEN" not in cfg, "失败路径下 token 也必须被清除"
