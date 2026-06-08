"""Task Tracker CLI."""

import argparse
from task_tracker import add_task, list_tasks, mark_done, delete_task


def main():
    parser = argparse.ArgumentParser(description="Task Tracker CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("title")

    sub.add_parser("list")

    p_done = sub.add_parser("done")
    p_done.add_argument("id", type=int)

    p_del = sub.add_parser("delete")
    p_del.add_argument("id", type=int)

    args = parser.parse_args()

    if args.command == "add":
        task = add_task(args.title)
        print(f"添加任务 #{task.id}: {task.title}")
    elif args.command == "list":
        for t in list_tasks():
            status = "✓" if t.done else " "
            print(f"[{status}] #{t.id} {t.title}")
    elif args.command == "done":
        if mark_done(args.id):
            print(f"任务 #{args.id} 已完成")
        else:
            print(f"任务 #{args.id} 不存在")
    elif args.command == "delete":
        if delete_task(args.id):
            print(f"任务 #{args.id} 已删除")
        else:
            print(f"任务 #{args.id} 不存在")


if __name__ == "__main__":
    main()
