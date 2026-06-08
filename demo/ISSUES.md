# Demo Issues — Task Tracker 项目

以下是可以直接用来测试 Multi-Agent 团队的 Issue 列表。每个 Issue 都有明确的范围和预期结果。

---

## Issue 1: 添加标签（tag）过滤功能

**当前状态**：`list_tasks()` 只支持按 `done` 状态过滤，不支持按标签过滤。
**期望**：添加 `list_tasks(tag="urgent")` 参数，返回包含指定标签的任务。

**涉及文件**：`src/task_tracker/__init__.py`、`tests/test_task_tracker.py`

---

## Issue 2: 添加任务优先级（priority）字段

**当前状态**：Task 数据类只有 id、title、done、tags 四个字段。
**期望**：添加 `priority` 字段（int，1-5），`add_task` 允许指定优先级，`list_tasks` 支持按优先级排序。

**涉及文件**：`src/task_tracker/__init__.py`、`src/task_tracker/cli.py`、`tests/test_task_tracker.py`

---

## Issue 3: 添加数据导出功能（JSON/CSV）

**当前状态**：任务数据保存在 `~/.task_tracker.json`，没有导出功能。
**期望**：添加 `export_tasks(format="json")` 函数，支持导出为 JSON 或 CSV 格式文件。

**涉及文件**：`src/task_tracker/__init__.py`、`src/task_tracker/cli.py`

---

## Issue 4: 修复并发写入导致的数据丢失

**当前状态**：`save_tasks()` 直接写入文件，如果两个进程同时操作会丢失数据。
**期望**：使用文件锁（`fcntl` / `msvcrt`）保护写入操作，实现线程安全的持久化。

**涉及文件**：`src/task_tracker/__init__.py`

---

## Issue 5: 重构 CLI 使用 click 库

**当前状态**：CLI 使用 argparse，代码较为冗长。
**期望**：改用 click 库重写 CLI，保持相同的命令行接口。

**涉及文件**：`src/task_tracker/cli.py`、`requirements.txt`（或 `pyproject.toml`）
