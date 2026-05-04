"""Shared pytest fixtures for harness/ and taskprep/ tests.

设计要点：
- 全部 LLM 调用 mock 到 SDK 客户端层（`anthropic.Anthropic` / `openai.OpenAI`）
- git 调用一律走真实 subprocess + 程序化 fixture 仓库
- `_isolate_env` autouse 把 API key 设为 test_*，避免误打真实网络
- `fast_sleep` 把 `time.sleep` 短路掉，避免重试退避拖慢 unit 测试
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ──────────────────────────────────────────────
# 环境隔离
# ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """默认把测试期可能用到的 API key 设为 test_*；GITHUB_TOKEN 默认清空。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_anthropic_key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test_deepseek_key")
    monkeypatch.setenv("ZHIPU_API_KEY", "test_zhipu_key")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    yield


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """记录 time.sleep 调用并立即返回，避免重试逻辑真的睡。

    用法：`captured = fast_sleep; ...; assert captured == [2, 4]`
    """
    captured: list[float] = []

    def _fake_sleep(seconds: float) -> None:
        captured.append(seconds)

    monkeypatch.setattr("time.sleep", _fake_sleep)
    return captured


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        path_str = str(item.path).replace(os.sep, "/")
        if "/tests/unit/" in path_str:
            item.add_marker(pytest.mark.unit)
        elif "/tests/integration/" in path_str:
            item.add_marker(pytest.mark.integration)
        elif "/tests/e2e/" in path_str:
            item.add_marker(pytest.mark.e2e)
        elif "/tests/smoke/" in path_str:
            item.add_marker(pytest.mark.smoke)


# ──────────────────────────────────────────────
# 真实 git fixture 仓库
# ──────────────────────────────────────────────


def _git(repo: Path, *args: str) -> str:
    """在 repo 下执行 git 命令，返回 stdout（已 strip）。"""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "core.autocrlf", "false")


@dataclass(frozen=True)
class FixtureRepo:
    path: Path
    init_commit: str
    fix_commit: str


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., FixtureRepo]:
    """程序化创建最小 fixture 仓库，含 init_commit（含 bug）+ fix_commit（修 bug + 加测试）。"""

    def _make(name: str = "fixture_repo") -> FixtureRepo:
        repo = tmp_path / name
        repo.mkdir()
        _git_init(repo)

        # init commit：src/a.py 含 bug，src/b.ts 作为 reference 风格文件
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text(
            "def add(a, b):\n    return a - b  # bug\n",
            encoding="utf-8",
        )
        (repo / "src" / "b.ts").write_text(
            "export const greet = (name: string) => `Hi ${name}`\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init")
        init_commit = _git(repo, "rev-parse", "HEAD")

        # fix commit：修 bug + 新增 pytest 测试
        (repo / "src" / "a.py").write_text(
            "def add(a, b):\n    return a + b\n",
            encoding="utf-8",
        )
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text(
            "from src.a import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fix bug + add test")
        fix_commit = _git(repo, "rev-parse", "HEAD")

        # 回到 init_commit，让仓库默认处于 base 状态（grader 使用）
        _git(repo, "checkout", "-q", init_commit)

        return FixtureRepo(path=repo, init_commit=init_commit, fix_commit=fix_commit)

    return _make


# ──────────────────────────────────────────────
# 任务目录 fixture
# ──────────────────────────────────────────────


@dataclass(frozen=True)
class SampleTask:
    task_dir: Path
    repo: FixtureRepo


