"""trade 看板数据层：聚合账户/持仓/当日决策/尝试回报/委托 → 视图状态。

- 每张卡独立容错（P2-07）：失败给出明确错误与原因，不伪装空数据，也不拖垮整页。
- 日期一律 Asia/Shanghai（P2-04）。
- 回报按订单生命周期展示（P0-02），区分已成交/被拒/部分成交/排除。
"""
from __future__ import annotations

from dataclasses import asdict

from lkl.broker import exchange, fileio, status, trade_date


def _account() -> dict:
    from lkl.broker import info
    try:
        u = info.user_info()
        return {"account": u.account_id, "cash": asdict(u.cash) if u.cash else {},
                "positions": [asdict(p) for p in u.positions], "ok": True}
    except Exception as e:
        return {"ok": False, "note": f"{type(e).__name__}: {e}"}


def _orders() -> dict:
    try:
        return {"ok": True, "rows": status.list_orders()}
    except Exception as e:
        return {"ok": False, "note": f"{type(e).__name__}: {e}", "rows": []}


def _decisions(for_date: str) -> dict:
    try:
        return {"ok": True, "rows": [asdict(s) for s in
                                     exchange.load_decisions(for_date)]}
    except exchange.DecisionValidationError as e:
        return {"ok": False, "note": f"决策校验失败：{e}", "rows": []}
    except Exception as e:
        return {"ok": False, "note": f"{type(e).__name__}: {e}", "rows": []}


def state(for_date: str | None = None) -> dict:
    for_date = for_date or trade_date.trade_date()
    return {
        "for_date": for_date,
        "account": _account(),
        "decisions": _decisions(for_date),
        "results": exchange.load_results(for_date),
        "orders": _orders(),
        "exchange_dir": str(fileio.directory()),
    }