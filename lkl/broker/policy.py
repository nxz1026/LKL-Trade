"""下单策略门禁（与 gmtrade 无关，避免循环依赖/GMT 牵绊）。

- `market` 交易时段/交易日门禁：非交易日或盘外 → REJECTED（**可重试**，等开市再进单），
  绝不把「现在还没到点」当成永久排除，也不允许绕过。

返回 None=放行，否则给出一条带原因的结果（REJECTED=可重试）。

注：window 曾是执行门禁（NONE→EXCLUDED）——契约 v2 起 window 只是分析端市场买入
口径标签，无执行语义（SELL 清仓与 window=NONE 退潮期并存是正常组合），执行分发
一律看 exec（OPEN_POS/CLOSE_ALL），不再按 window 判断。
"""
from __future__ import annotations

from lkl.broker import session
from lkl.broker.orderstate import OrderStatus
from lkl.broker.result import ExecResult


def market_verdict() -> ExecResult | None:
    """交易日/盘中门禁；非可交易 → REJECTED（可重试，等开市再进）。"""
    if session.market_open():
        return None
    return ExecResult(status=OrderStatus.REJECTED,
                      reason="非交易日或不在盘中时段，暂停自动下单")