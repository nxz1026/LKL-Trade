"""执行层：BrokerExecutor（掘金仿真/交易实单）。

只保留被测使用的 BrokerExecutor；已移除未接入的 Executor 协议与 ManualExecutor。
"""
from __future__ import annotations

from lkl.broker.result import ExecResult
from lkl.models.types import Signal


class BrokerExecutor:
    """掘金执行器：Signal → gmtrade 实单（本地金矿终端 127.0.0.1:7001）。"""
    def submit(self, sig: Signal, volume: int = 0) -> ExecResult:
        from lkl.broker.orders import submit
        return submit(sig, volume=volume)

    def status(self, order_id: str) -> ExecResult:
        from lkl.broker.status import get_status
        return get_status(order_id)