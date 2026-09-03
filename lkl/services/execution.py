"""执行层：Executor 协议 + Manual（不实单）+ Broker（掘金仿真实单）。"""
from __future__ import annotations

from typing import Protocol

from lkl.broker.result import ExecResult
from lkl.models.types import Signal


class Executor(Protocol):
    """执行器协议：gmtrade 等接入。"""
    def submit(self, sig: Signal) -> ExecResult: ...
    def status(self, order_id: str) -> ExecResult: ...


class ManualExecutor:
    """不委托：仅记录 SUGGESTED。"""
    def submit(self, sig: Signal) -> ExecResult:
        return ExecResult(f"manual-{sig.confirm_date}-{sig.code}", "SUGGESTED")

    def status(self, order_id: str) -> ExecResult:
        return ExecResult(order_id, "SUGGESTED")


class BrokerExecutor:
    """掘金仿真执行器：Signal → gmtrade 实单（本地金矿终端 127.0.0.1:7001）。"""
    def submit(self, sig: Signal, volume: int = 0) -> ExecResult:
        from lkl.broker.orders import submit
        return submit(sig, volume=volume)

    def status(self, order_id: str) -> ExecResult:
        from lkl.broker.status import get_status
        return get_status(order_id)