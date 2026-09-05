"""trade 看板数据层：聚合账户/持仓/当日决策/尝试回报/委托 → 视图状态。

- 每张卡独立容错：失败给出明确错误与原因，不伪装空数据，也不拖垮整页。
- 日期一律 Asia/Shanghai。
- 回报按订单生命周期展示，区分已成交/被拒/部分成交/排除。
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
    """今日终端委托（LKL 自动单 + 手动单原始数据）。"""
    try:
        return {"ok": True, "rows": status.list_orders()}
    except Exception as e:
        return {"ok": False, "note": f"{type(e).__name__}: {e}", "rows": []}


def _manual_orders(for_date: str) -> dict:
    """今日手动委托回捞 manifest（含 source 标记 manual/decision）。

    数据源是 manual_orders_fetch 周期回捞的终端委托快照（含手动单与 LKL 自动单）；
    与实时 _orders 不同，此快照持久化在交换目录，即使终端查询失败也能展示当日委托。
    """
    try:
        p = fileio.latest("manual_orders")
        if not p:
            return {"ok": True, "rows": [], "note": ""}
        data = fileio.read_json_safe(p)
        if data is None:
            return {"ok": True, "rows": [], "note": "手动委托回捞文件损坏"}
        if data.get("for_date") != for_date:
            return {"ok": True, "rows": [], "note": f"暂无 {for_date} 手动委托回捞"}
        return {"ok": True, "rows": data.get("orders", [])}
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


def _merge_orders(orders: dict, manual: dict, for_date: str) -> dict:
    """合并实时委托 + 手动回捞 manifest → 统一视图（含 source 标记）。

    - 同一 order_id 以实时委托为准（状态最新），来源标记补自 manifest。
    - 仅在 manifest 出现、实时查询缺失的委托（终端查询失败时）用 manifest 行兜底。
    - 实时查询失败（_orders.ok=False）时完全回退到 manifest 视图。
    """
    live = {r.get("full_id") or r.get("order_id"): r for r in orders.get("rows", [])}
    if not orders.get("ok", False):
        src_rows = manual.get("rows", [])
        return {"ok": False, "note": orders.get("note", ""),
                "rows": src_rows, "source": "manifest"}
    src_rows = []
    for r in manual.get("rows", []):
        oid = r.get("order_id") or r.get("full_id")
        live_row = live.pop(oid, None)
        base = dict(live_row) if live_row else dict(r)
        base.setdefault("source", r.get("source", "manual"))
        src_rows.append(base)
    # 实时独有的委托（终端已查到、manifest 尚未回捞）标记为 decision/manual 未知：
    # 凡在当日 results 中出现过的 order_id 视为 LKL 自动单，否则归为手动（终端直接操作）。
    known = {t.get("order_id", "") for t in exchange.load_results(for_date)}
    for oid, r in live.items():
        src = "decision" if oid in known else "manual"
        r.setdefault("source", src)
        src_rows.append(r)
    return {"ok": True, "rows": src_rows, "source": "merged"}


def state(for_date: str | None = None) -> dict:
    for_date = for_date or trade_date.trade_date()
    orders = _orders()
    manual = _manual_orders(for_date)
    return {
        "for_date": for_date,
        "account": _account(),
        "decisions": _decisions(for_date),
        "results": exchange.load_results(for_date),
        "orders": _merge_orders(orders, manual, for_date),
        "exchange_dir": str(fileio.directory()),
    }