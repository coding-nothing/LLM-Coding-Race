"""TC-17 ~ TC-22：harness/parser.py 的 extract_changes 四级 fallback。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tests.conftest import FixtureRepo


# ──────────────────────────────────────────────
# TC-17：单个 ```diff ... ``` 块
# ──────────────────────────────────────────────
def test_tc17_single_diff_block(
    llm_response: Callable[[str], str], make_repo: Callable[..., FixtureRepo]
) -> None:
    from harness.parser import extract_changes

    repo = make_repo()
    raw = llm_response("valid_diff.txt")
    result = extract_changes(raw, ["src/a.py"], repo.path)

    assert result["format"] == "diff"
    assert "--- a/src/a.py" in result["diff_text"]
    assert "+++ b/src/a.py" in result["diff_text"]
    assert "+    return a + b" in result["diff_text"]
    assert result["raw_blocks_count"] >= 1


# ──────────────────────────────────────────────
# TC-18：多个 ```diff 块取最后一个非空
# ──────────────────────────────────────────────
def test_tc18_multiple_diff_blocks_takes_last_nonempty(
    llm_response: Callable[[str], str], make_repo: Callable[..., FixtureRepo]
) -> None:
    from harness.parser import extract_changes

    repo = make_repo()
    raw = llm_response("multi_diff.txt")
    result = extract_changes(raw, ["src/a.py"], repo.path)

    assert result["format"] == "diff"
    # 最后一个块的修复方案是 + b（正确），不是 * b（错误）
    assert "+    return a + b" in result["diff_text"]
    assert "+    return a * b" not in result["diff_text"]


# ──────────────────────────────────────────────
# TC-19：## File 段 + 围栏块 → 转 unified diff
# ──────────────────────────────────────────────
def test_tc19_file_header_with_block_converts_to_diff(
    llm_response: Callable[[str], str], make_repo: Callable[..., FixtureRepo]
) -> None:
    from harness.parser import extract_changes

    repo = make_repo()
    raw = llm_response("valid_files.txt")
    result = extract_changes(raw, ["src/a.py"], repo.path)

    assert result["format"] == "files"
    assert "--- a/src/a.py" in result["diff_text"]
    assert "+++ b/src/a.py" in result["diff_text"]
    # 新内容含 + b
    assert "+    return a + b" in result["diff_text"]


# ──────────────────────────────────────────────
# TC-20：N 个匿名代码块映射 N 个 main_files
# ──────────────────────────────────────────────
def test_tc20_anonymous_blocks_map_to_main_files(
    llm_response: Callable[[str], str], make_repo: Callable[..., FixtureRepo]
) -> None:
    from harness.parser import extract_changes

    repo = make_repo()
    raw = llm_response("anonymous_blocks.txt")
    result = extract_changes(raw, ["src/a.py"], repo.path)

    assert result["format"] == "files"
    assert "src/a.py" in result["diff_text"]


# ──────────────────────────────────────────────
# TC-21：纯散文 → format=none
# ──────────────────────────────────────────────
def test_tc21_pure_prose_returns_none_format(
    llm_response: Callable[[str], str], make_repo: Callable[..., FixtureRepo]
) -> None:
    from harness.parser import extract_changes

    repo = make_repo()
    raw = llm_response("garbage.txt")
    result = extract_changes(raw, ["src/a.py"], repo.path)

    assert result["format"] == "none"
    assert result["diff_text"] == ""


# ──────────────────────────────────────────────
# TC-22：raw_blocks_count 反映实际代码块数
# ──────────────────────────────────────────────
def test_tc22_raw_blocks_count(
    llm_response: Callable[[str], str], make_repo: Callable[..., FixtureRepo]
) -> None:
    from harness.parser import extract_changes

    repo = make_repo()
    raw = llm_response("multi_diff.txt")  # 2 个 diff 块
    result = extract_changes(raw, ["src/a.py"], repo.path)
    assert result["raw_blocks_count"] == 2


def test_tc22_raw_blocks_count_zero_for_no_blocks(
    llm_response: Callable[[str], str], make_repo: Callable[..., FixtureRepo]
) -> None:
    from harness.parser import extract_changes

    repo = make_repo()
    raw = llm_response("garbage.txt")
    result = extract_changes(raw, ["src/a.py"], repo.path)
    assert result["raw_blocks_count"] == 0


# ──────────────────────────────────────────────
# 补充：malformed diff 不抛错，回落到 none
# ──────────────────────────────────────────────
def test_malformed_diff_does_not_raise(
    llm_response: Callable[[str], str], make_repo: Callable[..., FixtureRepo]
) -> None:
    from harness.parser import extract_changes

    repo = make_repo()
    raw = llm_response("malformed_diff.txt")
    # 任何提取失败都应返回 dict，不抛错
    result = extract_changes(raw, ["src/a.py"], repo.path)
    assert isinstance(result, dict)
    assert result["format"] in ("diff", "files", "none")
