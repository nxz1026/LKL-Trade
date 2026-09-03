"""委托状态：查询/枚举掘金当日委托，映射成中文状态与可读字段。"""
from __future__ import annotations

from gmtrade.api import get_orders

from lkl.broker import client
from lkl.broker.result import ExecResult

_LABEL = {1: "已报", 2: "部成", 3: "已成", 4: "当日收",
          5: "已撤", 6: "待撤", 8: "已拒", 10: "待报", 12: "过期"}
_SIDE = {1: "买", 2: "卖"}


def _orders_list() -> list:
    return get_orders()


def _label(status: int) -> str:
    return _LABEL.get(status, f"ST{status}")


def get_status(order_id: str) -> ExecResult:
    """按 order_id 查当日委托状态。"""
    client.connect()
    for o in _orders_list():
        if o.order_id == order_id or o.cl_ord_id == order_id:
            return ExecResult(o.order_id, _label(o.status))
    return ExecResult(order_id, "NOT_FOUND")


def list_status() -> list:
    """今日全部委托的 (id, 状态) 结果列表。"""
    client.connect()
    return [ExecResult(o.order_id, _label(o.status)) for o in _orders_list()]


def list_orders() -> list:
    """今日委托 → 可读字段（短ID/代码/方向/数量/价格/状态/完整ID）。"""
    client.connect()
    rows = []
    for o in _orders_list():
        rows.append({"id": o.order_id[:8], "full_id": o.order_id,
                     "symbol": o.symbol, "side": _SIDE.get(o.side, o.side),
                     "volume": o.volume, "price": o.price,
                     "filled": o.filled_volume,
                     "status": _label(o.status)})
    return rows