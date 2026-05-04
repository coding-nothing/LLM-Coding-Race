"""taskprep git 操作模块 — 纯 subprocess 调原生 git，无 GitPython 依赖。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Literal


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _is_test_path(path: str) -> bool:
    p = Path(path)
    name = p.name
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.ts"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part in ("tests", "__tests__"):
            return True
    return False


_TEST_EXCLUDE = [
    ":(exclude)*.test.*",
    ":(exclude)*.spec.*",
    ":(exclude)test_*",
    ":(exclude)*_test.*",
    ":(exclude)**/tests/**",
    ":(exclude)**/__tests__/**",
]


def show_diff(repo_path: Path, commit: str, *, include_tests: bool = False) -> str:
    try:
        full = _git(repo_path, "show", commit, "--pretty=format:")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"git show failed for {commit}: {e.stderr}") from e

    if include_tests:
        return full

    lines = full.splitlines(keepends=True)
    result: list[str] = []
    skip = False
    for line in lines:
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                file_a = parts[2]
                file_b = parts[3]
                skip = _is_test_path(file_a) or _is_test_path(file_b)
        if not skip:
            result.append(line)
    return "".join(result)


def changed_files(
    repo_path: Path, commit: str, *, exclude_tests: bool = True
) -> list[str]:
    try:
        output = _git(repo_path, "show", "--name-only", "--format=", commit)
        files = [f.strip() for f in output.splitlines() if f.strip()]
        if exclude_tests:
            files = [f for f in files if not _is_test_path(f)]
        return files
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"git show --name-only failed for {commit}: {e.stderr}") from e


def detect_test_framework(
    repo_path: Path,
) -> Literal["vitest", "jest", "pytest", "cargo-test", "go-test", "unknown"]:
    repo = Path(repo_path)

    pkg_json = repo / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            dev_deps = data.get("devDependencies", {})
            if "vitest" in dev_deps:
                return "vitest"
            if "jest" in dev_deps:
                return "jest"
        except (json.JSONDecodeError, OSError):
            pass

    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            if "[tool.pytest.ini_options]" in content or "[tool.pytest]" in content:
                return "pytest"
        except OSError:
            pass

    cargo = repo / "Cargo.toml"
    if cargo.exists():
        return "cargo-test"

    gomod = repo / "go.mod"
    if gomod.exists():
        return "go-test"

    return "unknown"


def find_similar_tests(
    repo_path: Path, main_files: list[str], max_samples: int = 3
) -> list[tuple[str, str]]:
    repo = Path(repo_path)
    search_roots: set[Path] = set()
    # 始终包含仓库根目录的 tests 子目录
    search_roots.add(repo)
    search_roots.add(repo / "tests")
    search_roots.add(repo / "__tests__")

    for mf in main_files:
        p = Path(mf)
        parent_dir = repo / p.parent
        search_roots.add(parent_dir)
        search_roots.add(parent_dir / "tests")
        search_roots.add(parent_dir / "__tests__")
        # 上溯一层父目录
        grandparent = p.parent.parent
        if str(grandparent) != ".":
            search_roots.add(repo / grandparent)
            search_roots.add(repo / grandparent / "tests")
            search_roots.add(repo / grandparent / "__tests__")

    candidates: set[str] = set()
    for root in search_roots:
        if not root.exists():
            continue
        for entry in root.rglob("*"):
            if entry.is_file():
                rel = str(entry.relative_to(repo)).replace("\\", "/")
                if _is_test_path(rel):
                    candidates.add(rel)

    if not candidates:
        return []

    scored: list[tuple[int, str]] = []
    for c in candidates:
        try:
            ts = _git(repo_path, "log", "-1", "--format=%ct", "HEAD", "--", c)
            scored.append((int(ts.strip() or "0"), c))
        except subprocess.CalledProcessError:
            scored.append((0, c))

    scored.sort(reverse=True)

    results: list[tuple[str, str]] = []
    for _, path in scored[:max_samples]:
        try:
            content = (repo / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            content = ""
        results.append((path, content))

    return results


def resolve_base_commit(repo_path: Path, source_commit: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", f"{source_commit}^"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        if any(
            kw in stderr
            for kw in ("unknown revision", "bad revision", "does not have")
        ):
            raise RuntimeError(
                f"Invalid commit: {source_commit} — {stderr}"
            ) from e
        raise RuntimeError(
            f"Cannot resolve base commit for {source_commit}: {stderr}"
        ) from e
