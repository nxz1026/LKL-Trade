"""trade 看板数据层：聚合账户/持仓/当日决策/成交回报/委托 → 视图状态。"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date

from lkl.broker import exchange, status


def _account() -> dict:
    """账户资金/持仓；终端未连则返回失败说明。"""
    from lkl.broker import info
    try:
        u = info.user_info()
        return {"account": u.account_id, "cash": asdict(u.cash) if u.cash else {},
                "positions": [asdict(p) for p in u.positions], "ok": True}
    except (ConnectionError, RuntimeError) as e:
        return {"ok": False, "note": str(e)}


def _orders() -> list:
    try:
        return status.list_orders()
    except Exception:
        return []


def state(for_date: str | None = None) -> dict:
    """当日决策/成交回报/账户/委托聚合。"""
    for_date = for_date or date.today().isoformat()
    return {
        "for_date": for_date,
        "account": _account(),
        "decisions": [asdict(s) for s in exchange.load_decisions(for_date)],
        "results": exchange.load_results(for_date),
        "orders": _orders(),
        "exchange_dir": str(exchange.fileio.directory()),
    }