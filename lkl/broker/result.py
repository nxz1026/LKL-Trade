"""委托结果值对象：order_id + 权威状态（OrderStatus）+ 成交明细。

执行层与 broker 共用，避免循环依赖；任何状态必须是 OrderStatus 终态语义。
（对应审查 P0-02/P2-10：拒绝用布尔/裸字符串表达订单生命周期。）
"""
from __future__ import annotations

from lkl.broker.orderstate import OrderStatus


class ExecResult:
    __slots__ = ("order_id", "status", "filled", "avg_price", "remaining",
                 "reason")

    def __init__(self, order_id: str = "", status: OrderStatus = OrderStatus.UNKNOWN,
                 *, filled: int = 0, avg_price: float = 0.0,
                 remaining: int = 0, reason: str = "") -> None:
        if isinstance(status, str):
            status = OrderStatus(status)
        self.order_id = order_id or ""
        self.status = status
        self.filled = int(filled)
        self.avg_price = float(avg_price)
        self.remaining = int(remaining)
        self.reason = reason

    @property
    def ok(self) -> bool:
        """已确认成交（不是 order_id 存在）。"""
        return self.status.confirmed

    @property
    def confirmed(self) -> bool:
        return self.status.confirmed

    @property
    def terminal(self) -> bool:
        return self.status.terminal

    @property
    def retryable(self) -> bool:
        return self.status.retryable

    def to_row(self) -> dict:
        return {
            "order_id": self.order_id,
            "status": self.status.value,
            "status_label": self.status.label,
            "filled": self.filled,
            "remaining": self.remaining,
            "avg_price": self.avg_price,
            "reason": self.reason,
            "confirmed": self.ok,
        }

    def __repr__(self) -> str:
        return (f"ExecResult(order_id={self.order_id!r}, status={self.status.name}, "
                f"filled={self.filled}, remaining={self.remaining}, reason={self.reason!r})")