"""lkl trade CLI 分发：trade [date] 一次 或 trade watch 循环盯盘。"""
from __future__ import annotations

_RETRYABLE = ("REJECTED", "NO_POSITION", "SUBMITTED", "PARTIAL",
              "NOT_FOUND", "UNKNOWN")


def run(argv: list[str]) -> int:
    """lkl trade：单次或 watch。核心逻辑见 tradeops。"""
    if argv and argv[0] == "watch":
        from lkl.broker.watch import run as watch_run
        return watch_run(argv[1:])
    from lkl.broker import exchange, governor, trade_date
    from lkl.broker.tradeops import process_once
    for_date = argv[0] if argv else trade_date.trade_date()

    ok, why = governor.allow_trade()
    if not ok:
        print(f"{for_date}: 未下单 —— {why}")
        return 0

    n = process_once(for_date)
    if n:
        print(f"{for_date}: 本轮确认成交 {n} 单")
        return 0

    # 0 = 无动作或尝试未成交——给准确原因，不再误导
    rows = exchange.load_results(for_date)
    pend = [r for r in rows if r.get("status") in _RETRYABLE]
    if pend:
        last = pend[-1]
        print(f"{for_date}: 已尝试 {len(pend)} 次未成交 "
              f"（最近: {last.get('code')} {last.get('status')} —— {last.get('reason') or '-'}），"
              f"保留可重试/待人工，详见 recon/alerts")
        return 0
    f = exchange.decision_date()
    if f is not None and f != for_date[:10]:
        print(f"⚠ decisions for_date={f} ≠ 执行日 {for_date[:10]}，已跳过（核对两端日期/同步）")
        return 0
    print(f"{for_date}: 无待执行动作（无新决策或均已成交/终态）")
    return 0