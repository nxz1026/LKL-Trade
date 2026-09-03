"""展示层：账户信息渲染成可读文本（供 cli 打印）。"""
from __future__ import annotations

from lkl.broker.models import PositionInfo, UserInfo


def render_user(u: UserInfo) -> str:
    """账户 + 资金 + 持仓 → 多行文本。"""
    lines = []
    head = [u.account_id, u.account_name or None]
    lines.append("账户 " + " ".join(x for x in head if x))
    cash = u.cash
    if cash:
        lines.append(f"  资产净值 {cash.nav:.2f} | 总资产 {cash.balance:.2f} | "
                     f"可用 {cash.available:.2f} | 冻结 {cash.frozen:.2f} | 浮盈 {cash.pnl:.2f}")
    else:
        lines.append("  资金：未取得")
    if not u.positions:
        lines.append("  持仓：空")
    else:
        lines.append("  持仓：")
        lines += [f"    {p.symbol} x{p.volume} 可用{p.available} "
                  f"成本{p.cost} 现价{p.last_price} 浮盈{p.fpnl}"
                  for p in u.positions]
    return "\n".join(lines)