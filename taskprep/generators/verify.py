"""generate_verify — 模板驱动生成 verify.sh（不调 LLM）。"""

from __future__ import annotations

from taskprep.llm import LLMConfig


_VITEST_TEMPLATE = """\
#!/usr/bin/env bash
set -e
cd "$1"
pnpm install
pnpm test {test_paths}
"""

_PYTEST_TEMPLATE = """\
#!/usr/bin/env bash
set -e
cd "$1"
python -m pytest {test_paths} -q
"""

_UNKNOWN_TEMPLATE = """\
#!/usr/bin/env bash
set -e
cd "$1"
# [需要人工填写] 无法自动检测测试框架，请手动填入 install 和 test 命令。
echo "[WARNING] verify.sh 尚未完成 — 请人工填写测试命令" >&2
exit 1
"""


def generate_verify(
    framework: str, test_paths: list[str], llm: LLMConfig | None = None
) -> str:
    _ = llm  # unused; verify 不调 LLM

    paths_str = " ".join(test_paths) if test_paths else ""

    if framework == "vitest":
        return _VITEST_TEMPLATE.format(test_paths=paths_str)
    elif framework == "pytest":
        return _PYTEST_TEMPLATE.format(test_paths=paths_str)
    else:
        return _UNKNOWN_TEMPLATE
