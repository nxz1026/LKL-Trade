"""broker 依赖的领域模型最小子集（Signal；Position 不再需要——持仓用 broker 侧 PositionInfo）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Signal:
    """交易动作：BUY/SELL。confirm_date=执行日；code 无交易所前缀。"""
    confirm_date: date
    code: str
    action: str                        # BUY / SELL
    reason: str = ""
    buy_window: str = ""
    volume: int = 0                      # BUY=0 自定 / SELL=建议股数