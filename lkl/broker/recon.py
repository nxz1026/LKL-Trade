"""对账（产品7 第8条：委托/成交/持仓/策略四源一致）。

本地可观测硬校验：decisions(策略) × results/attempts(成交语义) × ledger(已成交防重)
× holdings(真仓快照) + orders(当日委托, 可得时)。每只决策给出 一致/不一致/待处理。
DB 侧另做多用户合并跨源统一核对。
"""
from __future__ import annotations

import os

from lkl.broker import exchange, holdings, ledger, trade_date
from lkl.broker.orderstate import OrderStatus

_TERMINAL = {s.value for s in OrderStatus if s.terminal}


def _terminal(st: str) -> bool:
    return st in _TERMINAL


def _holdings_by_code() -> dict:
    out = {}
    for p in holdings.load():
        out[str(p.get("code", "") or "").strip()] = int(p.get("volume", 0) or 0)
    return out


def _flag(name: str) -> bool:
    return bool(os.environ.get(name))


def _orders_map() -> dict:
    try:
        from lkl.broker.status import list_orders
        return {r["full_id"]: r.get("status_label") or r.get("status", "")
                for r in list_orders()}
    except Exception:
        return {}


def reconcile(for_date: str | None = None) -> dict:
    for_date = for_date or trade_date.trade_date()
    src = exchange.decision_file(for_date)
    decisions = exchange.load_decisions(for_date, path=src) if src else []
    done = ledger.load()
    attempts = exchange.load_results(for_date)
    by_ref: dict[str, list] = {}
    for r in attempts:
        by_ref.setdefault(r["ref"], []).append(r)
    pos = _holdings_by_code()
    # 委托核验可选（需登录终端），默认关闭避免每次看板轮询触发登录
    orders = _orders_map() if _flag("GM_RECON_ORDERS") else {}

    rows, ok, warn = [], 0, 0
    for sig in decisions:
        ref = f"{sig.confirm_date}|{sig.code}|{sig.action}"
        outs = by_ref.get(ref, [])
        latest = outs[-1] if outs else None
        detail = (latest or {}).get("reason") or ""
        if ref in done:
            if sig.action == "BUY" and pos.get(sig.code, 0) <= 0:
                status, lvl = "成交但持仓缺失", "warn"
                detail = detail or "已成交却无持仓"
            elif sig.action == "SELL" and pos.get(sig.code, 0) > 0:
                status, lvl = "应清仓仍持仓", "warn"
                detail = f"应清仓仍有 {pos[sig.code]} 股"
            else:
                status, lvl = "一致", "ok"
            oid = (latest or {}).get("order_id", "")
            if oid and orders and oid not in orders:
                status, lvl, detail = "委托缺口", "warn", f"成交单 {oid} 未见券商当日委托"
        elif (latest or {}).get("confirmed"):
            status, lvl = "一致", "ok"
        elif outs and _terminal(outs[-1]["status"]):
            status, lvl = ("已排除", "ok") if outs[-1]["status"] == "EXCLUDED" else ("终态未成", "warn")
        else:
            status, lvl = "待处理", "warn"
        rows.append({"action": sig.action, "code": sig.code,
                     "status": status, "level": lvl, "note": detail})
        ok += (lvl == "ok")
        warn += (lvl != "ok")

    return {"for_date": for_date,
            "summary": {"ok": ok, "warn": warn, "total": len(decisions)},
            "rows": rows}


def run(for_date: str | None = None) -> int:
    r = reconcile(for_date)
    print(f"{r['for_date']} 对账：一致 {r['summary']['ok']} / 异常 {r['summary']['warn']} / 共 {r['summary']['total']}")
    for row in r["rows"]:
        mark = "✓" if row["level"] == "ok" else "!"
        print(f"  {mark} {row['action']:<4} {row['code']}  {row['status']}  {row['note']}")
    return 0 if r["summary"]["warn"] == 0 else 1