"""下单/委托 CLI 动作：构造 Signal 并委托，或列出今日委托（时区统一 Asia/Shanghai）。"""
from __future__ import annotations

from lkl.broker import session
from lkl.models.types import Signal
from lkl.services.execution import BrokerExecutor


def do_order(argv: list[str]) -> None:
    """lkl sim order <code> <BUY|SELL> [股数=100]（高级模式，走完整门禁/防重）。"""
    if len(argv) < 2:
        print("用法: lkl sim order <code> <BUY|SELL> [股数=100]")
        return
    code, side = argv[0].upper(), argv[1].upper()
    shares = int(argv[2]) if len(argv) > 2 else 0
    sig = Signal(confirm_date=session.now().date(), code=code, action=side)
    print(f"下单 {side} {code} -> {BrokerExecutor().submit(sig, volume=shares)}")


def list_orders() -> None:
    """列出今日全部委托及状态。"""
    from lkl.broker.status import list_status
    for row in list_status():
        print(f"  {row.order_id} {row.status}")