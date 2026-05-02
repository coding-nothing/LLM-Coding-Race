"""仓库 clone + ref 解析 + token 安全清理。

不变量（PRD §B5）：
- HTTPS + GITHUB_TOKEN 的注入路径，无论成功/失败都必须清除 .git/config 中的凭据。
- 用 try/finally 包住 fetch+checkout，把 _strip_token_from_remote 放进 finally。
"""

from __future__ import annotations

import os
import re
import subprocess
import urllib.parse
from pathlib import Path


def resolve_ref(repo_path: Path, ref: str) -> str:
    """把 ref（branch/tag/short hash/HEAD）解析为完整 40 字符 commit hash。"""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--verify", f"{ref}^{{commit}}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        raise RuntimeError(f"无法解析 ref '{ref}': {stderr.strip()}") from exc
    full = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", full):
        raise RuntimeError(f"git rev-parse 返回非法 hash：{full!r}")
    return full


def _strip_token_from_remote(repo_path: Path) -> None:
    """把 origin remote URL 重置为不含 userinfo（即 token）的形式。"""
    cfg_path = Path(repo_path) / ".git" / "config"
    if not cfg_path.is_file():
        return
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
        )
    except OSError:
        return
    if result.returncode != 0:
        return
    url = (result.stdout or "").strip()
    if not url:
        return
    parsed = urllib.parse.urlparse(url)
    if not (parsed.username or parsed.password):
        return
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    cleaned = urllib.parse.urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "remote", "set-url", "origin", cleaned],
        check=False,
        capture_output=True,
        text=True,
    )


def _repo_dir_name(repo_url: str, ref: str) -> str:
    if "://" in repo_url:
        parsed = urllib.parse.urlparse(repo_url)
        last = Path(parsed.path).name
    else:
        last = Path(repo_url).name
    if last.endswith(".git"):
        last = last[:-4]
    if not last:
        last = "repo"
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", ref):
        ref_short = ref[:7]
    else:
        ref_short = re.sub(r"[^A-Za-z0-9._-]", "_", ref)[:20] or "ref"
    return f"{last}_{ref_short}"


def _inject_token(repo_url: str, token: str) -> str:
    parsed = urllib.parse.urlparse(repo_url)
    netloc_with_token = f"x-access-token:{token}@{parsed.netloc}"
    return urllib.parse.urlunparse(
        (parsed.scheme, netloc_with_token, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def clone_repo(repo_url: str, ref: str, dest_root: Path) -> Path:
    """Clone repo_url 到 dest_root/<name>_<ref_short>/，checkout 指定 ref。

    幂等：dest 存在且含 .git 时直接复用。
    安全：HTTPS+GITHUB_TOKEN 路径下 finally 清除 token。
    """
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / _repo_dir_name(repo_url, ref)

    if dest.exists() and (dest / ".git").exists():
        return dest

    token = os.environ.get("GITHUB_TOKEN")
    using_token = bool(token) and repo_url.startswith("https://")
    clone_url = _inject_token(repo_url, token) if using_token else repo_url

    try:
        subprocess.run(
            ["git", "clone", "--filter=blob:none", clone_url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        if dest.exists():
            _strip_token_from_remote(dest)
        raise RuntimeError(
            f"git clone 失败 ({repo_url}): {(exc.stderr or '').strip()}"
        ) from exc

    try:
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "origin", ref],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(dest), "checkout", "-q", ref],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        _strip_token_from_remote(dest)

    return dest
