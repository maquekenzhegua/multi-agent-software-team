"""Tests for Task Tracker."""

import json
import os
import tempfile

import task_tracker
from task_tracker import Task, add_task, list_tasks, mark_done, delete_task


def test_add_task(monkeypatch):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        monkeypatch.setattr(task_tracker, "DATA_FILE", f.name)
        task = add_task("Buy groceries")
        assert task.title == "Buy groceries"
        assert task.id == 1
        assert not task.done


def test_list_tasks(monkeypatch):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        monkeypatch.setattr(task_tracker, "DATA_FILE", f.name)
        add_task("Task 1")
        add_task("Task 2")
        tasks = list_tasks()
        assert len(tasks) == 2


def test_mark_done(monkeypatch):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        monkeypatch.setattr(task_tracker, "DATA_FILE", f.name)
        add_task("Task to complete")
        assert mark_done(1)
        tasks = list_tasks(done=True)
        assert len(tasks) == 1


def test_delete_task(monkeypatch):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        monkeypatch.setattr(task_tracker, "DATA_FILE", f.name)
        add_task("Task to delete")
        assert delete_task(1)
        assert len(list_tasks()) == 0
