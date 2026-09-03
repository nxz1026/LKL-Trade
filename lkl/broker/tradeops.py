"""单次执行核心：Signal→实单结果行；账本+今日 results 去重；合并写 results.json。"""
from __future__ import annotations

from datetime import datetime

from lkl.broker import exchange, ledger, remote, trade_date
from lkl.models.types import Signal
from lkl.services.execution import BrokerExecutor


def _ref(sig: Signal) -> str:
    return f"{sig.confirm_date}|{sig.code}|{sig.action}"


def _run_one(sig: Signal) -> dict:
    """单条 Signal 实单 → results.json 一行。"""
    res = BrokerExecutor().submit(sig, volume=sig.volume)
    ok = bool(res.order_id)
    status = "REJECTED" if not ok else (res.status or "SUBMITTED")
    return {"ref": _ref(sig), "action": sig.action, "code": sig.code,
            "ok": ok, "order_id": res.order_id, "status": status,
            "note": sig.reason, "traded_at": _now()}


def process_once(for_date: str | None = None) -> int:
    """去重执行并合并回报；返回本轮新成交数。"""
    for_date = for_date or trade_date.trade_date()
    remote.pull("decisions.json")
    decisions = exchange.load_decisions(for_date)
    existing = exchange.load_results(for_date)
    done = {r["ref"] for r in existing} | ledger.load()
    todo = [s for s in decisions if _ref(s) not in done]
    new = [item for s in todo if (item := _run_one(s))]
    if new:
        exchange.dump_results(for_date, existing + new)
        ledger.mark(item["ref"] for item in new)
        remote.push("results.json")
    return len(new)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")