@pytest.fixture
def sample_task(tmp_path: Path, make_repo: Callable[..., FixtureRepo]) -> SampleTask:
    """生成一个完整的 fixture 任务目录（含全部 6 个契约文件，无 .draft 后缀）。"""
    repo = make_repo()
    task_dir = tmp_path / "tasks" / "sample-fix"
    task_dir.mkdir(parents=True)

    (task_dir / "meta.json").write_text(
        json.dumps(
            {
                "task_id": "sample-fix",
                "repo_url": f"file://{repo.path.as_posix()}",
                "base_commit": repo.init_commit,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (task_dir / "prompt.md").write_text(
        "# Bug\n\n`src/a.py` 中的 `add` 函数错把加法写成减法，请修复。\n",
        encoding="utf-8",
    )
    (task_dir / "target_files.txt").write_text(
        "main:src/a.py\nreference:src/b.ts\ntree:src/\n",
        encoding="utf-8",
    )

    test_patch = subprocess.run(
        [
            "git", "-C", str(repo.path), "diff",
            f"{repo.init_commit}..{repo.fix_commit}", "--", "tests/",
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    (task_dir / "test_patch.diff").write_text(test_patch, encoding="utf-8")

    src_diff = subprocess.run(
        [
            "git", "-C", str(repo.path), "diff",
            f"{repo.init_commit}..{repo.fix_commit}", "--", "src/",
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    (task_dir / "reference.diff").write_text(src_diff, encoding="utf-8")

    (task_dir / "verify.sh").write_text(
        '#!/usr/bin/env bash\nset -e\ncd "$1"\npython -m pytest tests/test_a.py -q\n',
        encoding="utf-8",
    )

    return SampleTask(task_dir=task_dir, repo=repo)


# ──────────────────────────────────────────────
# LLM 响应物料 loader
# ──────────────────────────────────────────────


@pytest.fixture
def llm_response(fixtures_dir: Path) -> Callable[[str], str]:
    """从 tests/fixtures/llm_responses/ 加载固定模型响应文本。"""

    def _load(name: str) -> str:
        path = fixtures_dir / "llm_responses" / name
        return path.read_text(encoding="utf-8")

    return _load


# ──────────────────────────────────────────────
# SDK 客户端 mock
# ──────────────────────────────────────────────


@pytest.fixture
def mock_anthropic(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch `harness.runner.anthropic.Anthropic`，返回 client mock。

    用法：
        client = mock_anthropic
        client.messages.create.return_value = make_anthropic_message("...")
    """
    client = MagicMock(name="AnthropicClient")
    factory = MagicMock(return_value=client, name="AnthropicFactory")
    monkeypatch.setattr("harness.runner.anthropic.Anthropic", factory, raising=False)
    client._factory = factory  # 暴露给测试断言构造参数
    return client


@pytest.fixture
def mock_openai(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch `harness.runner.openai.OpenAI`，返回 client mock。"""
    client = MagicMock(name="OpenAIClient")
    factory = MagicMock(return_value=client, name="OpenAIFactory")
    monkeypatch.setattr("harness.runner.openai.OpenAI", factory, raising=False)
    client._factory = factory
    return client


def make_anthropic_message(text: str, *, input_tokens: int = 100,
                           output_tokens: int = 50,
                           cache_read: int = 0) -> Any:
    """构造 anthropic SDK 的 Message 形状（仅含被 runner 用到的字段）。"""
    msg = MagicMock(name="AnthropicMessage")
    block = MagicMock(name="ContentBlock")
    block.type = "text"
    block.text = text
    msg.content = [block]
    usage = MagicMock(name="Usage")
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = cache_read
    msg.usage = usage
    return msg


def make_openai_completion(text: str, *, prompt_tokens: int = 100,
                           completion_tokens: int = 50) -> Any:
    """构造 openai SDK 的 ChatCompletion 形状。"""
    completion = MagicMock(name="ChatCompletion")
    choice = MagicMock(name="Choice")
    choice.message.content = text
    completion.choices = [choice]
    usage = MagicMock(name="Usage")
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.prompt_tokens_details = MagicMock(cached_tokens=0)
    completion.usage = usage
    return completion


# ──────────────────────────────────────────────
# Phase 2 taskprep 专用 fixture（追加，不动 Phase 1）
# ──────────────────────────────────────────────


@pytest.fixture
def make_repo_with_merge(tmp_path: Path) -> Callable[..., FixtureRepo]:
    """在 make_repo 基础上创建 feature 分支 + merge commit，用于 TC-76。

    返回的 FixtureRepo.fix_commit 是 merge commit（2 个父 commit）。
    """

    def _make(name: str = "fixture_repo_merge") -> FixtureRepo:
        repo = tmp_path / name
        repo.mkdir()
        _git_init(repo)

        # init commit
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text(
            "def add(a, b):\n    return a - b  # bug\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init")
        init_commit = _git(repo, "rev-parse", "HEAD")

        # 记住初始分支名（不同 git 版本可能用 master 或 main）
        init_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")

        # feature 分支
        _git(repo, "checkout", "-q", "-b", "feature/fix")
        (repo / "src" / "a.py").write_text(
            "def add(a, b):\n    return a + b\n",
            encoding="utf-8",
        )
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text(
            "from src.a import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fix bug + add test")

        # 切回初始分支并 merge feature（no-ff 保证 merge commit）
        _git(repo, "checkout", "-q", init_branch)
        _git(repo, "merge", "--no-ff", "-q", "-m", "merge feature/fix", "feature/fix")
        merge_commit = _git(repo, "rev-parse", "HEAD")

        # 回到 init_commit
        _git(repo, "checkout", "-q", init_commit)

        return FixtureRepo(path=repo, init_commit=init_commit, fix_commit=merge_commit)

    return _make


@pytest.fixture
def make_repo_with_manifest(tmp_path: Path) -> Callable[..., FixtureRepo]:
    """make_repo + 写入 package.json 或 pyproject.toml，用于 TC-77/78/79。

    manifest 参数：`"package.json"` → vitest；`"pyproject.toml"` → pytest。
    """

    def _make(manifest: str = "package.json", name: str = "fixture_repo_manifest") -> FixtureRepo:
        repo = tmp_path / name
        repo.mkdir()
        _git_init(repo)

        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text(
            "def add(a, b):\n    return a - b  # bug\n",
            encoding="utf-8",
        )

        if manifest == "package.json":
            (repo / "package.json").write_text(
                '{"devDependencies": {"vitest": "^1.0.0"}}\n',
                encoding="utf-8",
            )
        elif manifest == "pyproject.toml":
            (repo / "pyproject.toml").write_text(
                "[tool.pytest.ini_options]\nminversion = \"8.0\"\n",
                encoding="utf-8",
            )

        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init with manifest")
        init_commit = _git(repo, "rev-parse", "HEAD")

        # fix commit
        (repo / "src" / "a.py").write_text(
            "def add(a, b):\n    return a + b\n",
            encoding="utf-8",
        )
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text(
            "from src.a import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fix bug + add test")
        fix_commit = _git(repo, "rev-parse", "HEAD")

        _git(repo, "checkout", "-q", init_commit)

        return FixtureRepo(path=repo, init_commit=init_commit, fix_commit=fix_commit)

    return _make


@pytest.fixture
def debug_doc_sample(tmp_path: Path) -> Path:
    """生成示例 debug 文档（含现象/复现/错误/约束 4 段），用于 TC-69 等。"""
    doc = tmp_path / "debug-doc.md"
    doc.write_text(
        "# 调试文档：add 函数错误\n\n"
        "## 现象\n\n"
        "调用 `add(1, 2)` 返回 `-1` 而非 `3`。\n\n"
        "## 复现步骤\n\n"
        "1. 运行 `python -c \"from src.a import add; print(add(1, 2))\"`\n"
        "2. 观察输出为 `-1`\n\n"
        "## 错误信息\n\n"
        "无报错，逻辑错误。\n\n"
        "## 约束\n\n"
        "- 不修改函数签名\n"
        "- 使用 Python 3.11+ 语法\n",
        encoding="utf-8",
    )
    return doc


@pytest.fixture
def mock_taskprep_anthropic(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch `taskprep.llm.anthropic.Anthropic`，返回 client mock。

    与 Phase 1 的 `mock_anthropic`（patch harness.runner.*）独立，不可合并。
    """
    client = MagicMock(name="TaskprepAnthropicClient")
    factory = MagicMock(return_value=client, name="TaskprepAnthropicFactory")
    monkeypatch.setattr("taskprep.llm.anthropic.Anthropic", factory, raising=False)
    client._factory = factory
    return client


@pytest.fixture
def mock_taskprep_openai(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch `taskprep.llm.openai.OpenAI`，返回 client mock。

    与 Phase 1 的 `mock_openai`（patch harness.runner.*）独立，不可合并。
    """
    client = MagicMock(name="TaskprepOpenAIClient")
    factory = MagicMock(return_value=client, name="TaskprepOpenAIFactory")
    monkeypatch.setattr("taskprep.llm.openai.OpenAI", factory, raising=False)
    client._factory = factory
    return client
