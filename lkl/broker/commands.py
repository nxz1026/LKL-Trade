"""下单/委托 CLI 动作：构造 Signal 并委托，或列出今日委托（时区统一 Asia/Shanghai）。"""
from __future__ import annotations

from lkl.broker import session
from lkl.models.types import Signal
from lkl.services.execution import BrokerExecutor


def do_order(argv: list[str]) -> None:
    """lkl sim order <code> <BUY|SELL> [股数] --force（高级手动，须显式确认）。

    绕过策略文件与整批幂等，仅作诊断；默认拒绝，须 --force 才执行。"""
    if "--force" not in argv or len(argv) < 3:
        print("用法: lkl sim order <code> <BUY|SELL> [股数] --force   # 高级手动，需显式 --force")
        return
    argv = [a for a in argv if a != "--force"]
    code, side = argv[0].upper(), argv[1].upper()
    shares = int(argv[2]) if len(argv) > 2 else 0
    print("[高级手动] 绕过策略校验/整批防重，仅限诊断使用")
    sig = Signal(confirm_date=session.now().date(), code=code, action=side)
    print(f"下单 {side} {code} -> {BrokerExecutor().submit(sig, volume=shares)}")


def list_orders() -> None:
    """列出今日全部委托及状态。"""
    from lkl.broker.status import list_status
    for row in list_status():
        print(f"  {row.order_id} {row.status}")