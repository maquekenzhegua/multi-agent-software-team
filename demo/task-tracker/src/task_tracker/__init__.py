"""Task Tracker — a simple CLI task manager (demo project for multi-agent team)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

DATA_FILE = os.path.expanduser("~/.task_tracker.json")


@dataclass
class Task:
    id: int
    title: str
    done: bool = False
    tags: list[str] = field(default_factory=list)


def load_tasks() -> list[Task]:
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r") as f:
        raw = json.load(f)
    return [Task(**r) for r in raw]


def save_tasks(tasks: list[Task]) -> None:
    with open(DATA_FILE, "w") as f:
        json.dump([t.__dict__ for t in tasks], f, indent=2)


def add_task(title: str, tags: list[str] | None = None) -> Task:
    tasks = load_tasks()
    next_id = max((t.id for t in tasks), default=0) + 1
    task = Task(id=next_id, title=title, tags=tags or [])
    tasks.append(task)
    save_tasks(tasks)
    return task


def list_tasks(done: bool | None = None) -> list[Task]:
    tasks = load_tasks()
    if done is not None:
        return [t for t in tasks if t.done == done]
    return tasks


def mark_done(task_id: int) -> bool:
    tasks = load_tasks()
    for t in tasks:
        if t.id == task_id:
            t.done = True
            save_tasks(tasks)
            return True
    return False


def delete_task(task_id: int) -> bool:
    tasks = load_tasks()
    filtered = [t for t in tasks if t.id != task_id]
    if len(filtered) < len(tasks):
        save_tasks(filtered)
        return True
    return False
