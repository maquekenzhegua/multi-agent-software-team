# Multi-Agent Software Engineering Team

<p align="center">
  <strong>5 个 AI Agent 自动把 GitHub Issue 变成可合并的 PR  |  English &amp; 中文</strong>
</p>

<p align="center">
  <a href="https://github.com/maquekenzhegua/multi-agent-software-team/actions/workflows/ci.yml"><img src="https://github.com/maquekenzhegua/multi-agent-software-team/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT"></a>
  <a href="https://github.com/maquekenzhegua/multi-agent-software-team"><img src="https://img.shields.io/github/stars/maquekenzhegua/multi-agent-software-team?style=social" alt="Stars"></a>
</p>

---

> 基于 [AI Engineering from Scratch](https://github.com/rohitg00/ai-engineering-from-scratch) 课程 Phase 19 Capstone 项目

一个由 5 个专门化 AI Agent 组成的虚拟软件工程团队，通过 A2A 类型化任务板协调工作。给定一个 GitHub Issue，自动完成：**需求分析 → 代码实现 → 合并 → 审查 → 测试**，最终产出一个可合并的 PR。

A virtual software engineering team of 5 specialized AI agents coordinated through a typed A2A task board. Feed it a GitHub Issue and it autonomously produces a mergeable PR — from architecture to passing tests.

---

## Demo

<p align="center">
  <img src="https://raw.githubusercontent.com/maquekenzhegua/multi-agent-software-team/main/demo/demo.gif" width="700" alt="Demo" onerror="this.style.display='none'">
</p>

```bash
$ python cli.py run --issue "修复 widget 解析竞态条件" --stub --coders 4

13:45:01 [INFO ] agent_team.orchestrator | 启动多 Agent 团队: 4 编码者, 预算 120000 tokens
13:45:03 [INFO ] agent_team.orchestrator | [architect] 计划: 修复竞态条件：为共享状态添加线程安全保护 (4 个子任务)
13:45:03 [INFO ] agent_team.orchestrator | [board] 已将 4 个子任务分派给 4 个编码者
13:45:05 [INFO ] agent_team.orchestrator | [coder-A] lock: +25/-0 行, 1 个文件
13:45:05 [INFO ] agent_team.orchestrator | [coder-B] parser: +18/-0 行, 1 个文件
13:45:05 [INFO ] agent_team.orchestrator | [coder-C] cache: +20/-0 行, 1 个文件
13:45:05 [INFO ] agent_team.orchestrator | [coder-D] test: +12/-0 行, 1 个文件
13:45:06 [INFO ] agent_team.orchestrator | [merge] 合并 4 个分支...
13:45:06 [INFO ] agent_team.orchestrator | [merge] 4 个文件变更, 0 个冲突
13:45:08 [INFO ] agent_team.orchestrator | [reviewer] 通过
13:45:09 [INFO ] agent_team.orchestrator | [tester] 通过: 42/42
13:45:09 [INFO ] agent_team.orchestrator | [team] 完成: 8.3s, 9860 tokens

========== 运行报告 ==========
Issue: 修复 widget 解析竞态条件
编码者数量: 4
子任务: 4/4
审查通过: 是 (反馈 0 次)
测试通过: 是
耗时: 8.3s
总 token: 9,860
Token 放大率: 2.1x
```

---

## 架构 Architecture

```
GitHub Issue → Architect(Claude Opus) → 子任务 DAG
                    ↓
              Task Board (JSONL)        ← A2A 协议，9 种消息类型
                    ↓
    ┌──────┬────────┼────────┬──────┐
    ↓      ↓        ↓        ↓      ↓
  Coder A Coder B  Coder C  Coder D   (并行 git worktree)
    └──────┴────────┼────────┴──────┘
                    ↓
          Merge Coordinator            (三方合并 + LLM 冲突调解)
                    ↓
              Reviewer                 (代码审查 + 误批探测)
                    ↓
              Tester                   (沙箱测试) → 通过 → PR
                ↓ (失败则反馈回 Coder)
```

## 特性 | Features

| 特性 | 说明 |
|------|------|
| 5 角色协作 | 架构师 → 编码者(并行) → 合并协调器 → 审查者 → 测试者，带反馈循环 |
| 多供应商 LLM | Anthropic (Claude)、OpenAI (GPT)、Google (Gemini)，按角色分配不同模型 |
| Stub 模式 | **无需 API Key** 即可测试完整流程，28 种模板自动匹配场景 |
| 并行工作树 | 每个编码者在独立 `git worktree` 中互不干扰，真实 git 操作 |
| 预算控制 | 按角色 + 总计的 token 上限，**预检查阻断**，不会花超了才发现 |
| 误批探测 | 可配置 Bug 注入率，自动测量审查者漏报率 |
| Token 放大率 | 自动对比多 Agent vs 单 Agent 的 token 效率 |
| CI/CD | GitHub Actions：3 OS x 3 Python 版本，每次 push 自动跑 22 个测试 |

---

## 快速开始 | Quick Start

```bash
# 克隆 Clone
git clone https://github.com/maquekenzhegua/multi-agent-software-team.git
cd multi-agent-software-team
pip install -r requirements.txt

# === Stub 模式（无需 API Key，30 秒感受完整流程）===
python cli.py run --issue "修复缓存溢出导致的数据不一致" --stub
python cli.py run --issue "重构 API 认证中间件" --stub --coders 4

# === 真实模式（需设置 API Keys）===
# Windows PowerShell:
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:OPENAI_API_KEY = "sk-..."
$env:GOOGLE_API_KEY = "..."

# Linux / macOS:
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GOOGLE_API_KEY=...

# 从 GitHub Issue URL 直接启动
python cli.py run --issue "https://github.com/user/repo/issues/42" --repo /path/to/repo

# 批量评估 + 基线对比
python cli.py eval --issues-file issues.txt --coders 4 --stub --baseline

# 单 Agent 基线对比
python cli.py baseline --issue "修复登录页面超时问题" --stub
```

## 命令行 | CLI

```
python cli.py run      --issue <url|描述> [--repo <路径>] [--coders N]
                       [--baseline] [--stub] [--output <json>] [-v] [--log-file <路径>]

python cli.py eval     --issues-file <路径> [--coders N] [--baseline] [--stub]

python cli.py baseline --issue <url|描述> [--stub]
```

## 测试 | Tests

```bash
pytest tests/ -v                                    # 全部 22 个测试
pytest tests/test_task_board.py -v                  # 任务板（8 个）
pytest tests/test_roles.py -v                       # 角色（9 个）
pytest tests/test_orchestrator.py -v                # 编排器（5 个）
```

## 项目结构 | Structure

```
├── src/
│   ├── config.py              # 角色-模型映射、预算上限
│   ├── task_board.py          # A2A 类型化消息板（JSONL，线程安全）
│   ├── llm.py                 # 多供应商 LLM 抽象层 + Stub
│   ├── accounting.py          # Token 账本 + 运行报告
│   ├── budget.py              # 预算守卫：预检查阻断机制
│   ├── retry.py               # 指数退避重试装饰器 + safe_run
│   ├── logging_config.py      # 结构化日志（控制台 + 文件）
│   ├── orchestrator.py        # 团队编排器：全流程 + 反馈循环
│   └── roles/
│       ├── architect.py       # 架构师：Issue → 子任务 DAG
│       ├── coder.py           # 编码者：并行 worktree + 28 种 Stub
│       ├── merge_coord.py     # 合并协调器：三方合并 + LLM 冲突调解
│       ├── reviewer.py        # 审查者：diff 审查 + 自审硬约束 + 误批探测
│       └── tester.py          # 测试者：本地/Docker 沙箱
├── cli.py                     # 命令行入口
├── tests/                     # 22 个测试（任务板/角色/编排器）
├── .github/workflows/ci.yml   # CI：3 OS × 3 Python + lint
└── requirements.txt
```

## 配置 | Configuration

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

也可以在目标仓库中放置 `.team.toml` 或 `.team.yml` 实现更细粒度的项目级配置覆盖。

## 许可 | License

MIT — 继承自 [AI Engineering from Scratch](https://github.com/rohitg00/ai-engineering-from-scratch)
