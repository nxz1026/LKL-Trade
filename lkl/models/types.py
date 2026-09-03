"""LKL-Trade：交易端独立仓（掘金仿真实单 + JSON 通道 + 看板）。

broker 依赖的领域模型最小子集（Signal/Position，含 volume）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Signal:
    """交易动作：BUY/SELL。confirm_date=执行日；code 无交易所前缀。"""
    confirm_date: date
    code: str
    action: str                        # BUY / SELL
    reason: str = ""
    buy_window: str = ""
    checklist: list = field(default_factory=list)
    status: str = "SUGGESTED"
    volume: int = 0                      # 0 = 默认(BUY 1手 / SELL 持仓量)
    id: int | None = None


@dataclass
class Position:
    """持仓记录（本地回显用，DB 侧为权威）。"""
    code: str
    entry_date: date
    entry_price: float
    shares: int
    status: str = "OPEN"
    note: str = ""
    closed_date: date | None = None
    close_price: float | None = None
    id: int | None = None