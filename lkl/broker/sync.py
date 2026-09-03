"""lkl sim sync: 真实持仓 -> holdings.json（供 DB 对账 position 表）。"""
from __future__ import annotations

from lkl.broker import client, holdings, queries, remote


def _row(p) -> dict:
    """PositionInfo → holdings 行（code 去交易所前缀，真实仓字段齐全）。"""
    return {"code": p.symbol.rsplit(".", 1)[-1], "symbol": p.symbol,
            "volume": p.volume, "available": p.available, "cost": p.cost,
            "vwap": p.vwap, "last_price": p.last_price, "fpnl": p.fpnl}


def snapshot() -> int:
    """连终端，读真实仓并写 holdings.json；返回条数。"""
    client.connect()
    rows = [_row(p) for p in queries.positions()]
    holdings.dump(rows)
    remote.push("holdings")
    return len(rows)