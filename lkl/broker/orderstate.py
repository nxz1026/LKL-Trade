"""订单生命周期唯一权威定义：终态/可重试/成交 判定。

所有执行/回报/看板共用此枚举，消除各处自造的状态词（en/中文、布尔 ok）。
规则：

- 只有 ``FILLED`` 是「已确认成交」——唯一允许写入防重账本 executed.json。
- ``REJECTED / NO_POSITION / PARTIAL / SUBMITTED / NOT_FOUND`` 都可自动重试，
  不入防重账本；部分成交的剩余数量必须保留，由执行层决定是否续下。
- ``CANCELLED`` 人工终结；``EXCLUDED`` 保留状态位（历史语义；window 自契约 v2 起不再
  产生 EXCLUDED，仅展示标签）→ 不再自动重试，但两者都不会被视为成交防重。
"""
from __future__ import annotations

from enum import Enum


class OrderStatus(str, Enum):
    PENDING = "PENDING"           # 待执行（未提交）
    SUBMITTED = "SUBMITTED"       # 已报，未成交
    PARTIAL = "PARTIAL"           # 部分成交，remaining>0
    FILLED = "FILLED"             # 全部成交——终态，唯一可入防重账本
    REJECTED = "REJECTED"         # 被拒（可重试）
    NO_POSITION = "NO_POSITION"   # 无持仓/可用不足（可重试）
    CANCELLED = "CANCELLED"       # 撤单/人工终（终态，不视为成交）
    EXCLUDED = "EXCLUDED"         # 决策语义排除（历史/人工），不成交且不再重试
    NOT_FOUND = "NOT_FOUND"       # 查询不到（可重试）
    UNKNOWN = "UNKNOWN"           # 兜底

    @property
    def terminal(self) -> bool:
        """不再需要自动重试的终态（成交/已撤/已排除）。"""
        return self in (OrderStatus.FILLED, OrderStatus.CANCELLED,
                        OrderStatus.EXCLUDED)

    @property
    def retryable(self) -> bool:
        """失败或未完结类——可自动重试，绝不入防重账本。"""
        return self in (OrderStatus.REJECTED, OrderStatus.NO_POSITION,
                        OrderStatus.PARTIAL, OrderStatus.SUBMITTED,
                        OrderStatus.PENDING, OrderStatus.NOT_FOUND,
                        OrderStatus.UNKNOWN)

    @property
    def confirmed(self) -> bool:
        """已确认成交——唯一允许写防重账本。"""
        return self == OrderStatus.FILLED

    @property
    def label(self) -> str:
        return _CN.get(self, str(self.value))


_CN = {
    OrderStatus.PENDING: "待执行",
    OrderStatus.SUBMITTED: "已报",
    OrderStatus.PARTIAL: "部分成交",
    OrderStatus.FILLED: "已成交",
    OrderStatus.REJECTED: "已拒",
    OrderStatus.NO_POSITION: "无持仓",
    OrderStatus.CANCELLED: "已撤",
    OrderStatus.EXCLUDED: "已排除",
    OrderStatus.NOT_FOUND: "未查得",
    OrderStatus.UNKNOWN: "未知",
}