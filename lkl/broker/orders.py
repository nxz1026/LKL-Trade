"""实时下单：Signal → 掘金 gmtrade order_volume（市价单）。

BUY 默认 1 手(100 股)；SELL 平掉持仓可用量。执行前须本地金矿终端已连账户。
委托状态查询见 status.py。
"""
from __future__ import annotations

from gmtrade.api import (
    OrderSide_Buy, OrderSide_Sell, OrderType_Market,
    PositionEffect_Open, PositionEffect_Close, order_volume,
)
from lkl.broker import client, queries, symbol
from lkl.broker.result import ExecResult
from lkl.models.types import Signal

_STATUS = {3: "FILLED", 1: "SUBMITTED", 2: "PARTIAL", 8: "REJECTED"}
_DEFAULT_LOT = 100  # BUY 默认 1 手
_EFFECT = {  # Signal.action → (OrderSide, PositionEffect)
    "BUY": (OrderSide_Buy, PositionEffect_Open),
    "SELL": (OrderSide_Sell, PositionEffect_Close),
}


def _lot(sig: Signal) -> int:
    """SELL 用持仓可用量；BUY 默认 1 手。"""
    if sig.action != "SELL":
        return _DEFAULT_LOT
    gm = symbol.to_gm_symbol(sig.code)
    for p in queries.positions():
        if p.symbol == gm and p.available > 0:
            return p.available
    return 0


def submit(sig: Signal, volume: int = 0) -> ExecResult:
    """按 Signal 下单；订单 id 为空=未成交/无持仓。"""
    client.connect()
    side, effect = _EFFECT[sig.action]
    shares = volume or _lot(sig)
    if shares <= 0:
        return ExecResult("", "NO_POSITION")
    orders = order_volume(symbol.to_gm_symbol(sig.code), shares, side,
                          OrderType_Market, effect, price=0.0)
    if not orders:
        return ExecResult("", "REJECTED")
    o = orders[0]
    return ExecResult(o.order_id, _STATUS.get(o.status, "SUBMITTED"))