# Contributing

欢迎贡献！无论是 Bug 修复、功能增强还是文档改进。

## 开发环境

```bash
git clone <repo-url>
cd "Multi-Agent Software Engineering Team"
pip install -r requirements.txt
```

## 运行测试

```bash
pytest tests/ -v

# 仅运行特定模块的测试
pytest tests/test_task_board.py -v
pytest tests/test_roles.py -v
pytest tests/test_orchestrator.py -v
```

## 代码风格

- 代码无注释 — 通过命名和结构自解释
- 类型标注：所有公共方法使用 `from __future__ import annotations` 和完整类型标注
- 使用 `dataclass` 定义数据类
- 公共 API 函数签名后不添加类型注释（使用 docstring 或 annotations）

## 添加新角色

1. 在 `src/roles/` 下创建新文件
2. 实现角色类（参考现有角色结构）
3. 提供 `create_stub_*()` 工厂函数用于测试
4. 在 `src/orchestrator.py` 中集成
5. 在 `tests/` 中添加测试

## 添加新 LLM 供应商

1. 在 `src/config.py` 的 `ModelProvider` 枚举中添加
2. 在 `src/llm.py` 的 `LLMClient` 中添加 `_{provider}_chat()` 方法
3. 添加 API Key 环境变量映射

## 提交规范

- 一个提交只做一件事
- 提交信息描述「为什么」而非「是什么」
- PR 标题简洁（70 字符以内），详情写在描述中
- 确保所有测试通过后再提交
