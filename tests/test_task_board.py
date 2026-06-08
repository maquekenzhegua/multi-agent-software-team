from __future__ import annotations

import json
import os
import tempfile
import threading

from src.task_board import Board, Msg, MsgKind


def test_post_and_read():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        board = Board(path)
        msg = Msg(MsgKind.PLAN_REQUEST, by="architect", to="board",
                  payload={"summary": "测试"}, tokens=100)
        board.post(msg)
        board.close()

        board2 = Board(path)
        msgs = board2.messages()
        assert len(msgs) == 1
        assert msgs[0].kind == MsgKind.PLAN_REQUEST
        assert msgs[0].by == "architect"
        assert msgs[0].payload["summary"] == "测试"
        assert msgs[0].id == msg.id
        board2.close()
    finally:
        os.unlink(path)


def test_inbox_filtering():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        board = Board(path)
        board.post(Msg(MsgKind.SUBTASK, by="architect", to="coder-A"))
        board.post(Msg(MsgKind.SUBTASK, by="architect", to="coder-B"))
        board.post(Msg(MsgKind.DIFF_READY, by="coder-A", to="merge_coord"))
        board.close()

        board2 = Board(path)
        inbox_a = board2.inbox("coder-A")
        assert len(inbox_a) == 1
        assert inbox_a[0].to == "coder-A"

        inbox_board = board2.inbox("board")
        assert len(inbox_board) == 0  # SUBTASK goes to coders, not "board"
        board2.close()
    finally:
        os.unlink(path)


def test_by_kind():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        board = Board(path)
        board.post(Msg(MsgKind.PLAN_REQUEST, by="architect", to="board"))
        board.post(Msg(MsgKind.DIFF_READY, by="coder-A", to="merge_coord"))
        board.post(Msg(MsgKind.DIFF_READY, by="coder-B", to="merge_coord"))
        board.post(Msg(MsgKind.APPROVED, by="reviewer", to="tester"))
        board.close()

        board2 = Board(path)
        diffs = board2.by_kind(MsgKind.DIFF_READY)
        assert len(diffs) == 2
        assert diffs[0].by == "coder-A"
        assert diffs[1].by == "coder-B"
        board2.close()
    finally:
        os.unlink(path)


def test_handoff_count():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        board = Board(path)
        board.post(Msg(MsgKind.PLAN_REQUEST, by="architect", to="board"))
        board.post(Msg(MsgKind.DIFF_READY, by="coder-A", to="merge_coord"))
        board.post(Msg(MsgKind.REVIEW_FEEDBACK, by="reviewer", to="coder-A"))
        board.post(Msg(MsgKind.TEST_PASSED, by="tester", to="pr_opener"))
        board.close()

        board2 = Board(path)
        assert board2.handoff_count() == 4
        board2.close()
    finally:
        os.unlink(path)


def test_tokens_by_role():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        board = Board(path)
        board.post(Msg(MsgKind.PLAN_REQUEST, by="architect", to="board", tokens=500))
        board.post(Msg(MsgKind.DIFF_READY, by="coder-A", to="merge_coord", tokens=300))
        board.post(Msg(MsgKind.DIFF_READY, by="coder-B", to="merge_coord", tokens=400))
        board.close()

        board2 = Board(path)
        tokens = board2.tokens_by_role()
        assert tokens["architect"] == 500
        assert tokens["coder-A"] == 300
        assert tokens["coder-B"] == 400
        assert board2.total_tokens() == 1200
        board2.close()
    finally:
        os.unlink(path)


def test_concurrent_writes():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        board = Board(path)
        errors = []

        def writer(role_name: str, count: int):
            try:
                for i in range(count):
                    board.post(Msg(MsgKind.DIFF_READY, by=role_name,
                                   to="merge_coord", payload={"idx": i}))
            except Exception as e:
                errors.append(f"{role_name}: {e}")

        threads = [
            threading.Thread(target=writer, args=(f"coder-{chr(65+i)}", 10))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发写入错误: {errors}"
        board.close()

        board2 = Board(path)
        msgs = board2.messages()
        assert len(msgs) == 40, f"预期 40 条消息，实际 {len(msgs)}"
        board2.close()
    finally:
        os.unlink(path)


def test_clear():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        board = Board(path)
        board.post(Msg(MsgKind.PLAN_REQUEST, by="architect", to="board"))
        board.close()
        assert os.path.exists(path)

        board2 = Board(path)
        board2.clear()
        assert len(board2.messages()) == 0
        board2.close()
    finally:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except PermissionError:
            pass


def test_message_roundtrip():
    msg = Msg(
        kind=MsgKind.DIFF_READY, by="coder-A", to="merge_coord",
        payload={"subtask": "parser", "lines": 42}, tokens=3200,
        span_id="span-001", parent_span_id="span-root",
    )
    d = msg.to_dict()
    restored = Msg.from_dict(d)
    assert restored.kind == MsgKind.DIFF_READY
    assert restored.by == "coder-A"
    assert restored.to == "merge_coord"
    assert restored.payload["subtask"] == "parser"
    assert restored.payload["lines"] == 42
    assert restored.tokens == 3200
    assert restored.span_id == "span-001"
    assert restored.parent_span_id == "span-root"
