"""下单策略门禁（与 gmtrade 无关，避免循环依赖/GMT 牵绊）。

- `window` 契约（对应审查 P1-02）：""/ANY/DAY 放行；MORNING/AFTERNOON 仅在对应交易
  时段放行；NONE 或未识别值 → EXCLUDED（明确不交易、不再重试、绝不下单）。
  在 tradeops 执行层与 orders.submit 双层把关——任何实现绕过都不该真下单。
- `market` 交易时段/交易日门禁（P1-03/04）：非交易日或盘外 → REJECTED（**可重试**，
  等开市再进单），绝不把「现在还没到点」当成永久排除，也不允许绕过。

返回 None=放行，否则给出一条带原因的结果（EXCLUDED=终态 / REJECTED=可重试）。
"""
from __future__ import annotations

from lkl.broker import session
from lkl.broker.orderstate import OrderStatus
from lkl.broker.result import ExecResult
from lkl.models.types import Signal

_WINDOW_FREE = {"", "ANY", "DAY"}
_WINDOW_DOOR = {"MORNING": (9, 30, 11, 30), "AFTERNOON": (13, 0, 15, 0)}


def window_verdict(sig: Signal) -> ExecResult | None:
    """window 语义门禁；None=放行，否则 EXCLUDED（终态不成交）。"""
    w = (sig.buy_window or "").strip().upper()
    if not w or w in _WINDOW_FREE:
        return None
    if w in _WINDOW_DOOR:
        h1, m1, h2, m2 = _WINDOW_DOOR[w]
        t = session.now().time()
        ok = (h1, m1) <= (t.hour, t.minute) <= (h2, m2)
        return None if ok else ExecResult(
            status=OrderStatus.EXCLUDED,
            reason=f"window={w} 不在对应交易时段，不进单")
    return ExecResult(status=OrderStatus.EXCLUDED,
                      reason=f"window={sig.buy_window} 无明确执行语义，拒绝下单")


def market_verdict(sig: Signal | None = None) -> ExecResult | None:
    """交易日/盘中门禁；非可交易 → REJECTED（可重试，等开市再进）。"""
    if session.market_open():
        return None
    return ExecResult(status=OrderStatus.REJECTED,
                      reason="非交易日或不在盘中时段，暂停自动下单")