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
    buy_window: str = ""               # 分析端市场买入口径标签（window），仅展示，不参与执行
    exec_: str = ""                    # exec 执行语义：OPEN_POS / CLOSE_ALL（契约字段 exec）
    volume: int = 0                    # OPEN_POS=建议股数(可自定) / CLOSE_ALL=当前持仓数(忽略)