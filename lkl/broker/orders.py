"""实时下单：Signal → 掘金 gmtrade order（市价单），返回权威订单状态。

- 状态语义统一到 `OrderStatus`（消除自造布尔/中文状态词）；返回成交数量、
  均价、剩余数量与拒因。
- SELL 业务契约（契约 v2）：exec=CLOSE_ALL → 按实时可用持仓清仓（volume 只是建议，
  以当前可用量为准）；否则 `volume>0` = 指定数量（可用不足即 NO_POSITION 不下单）。
  冲突停止，绝不猜测。
- 门禁：交易日/盘中（REJECTED=可重试）。（window 自契约 v2 起不参与执行。）
- 委托→状态映射统一走 status._LOOKUP/_from（与委托查询同一权威定义，不重复两份）。
"""
from __future__ import annotations

from gmtrade.api import (
    OrderSide_Buy, OrderSide_Sell, OrderType_Market,
    PositionEffect_Open, PositionEffect_Close, order_volume,
)
from lkl.broker import client, policy, queries, status, symbol
from lkl.broker.orderstate import OrderStatus
from lkl.broker.result import ExecResult
from lkl.models.types import Signal

_DEFAULT_LOT = 100  # BUY 未给数量默认 1 手
_EFFECT = {  # Signal.action → (OrderSide, PositionEffect)
    "BUY": (OrderSide_Buy, PositionEffect_Open),
    "SELL": (OrderSide_Sell, PositionEffect_Close),
}


def _qty(sig: Signal) -> tuple[int, str]:
    """结算应下数量（BUY 默认1手；SELL 校验持仓）。返回 (shares, err)。"""
    if sig.action == "BUY":
        return (sig.volume or _DEFAULT_LOT), ""
    avail = 0
    gm = symbol.to_gm_symbol(sig.code)
    for p in queries.positions():
        if p.symbol == gm:
            avail = p.available
    if sig.exec_ == "CLOSE_ALL":
        return avail, ""               # 清仓全量：volume 只是建议，以实时可用为准
    if sig.volume > 0:
        if avail < sig.volume:
            return 0, f"SELL指令{sig.volume} > 持仓可用{avail}, 拒绝"
        return sig.volume, ""
    return avail, ""  # 未标 exec 的旧 SELL，volume=0 → 清仓


def submit(sig: Signal, volume: int = 0) -> ExecResult:
    """下市价单；返回含成交明细的权威状态。"""
    mg = policy.market_verdict()
    if mg:
        return mg
    client.connect()
    side, effect = _EFFECT[sig.action]
    shares = 0 if sig.exec_ == "CLOSE_ALL" else (volume or sig.volume)
    if shares <= 0:
        qty, err = _qty(sig)
        if err:
            return ExecResult(status=OrderStatus.NO_POSITION, reason=err)
        shares = qty
    if shares <= 0:
        return ExecResult(status=OrderStatus.NO_POSITION, reason="无可用持仓/数量为零")
    orders = order_volume(symbol.to_gm_symbol(sig.code), shares, side,
                          OrderType_Market, effect, price=0.0)
    if not orders:
        return ExecResult(status=OrderStatus.REJECTED, reason="券商拒单（无委托返回）")
    return status._from(orders[0])