# Multi-Agent Software Engineering Team

> 多 Agent 软件工程团队 — 基于 [AI Engineering from Scratch](https://github.com/rohitg00/ai-engineering-from-scratch) 课程 Phase 19 第 10 个 capstone 项目

一个由 5 个专门化 AI Agent 组成的软件工程团队，通过 A2A 类型化任务板协调工作，将 GitHub Issue 转化为可合并的 PR。

## 架构

```
GitHub Issue → Architect(Claude Opus) → 子任务 DAG
                    ↓
              Task Board (JSONL)
                    ↓
    ┌──────┬────────┼────────┬──────┐
    ↓      ↓        ↓        ↓      ↓
  Coder A  Coder B  Coder C  Coder D  (并行 git worktree)
    └──────┴────────┼────────┴──────┘
                    ↓
            Merge Coordinator (三方合并 + LLM 冲突调解)
                    ↓
                Reviewer (代码审查 + 误批探测)
                    ↓
                 Tester (沙箱测试) → 通过 → PR
                    ↓ (失败则反馈回 Coder)
```

## 特性

- **5 角色协作**：架构师 → 编码者(并行) → 合并协调器 → 审查者 → 测试者
- **类型化任务板**：9 种 A2A 消息类型，JSONL 文件存储，线程安全
- **多供应商 LLM**：Anthropic (Claude)、OpenAI (GPT)、Google (Gemini)
- **并行工作树**：每个编码者在独立 `git worktree` 中互不干扰
- **智能 Stub 模式**：无需 API Key 即可测试完整流程，根据输入动态生成响应
- **预算控制**：按角色 + 总计的 token 上限，超限自动阻断
- **重试机制**：LLM 调用指数退避重试（3 次 max）
- **误批探测**：可配置的 Bug 注入率，测量审查者漏报率
- **Token 放大率**：自动对比多 Agent vs 单 Agent 的 token 效率
- **结构化日志**：logging 模块，支持文件和控制台双输出
- **CI/CD**：GitHub Actions 在 3 操作系统 × 3 Python 版本上自动测试

## 快速开始

```bash
# 克隆并安装
git clone <repo-url>
cd "Multi-Agent Software Engineering Team"
pip install -r requirements.txt

# === Stub 模式（无需 API Key）===
python cli.py run --issue "修复缓存溢出导致的数据不一致" --stub
python cli.py run --issue "重构 API 认证中间件" --stub --coders 4

# === 真实模式（需设置 API Keys）===
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GOOGLE_API_KEY=...

# 从 GitHub Issue URL 直接启动
python cli.py run --issue "https://github.com/user/repo/issues/42" --repo /path/to/repo

# 批量评估
echo "issue-1: 修复竞态条件" > issues.txt
echo "issue-2: 添加请求限流" >> issues.txt
python cli.py eval --issues-file issues.txt --coders 4 --baseline

# 单 Agent 基线对比
python cli.py baseline --issue "修复登录页面超时问题" --stub

# 详细日志
python cli.py run --issue "你的问题" --stub -v --log-file team.log
```

## 命令行

```
python cli.py run    --issue <url|描述> [--repo <路径>] [--coders N]
                     [--baseline] [--stub] [--output <json>] [-v] [--log-file <路径>]

python cli.py eval   --issues-file <路径> [--coders N] [--baseline] [--stub]

python cli.py baseline --issue <url|描述> [--stub]
```

## 项目结构

```
├── src/
│   ├── config.py           # 配置：角色-模型映射、预算上限
│   ├── task_board.py       # A2A 类型化消息板（JSONL 文件存储，线程安全）
│   ├── llm.py              # 多供应商 LLM 抽象层 + Stub（带指数退避重试）
│   ├── accounting.py       # Token 账本 + 交接跨度 + 运行报告
│   ├── budget.py           # 预算守卫：按角色/总计检查，超限阻断
│   ├── retry.py            # 通用装饰器：指数退避重试 + safe_run 超时包装
│   ├── logging_config.py   # 结构化日志配置（控制台 + 文件）
│   ├── orchestrator.py     # 团队编排器：串联全流程，反馈循环，预算集成
│   └── roles/
│       ├── architect.py    # 架构师：Issue → 子任务 DAG + 动态 Stub
│       ├── coder.py        # 编码者：并行 worktree + 28 种 Stub 代码生成
│       ├── merge_coord.py  # 合并协调器：三方合并 + LLM 冲突调解
│       ├── reviewer.py     # 审查者：diff 审查 + 自审硬约束 + 误批探测
│       └── tester.py       # 测试者：本地/Docker 沙箱 + Stub 覆写
├── cli.py                  # 命令行入口
├── tests/                  # 22 个测试（任务板/角色/编排器）
├── .github/workflows/
│   └── ci.yml              # CI：3 OS × 3 Python + lint
├── requirements.txt
├── CHANGELOG.md
├── CONTRIBUTING.md
└── README.md
```

## 测试

```bash
# 全部测试
pytest tests/ -v

# 分模块
pytest tests/test_task_board.py -v    # 任务板（8 个）
pytest tests/test_roles.py -v         # 角色（9 个）
pytest tests/test_orchestrator.py -v  # 编排器（5 个）
```

## 配置

通过环境变量自定义：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | — |
| `OPENAI_API_KEY` | OpenAI API 密钥 | — |
| `GOOGLE_API_KEY` | Google API 密钥 | — |
| `TEAM_ARCHITECT_MODEL` | 架构师模型 | `claude-opus-4-7` |
| `TEAM_CODER_MODEL` | 编码者模型 | `claude-sonnet-4-7` |
| `TEAM_REVIEWER_MODEL` | 审查者模型 | `gpt-5.4` |
| `TEAM_TESTER_MODEL` | 测试者模型 | `gemini-2.5-pro` |
| `TEAM_MAX_CODERS` | 最大并行编码者数 | `8` |
| `TEAM_INJECT_BUG_RATE` | 误批探测 Bug 注入率 | `0.0` |

在代码中通过 `TeamConfig` 类进行更细粒度的配置（角色预算上限、工作树路径等）。

## 许可

MIT — 继承自 [AI Engineering from Scratch](https://github.com/rohitg00/ai-engineering-from-scratch)
