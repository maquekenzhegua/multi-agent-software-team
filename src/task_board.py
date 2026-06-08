from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator


class MsgKind(Enum):
    PLAN_REQUEST = "plan_request"
    SUBTASK = "subtask"
    DIFF_READY = "diff_ready"
    REVIEW_NEEDED = "review_needed"
    REVIEW_FEEDBACK = "review_feedback"
    APPROVED = "approved"
    TEST_NEEDED = "test_needed"
    TEST_PASSED = "test_passed"
    TEST_FAILED = "test_failed"
    REPLAN_NEEDED = "replan_needed"


@dataclass
class Msg:
    kind: MsgKind
    by: str
    to: str
    payload: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    tokens: int = 0
    span_id: str = ""
    parent_span_id: str = ""

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "kind": self.kind.value,
            "by": self.by,
            "to": self.to,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "tokens": self.tokens,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Msg:
        return cls(
            id=d["id"],
            kind=MsgKind(d["kind"]),
            by=d["by"],
            to=d["to"],
            payload=d.get("payload", {}),
            timestamp=d.get("timestamp", time.time()),
            tokens=d.get("tokens", 0),
            span_id=d.get("span_id", ""),
            parent_span_id=d.get("parent_span_id", ""),
        )


@dataclass
class Board:
    path: str
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _write_fp: object = field(default=None, repr=False)

    def __post_init__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._write_fp = open(self.path, "a", encoding="utf-8")

    def post(self, msg: Msg) -> None:
        with self._lock:
            self._write_fp.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")
            self._write_fp.flush()

    def messages(self) -> list[Msg]:
        if not os.path.exists(self.path):
            return []
        with self._lock:
            results = []
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            results.append(Msg.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                pass
            return results

    def inbox(self, role: str) -> list[Msg]:
        return [m for m in self.messages() if m.to == role or m.to == "board"]

    def by_kind(self, kind: MsgKind) -> list[Msg]:
        return [m for m in self.messages() if m.kind == kind]

    def latest_by_kind(self, kind: MsgKind) -> Msg | None:
        matches = self.by_kind(kind)
        return matches[-1] if matches else None

    def handoff_count(self) -> int:
        msgs = self.messages()
        return sum(1 for m in msgs if m.to != m.by and m.kind != MsgKind.SUBTASK)

    def tokens_by_role(self) -> dict[str, int]:
        totals: dict[str, int] = defaultdict(int)
        for m in self.messages():
            totals[m.by] += m.tokens
        return dict(totals)

    def total_tokens(self) -> int:
        return sum(self.tokens_by_role().values())

    def close(self) -> None:
        if self._write_fp:
            self._write_fp.close()

    def clear(self) -> None:
        with self._lock:
            if self._write_fp:
                self._write_fp.close()
                self._write_fp = None
            if os.path.exists(self.path):
                os.remove(self.path)
            self._write_fp = open(self.path, "a", encoding="utf-8")

    def __iter__(self) -> Iterator[Msg]:
        return iter(self.messages())

    def __len__(self) -> int:
        return len(self.messages())
