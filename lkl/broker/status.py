"""委托状态：查询/枚举掘金当日委托 → 权威 OrderStatus + 成交明细。

orders.submit 与委托查询共用同一映射（_LOOKUP/_from），状态定义唯一在 orderstate，
list_status/list_orders 共用 _rows() 拉取，不重复实现循环。
"""
from __future__ import annotations

from gmtrade.api import get_orders

from lkl.broker import client
from lkl.broker.orderstate import OrderStatus
from lkl.broker.result import ExecResult

_LOOKUP = {1: OrderStatus.SUBMITTED, 2: OrderStatus.PARTIAL,
           3: OrderStatus.FILLED, 4: OrderStatus.CANCELLED,
           5: OrderStatus.CANCELLED, 6: OrderStatus.CANCELLED,
           8: OrderStatus.REJECTED, 10: OrderStatus.SUBMITTED,
           12: OrderStatus.CANCELLED}

_SIDE = {1: "买", 2: "卖"}


def _orders_list() -> list:
    return get_orders()


def _from(o) -> ExecResult:
    """委托对象 → ExecResult；终态时把状态标签作为 reason（可读性兜底）。"""
    st = _LOOKUP.get(getattr(o, "status", 0), OrderStatus.UNKNOWN)
    vol = getattr(o, "volume", 0) or 0
    filled = getattr(o, "filled_volume", 0) or 0
    return ExecResult(
        getattr(o, "order_id", "") or "",
        status=st, filled=filled, remaining=max(vol - filled, 0),
        avg_price=getattr(o, "avg_price", 0.0) or getattr(o, "price", 0.0) or 0.0,
        reason=(getattr(o, "status_msg", "") or
                (st.label if not st.retryable else "")),
    )


def _rows() -> list:
    """连接并返回今日全部委托对象（查询失败的异常原样上抛，不吞）。"""
    client.connect()
    return _orders_list()


def get_status(order_id: str) -> ExecResult:
    """按 order_id 查当日委托；查不到 NOT_FOUND。"""
    for o in _rows():
        if o.order_id == order_id or getattr(o, "cl_ord_id", "") == order_id:
            return _from(o)
    return ExecResult(order_id, OrderStatus.NOT_FOUND, reason="当日未查得该委托")


def list_status() -> list:
    """今日全部委托的 ExecResult 列表。"""
    return [_from(o) for o in _rows()]


def list_orders() -> list:
    """今日委托 → 可读字段（短ID/代码/方向/数量/价格/成交/状态标签）。"""
    rows = []
    for o in _rows():
        st = _LOOKUP.get(getattr(o, "status", 0), OrderStatus.UNKNOWN)
        rows.append({"id": o.order_id[:8], "full_id": o.order_id,
                     "symbol": o.symbol, "side": _SIDE.get(o.side, o.side),
                     "volume": o.volume, "price": o.price,
                     "filled": o.filled_volume,
                     "remaining": max((o.volume or 0) - o.filled_volume, 0),
                     "status": st.value, "status_label": st.label})
    return rows