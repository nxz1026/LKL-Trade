"""委托结果值对象：order_id + 状态（执行层与 broker 共用，避免循环依赖）。"""
from __future__ import annotations


class ExecResult:
    def __init__(self, order_id: str, status: str) -> None:
        self.order_id, self.status = order_id, status

    def __repr__(self) -> str:
        return f"ExecResult(order_id={self.order_id!r}, status={self.status!r})"