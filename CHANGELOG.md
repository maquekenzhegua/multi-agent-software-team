# Changelog

## [1.0.0] — 2026-06-07

### 新增
- 5 角色多 Agent 软件工程团队：架构师、编码者（并行）、合并协调器、审查者、测试者
- A2A 类型化消息任务板（JSONL 文件存储，线程安全）
- 多供应商 LLM 抽象层：Anthropic（Claude）、OpenAI（GPT）、Google（Gemini）
- Token 账本和交接追踪系统，自动计算 token 放大率
- 并行编码执行（ThreadPoolExecutor），每个编码者在独立 git worktree 中工作
- 三方合并协调器，支持 LLM 调解合并冲突
- 代码审查者硬约束：不能审查自己创作的代码
- Bug 注入探测：可配置的误批率测量
- Docker 沙箱测试支持
- CLI：`team run`、`team eval`（SWE-bench 模式）、`team baseline`
- 动态 Stub 模式：无需 API Key 即可测试完整流程
- 预算上限强制执行（按角色 + 总计）
- 结构化日志系统（logging 模块，支持文件和控制台输出）
- LLM 调用指数退避重试（3 次，1/2/4 秒间隔）
- 22 个单元测试和集成测试
- GitHub Actions CI（3 操作系统 × 3 Python 版本 + lint 检查）
