"""账户查询：把掘金 proto 拆成模型。

查询失败必须保持失败（抛 `QueryError`）并携带原因，绝不转成空列表
——下游不得把「查询失败」当成「确实空仓」，不许据错误空仓快照下单。
"""
from __future__ import annotations

from .models import CashInfo, PositionInfo


class QueryError(RuntimeError):
    """终端/账户/数据读失败——与「真实空仓」严格区分。"""


def cash() -> CashInfo | None:
    """当前默认账户资金；未连接返回 None。"""
    from gmtrade.api import get_cash
    try:
        raw = get_cash()
    except Exception as e:
        raise QueryError(f"查询资金失败: {e}") from e
    if raw is None:
        return None
    return CashInfo(
        account_id=raw.account_id, account_name=raw.account_name,
        nav=raw.nav, balance=raw.balance, available=raw.available,
        frozen=raw.frozen, pnl=raw.pnl)


def positions() -> list:
    """当前账户全部持仓；**任何异常上抛 QueryError**（不再吞成空仓）。"""
    from gmtrade.api import get_positions
    try:
        rows = get_positions()
    except Exception as e:
        raise QueryError(f"查询持仓失败: {e}") from e
    return [
        PositionInfo(
            symbol=p.symbol, volume=int(p.volume), available=int(p.available),
            cost=p.cost, vwap=p.vwap, last_price=p.last_price, fpnl=p.fpnl)
        for p in (rows or [])
    ]