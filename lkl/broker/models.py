"""交易桥接数据模型：资金/持仓/账户基础信息（纯数据，贴近掘金 proto 字段）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CashInfo:
    """账户资金（get_cash 关键字段）。"""
    account_id: str = ""
    account_name: str = ""
    nav: float = 0.0        # 资产净值
    balance: float = 0.0    # 总资产
    available: float = 0.0  # 可用资金
    frozen: float = 0.0     # 冻结资金
    pnl: float = 0.0        # 浮动盈亏


@dataclass
class PositionInfo:
    """单只持仓。"""
    symbol: str = ""
    volume: int = 0         # 持仓数量
    available: int = 0      # 可用数量
    cost: float = 0.0       # 持仓成本
    vwap: float = 0.0       # 成交均价
    last_price: float = 0.0
    fpnl: float = 0.0       # 浮动盈亏


@dataclass
class UserInfo:
    """基本用户信息：账户 + 资金 + 持仓。"""
    account_id: str = ""
    account_name: str = ""
    cash: CashInfo | None = None
    positions: list = field(default_factory=list)