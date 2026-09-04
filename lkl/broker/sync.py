"""lkl sim sync: 真实持仓 -> holdings.json（供 DB 对账 position 表）。

v2 契约：行含 code(无前缀)/symbol/volume/available/cost/price(=最新价)/fpnl。
"""
from __future__ import annotations

from lkl.broker import client, holdings, manual_orders, queries, remote


def _row(p) -> dict:
    """PositionInfo → holdings 行（code 无交易所前缀；price=最新参考价）。"""
    return {"code": p.symbol.rsplit(".", 1)[-1], "symbol": p.symbol,
            "volume": p.volume, "available": p.available, "cost": p.cost,
            "price": p.last_price, "vwap": p.vwap,
            "last_price": p.last_price, "fpnl": p.fpnl}


def snapshot() -> int:
    """连终端，读真实仓并写 holdings.json；返回条数。同时回捞手动委托。"""
    client.connect()
    rows = [_row(p) for p in queries.positions()]
    holdings.dump(rows)
    remote.push("holdings")
    n_orders = 0
    try:
        n_orders = manual_orders.fetch()
    except Exception as e:
        # 手动单回捞是 best-effort，不阻断持仓快照
        pass
    return len(rows)