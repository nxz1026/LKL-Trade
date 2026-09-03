"""单次执行核心：Signal→实单结果行；账本+当日 results 去重；消费后归档决策+删远端。"""
from __future__ import annotations

from datetime import datetime

from lkl.broker import exchange, fileio, ledger, remote, trade_date
from lkl.broker.archiver import consume
from lkl.broker.cleanup import remove_archived
from lkl.models.types import Signal
from lkl.services.execution import BrokerExecutor


def _ref(sig: Signal) -> str:
    return f"{sig.confirm_date}|{sig.code}|{sig.action}"


def _run_one(sig: Signal) -> dict:
    res = BrokerExecutor().submit(sig, volume=sig.volume)
    ok = bool(res.order_id)
    status = "REJECTED" if not ok else (res.status or "SUBMITTED")
    return {"ref": _ref(sig), "action": sig.action, "code": sig.code,
            "ok": ok, "order_id": res.order_id, "status": status,
            "note": sig.reason, "traded_at": _now()}


def process_once(for_date: str | None = None) -> int:
    """去重执行；消费后归档决策副本并删远端。"""
    for_date = for_date or trade_date.trade_date()
    if fileio.latest("decisions") is None:  # 已消费归档
        return 0
    remote.pull("decisions")
    if exchange.decision_date() != for_date:  # 未来日决策留待执行,不消费
        return 0
    decisions = exchange.load_decisions(for_date)
    existing = exchange.load_results(for_date)
    done = {r["ref"] for r in existing} | ledger.load()
    todo = [s for s in decisions if _ref(s) not in done]
    new = [item for s in todo if (item := _run_one(s))]
    if new:
        ledger.mark(item["ref"] for item in new)
    exchange.dump_results(for_date, existing + new)  # 空执行也回写
    remote.push("results")
    if fileio.latest("decisions") is not None:  # 消费即归档+删远端
        consume("decisions", for_date)
        remove_archived(for_date)
    return len(new)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")