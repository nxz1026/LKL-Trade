"""账户查询：把掘金 proto 拆成模型（须先登录；未连接各函数返回空值）。"""
from __future__ import annotations

from .models import CashInfo, PositionInfo


def cash() -> CashInfo | None:
    """当前默认账户资金；未连接/失败返回 None。"""
    from gmtrade.api import get_cash
    try:
        raw = get_cash()          # 依赖 login 设置的 default_account
    except Exception:
        return None
    if raw is None:
        return None
    return CashInfo(
        account_id=raw.account_id, account_name=raw.account_name,
        nav=raw.nav, balance=raw.balance, available=raw.available,
        frozen=raw.frozen, pnl=raw.pnl)


def positions() -> list:
    """当前默认账户全部持仓。"""
    from gmtrade.api import get_positions
    try:
        rows = get_positions()
    except Exception:
        return []
    return [
        PositionInfo(
            symbol=p.symbol, volume=int(p.volume), available=int(p.available),
            cost=p.cost, vwap=p.vwap, last_price=p.last_price, fpnl=p.fpnl)
        for p in rows
    ]