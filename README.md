# LLM-Coding-Race

一个用来评测大模型 coding 能力的 harness。

> **Phase 1 + Phase 2 全部交付完成。** 两个 Project 解耦，靠 `tasks/<task_id>/` 的文件系统契约通讯。

## 快速开始

环境要求：

- Python 3.11+（开发主机为 Python 3.14 / Windows）
- 已安装 `git`、`bash`（Windows 上为 git-bash）

安装依赖：

```bash
pip install -e ".[dev]"
```

API key 通过 `.env`（见 `.env.example`）或环境变量提供：

| 模型 | 环境变量 | 说明 |
|---|---|---|
| `claude-opus-4-7` | `ANTHROPIC_API_KEY` | 当前由用户用 Pro 订阅 + Claude Code 手工跑，Project B 不直连 |
| `deepseek-v4-pro` | `DEEPSEEK_API_KEY` | OpenAI 兼容路径 |
| `glm-5.1` | `ZHIPU_API_KEY` | OpenAI 兼容路径 |

## 已实现的 CLI

### Project B — harness（Phase 1）

```bash
# 1. 准备仓库（任选其一）
python -m harness.cli fetch --repo <url> --ref <commit> --dest-root repos
python -m harness.cli fetch --task <task_id> --tasks-dir tasks --dest-root repos

# 2. 跑模型 → 写 outputs/<model>/<task>/run_<n>.json
python -m harness.cli run --models deepseek-v4-pro,glm-5.1 \
    --tasks-dir tasks --output-dir outputs --runs 2

# 3. 评分 → 写 outputs/<model>/<task>/grade_<n>.json
python -m harness.cli grade --tasks-dir tasks --output-dir outputs

# 4. 报告 → reports/report.md
python -m harness.cli report --output-dir outputs --reports-dir reports

# 5. 一键串：fetch → run → grade → report
python -m harness.cli all --models deepseek-v4-pro \
    --tasks-dir tasks --output-dir outputs --reports-dir reports --runs 2
```

### Project A — taskprep（Phase 2）

```bash
# 生成评测任务草稿（全部 LLM 产物带 .draft 后缀，需人工审核去后缀）
python -m taskprep.cli draft \
    --repo-url <url> --commit <hash> \
    --local-repo <path> --debug-doc <path> \
    --task-id <id>

# 单独重新生成某一产物
python -m taskprep.cli regen --task-id <id> --target test_patch|prompt|target_files|verify

# 重新运行 sanity check，更新审核清单
python -m taskprep.cli check --task-id <id>

# 列出所有任务及 .draft 状态
python -m taskprep.cli status
```

公共开关：

- `--allow-drafts`：忽略 `tasks/<id>/*.draft` 残留警告（默认 `.draft` 残留时 CLI 退出非 0）
- `--repo-path <task_id>=<本地仓库路径>`：跳过 fetch，直接指向本地仓库（测试与离线评测常用）
- `--tasks <id1,id2>` / `--models <name1,name2>`：仅评测指定任务/模型

## 任务目录契约（`tasks/<task_id>/`）

由 Phase 2 的 `taskprep` 自动生成草稿（带 `.draft` 后缀），人工审核去后缀后才被 `harness` 接受。
当前 Phase 2 未实现，可手写以下文件：

| 文件 | 必填 | 说明 |
|---|---|---|
| `meta.json` | ✓ | `task_id`、`repo_url`、`base_commit` |
| `prompt.md` | ✓ | 任务描述（system+user 都可以引用） |
| `target_files.txt` | ✓ | `main:` / `reference:` / `tree:` 段，决定 context 内容 |
| `reference.diff` | 推荐 | 标准答案 diff（仅人工评分阅读，禁止进 prompt） |
| `test_patch.diff` | 评分需要 | 单测/集测 patch；grader 在 worktree 上先 apply 它 |
| `verify.sh` | 评分需要 | grader 跑 `bash verify.sh <worktree_path>` 决定 tests_pass |

## 评测产物布局

```
outputs/<model>/<task>/run_<n>.json    # 模型原始响应 + 解析结果（PRD §B3.3）
outputs/<model>/<task>/grade_<n>.json  # diff 应用 + 测试结果 + 人工评分占位（PRD §B3.4）
reports/report.md                      # 总览 + 模型聚合 + 任务前缀聚合 + 失败附录
repos/<repo>_<ref>/                    # clone 出来的仓库副本（可复用）
```

## 测试

```bash
python -m pytest tests/
```

**Phase 1 + Phase 2：106 passed, 0 failed**（详见 `references/test-report-taskprep-round1.md`）。

## 开发流水线

整个仓库通过 `skills/vibe-delivery/SKILL.md` 描述的 9 阶段流水线交付：
`/prd` → `/prototype` → `/plan` → `/test-plan` → `/setup-test` → `/gen-test` → `/implement` → `/test` → `/ship`。
当前进度记录在 `references/workflow-state.json`，过程文档归档在 `references/archive/phase1/` 和 `references/archive/phase2/`。

## 项目结构

```
harness/                    # Phase 1 实现（已交付）
├── config.py               # ModelConfig + MODELS + load_dotenv
├── fetch.py                # clone_repo + token 安全清理
├── context.py              # build_context（防答案泄露）
├── parser.py               # 四级 fallback 提取 unified diff
├── runner.py               # 统一 LLM 调用 + run_all 幂等
├── grader.py               # worktree 隔离 + apply + verify
├── report.py               # markdown 报告聚合
└── cli.py                  # argparse 入口

taskprep/                   # Phase 2 实现（已交付）
├── cli.py                  # draft / regen / check / status 子命令
├── git_ops.py              # show_diff / changed_files / detect_test_framework / find_similar_tests
├── llm.py                  # LLMConfig + call（双 provider + 退避重试）
├── sanity.py               # run_sanity_check（worktree 隔离）
├── checklist.py            # generate_checklist（审核清单）
├── generators/
│   ├── prompt.py           # generate_prompt → prompt.md.draft
│   ├── target_files.py     # generate_target_files → target_files.txt.draft
│   ├── test_patch.py       # generate_test_patch → test_patch.diff.draft
│   └── verify.py           # generate_verify → verify.sh.draft
└── prompts/                # 版本化 system prompt 模板

tests/                      # 106 个测试
references/                 # PRD + workflow-state（archive/ 存归档过程文档）
tasks/                      # 评测任务（运行时填入；.gitignore）
outputs/, reports/, repos/  # 运行时产物（.gitignore）
```

## License

见 `LICENSE`。
