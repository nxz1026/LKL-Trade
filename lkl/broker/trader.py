"""lkl trade CLI 分发：trade [date] 一次 或 trade watch 循环盯盘。"""
from __future__ import annotations

from datetime import date


def run(argv: list[str]) -> int:
    """lkl trade：单次或 watch。核心逻辑见 tradeops。"""
    if argv and argv[0] == "watch":
        from lkl.broker.watch import run as watch_run
        return watch_run(argv[1:])
    from lkl.broker import exchange, trade_date
    from lkl.broker.tradeops import process_once
    for_date = argv[0] if argv else trade_date.trade_date()
    n = process_once(for_date)
    if not n:
        f = exchange.decision_date()
        if f is not None and f != for_date[:10]:
            print(f"⚠ decisions.json for_date={f} ≠ 执行日 {for_date[:10]}，已跳过（核对两端日期/同步）")
        else:
            print(f"{for_date}: 无待执行或均已执行")
    else:
        print(f"{for_date}: 新执行 {n} 单")
    return 0