"""单次执行核心：Signal→实单回报；去重、崩溃一致、并发互斥、绑定消费、治理门禁。

- P0-01/02：只有 FILLED 才入防重账本；REJECTED/NO_POSITION/PARTIAL 可重试。
- P0-03：先记意图再下单、重启对账，绝不重复提交。
- P0-04：单执行器锁；P0-05：只归档绑定文件身份。
- P1-08：固定顺序——先远端拉取，再选文件、校验、领取、执行。
- 治理（产品7）：默认 dry 演练不得自动下单；急诊 halt 持久；风控护栏拦截。
- v2 契约：results 行输出 action/code/ok/price/shares/order_id/reason。
"""
from __future__ import annotations

import logging
from datetime import datetime

from lkl.broker import alerts, exchange, governor, intent, ledger, policy, remote, trade_date
from lkl.broker.archiver import archive_one
from lkl.broker.cleanup import remove_archived
from lkl.broker.lock import single_executor
from lkl.broker.orderstate import OrderStatus
from lkl.broker.result import ExecResult
from lkl.models.types import Signal

log = logging.getLogger("lkl.tradeops")
MAX_ATTEMPTS = 3  # 每 ref 每日自动尝试上限


def _ref(sig: Signal) -> str:
    return f"{sig.confirm_date}|{sig.code}|{sig.action}"


def _executor():
    from lkl.services.execution import BrokerExecutor
    return BrokerExecutor()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _st(value) -> OrderStatus:
    try:
        return OrderStatus(value)
    except (ValueError, TypeError):
        return OrderStatus.UNKNOWN


def _row(sig: Signal, res: ExecResult, note: str) -> dict:
    """results 回报行（v2 契约：DB 消费 action/code/ok/price/shares/order_id/reason）。"""
    return {"ref": _ref(sig), "action": sig.action, "code": sig.code,
            "ok": res.ok, "order_id": res.order_id,
            "price": res.avg_price, "shares": res.filled,
            "status": res.status.value, "status_label": res.status.label,
            "confirmed": res.confirmed,
            "filled": res.filled, "remaining": res.remaining,
            "avg_price": res.avg_price,
            "reason": res.reason or note, "note": note,
            "traded_at": _now()}


def _remaining_wanted(sig: Signal, filled_total: int) -> int:
    if sig.action == "BUY":
        return (sig.volume or 100) - filled_total
    if sig.volume > 0:
        return max(sig.volume - filled_total, 0)
    return 0  # SELL 清仓：交 orders 按实时可用量


def _reconcile(executor) -> None:
    for ref, rec in list(intent.load().items()):
        oid = rec.get("order_id")
        if not oid:
            continue
        try:
            st = executor.status(oid)
        except Exception as e:
            log.warning("在途对账失败 ref=%s: %s", ref, e)
            continue
        if st.status is OrderStatus.NOT_FOUND:
            log.warning("在途 ref=%s 委托 %s 当日未查得，保留待核对", ref, oid)
        elif st.terminal:
            intent.finish(ref)
            if st.confirmed:
                ledger.mark([ref])


def preview(for_date: str | None = None) -> int:
    """交易前预演：打印可执行/受阻计划，不出单、不落盘。返回计划条数。"""
    for_date = for_date or trade_date.trade_date()
    with single_executor():
        remote.pull("decisions")
        src = exchange.decision_file(for_date)
        if src is None:
            print(f"{for_date}: 今日无可执行动作")
            return 0
        decisions = exchange.load_decisions(for_date, path=src)
        done = ledger.load()
        attempts = exchange.load_results(for_date)
        by_ref: dict[str, list] = {}
        for r in attempts:
            by_ref.setdefault(r["ref"], []).append(r)
        print(f"{for_date} 预演（只读，不下单）")
        count = 0
        for sig in decisions:
            ref = _ref(sig)
            reasons = []
            if ref in done:
                reasons.append("已成交")
            elif any(_st(r["status"]).terminal for r in by_ref.get(ref, [])):
                reasons.append("已达终态")
            v = policy.window_verdict(sig)
            if v is not None:
                reasons.append(v.reason)
            if intent.has(ref):
                reasons.append("在途待对账")
            qty = sig.volume or 100
            if sig.action == "BUY":
                b, why = governor.risk_block(qty, len(attempts), len({r.get("code") for r in attempts}))
                if b:
                    reasons.append(why)
            count += 1
            print(f"  {sig.action:<4} {sig.code}  拟{qty}股  "
                  + ("✓ 可执行" if not reasons else "✗ " + "；".join(reasons)))
        return count


def process_once(for_date: str | None = None, executor=None) -> int:
    """去重执行一批决策；返回本轮新确认成交条数。"""
    for_date = for_date or trade_date.trade_date()
    executor = executor or _executor()
    with single_executor():
        remote.pull("decisions")
        src = exchange.decision_file(for_date)
        if src is None:
            return 0
        try:
            ledger.load()
            intent.load()
        except (ledger.LedgerCorruptError, intent.PendingCorruptError):
            raise

        ok, why = governor.allow_trade()
        if not ok:
            log.info("治理门禁：%s（%s）", why, for_date)
            return 0

        _reconcile(executor)

        decisions = exchange.load_decisions(for_date, path=src)
        attempts = exchange.load_results(for_date)
        by_ref: dict[str, list] = {}
        for r in attempts:
            by_ref.setdefault(r["ref"], []).append(r)
        codes_today = {r.get("code") for r in attempts}

        done = ledger.load()
        new_confirmed: list[str] = []
        all_settled = True

        for sig in decisions:
            ref = _ref(sig)
            if ref in done or any(_st(r["status"]).terminal
                                  for r in by_ref.get(ref, [])):
                continue
            verdict = policy.window_verdict(sig)
            if verdict is not None:
                attempts.append(_row(sig, verdict, sig.reason))
                continue

            if intent.has(ref):
                log.info("ref=%s 已在途，本轮不重下", ref)
                all_settled = False
                continue
            retried = [r for r in by_ref.get(ref, []) if _st(r["status"]).retryable]
            if len(retried) >= MAX_ATTEMPTS:
                log.warning("ref=%s 达 %d 次仍不成，留待人工", ref, MAX_ATTEMPTS)
                all_settled = False
                continue

            filled_total = sum(r.get("filled", 0) for r in by_ref.get(ref, []))
            want = _remaining_wanted(sig, filled_total)
            if want <= 0 and sig.action == "BUY":
                all_settled = False
                continue

            if sig.action == "BUY":
                blocked, why = governor.risk_block(want, len(attempts), len(codes_today))
                if blocked:
                    log.warning("风控阻断 %s: %s", ref, why)
                    alerts.emit("WARN", f"风控拦截 {sig.code}: {why}")
                    all_settled = False
                    continue

            intent.record(ref, qty=want)
            try:
                res = executor.submit(sig, volume=want)
            except Exception as e:
                intent.finish(ref)
                log.error("下单异常 ref=%s: %s", ref, e)
                all_settled = False
                continue
            intent.record(ref, order_id=res.order_id, status=res.status.value, qty=want)

            row = _row(sig, res, sig.reason)
            attempts.append(row)
            if res.status is OrderStatus.EXCLUDED or res.status is OrderStatus.CANCELLED:
                intent.finish(ref)
            elif res.confirmed:
                intent.finish(ref)
                new_confirmed.append(ref)
            elif bool(res.order_id):
                all_settled = False
            else:
                intent.finish(ref)
                all_settled = False

        if new_confirmed:
            ledger.mark(new_confirmed)

        exchange.dump_results(for_date, attempts)
        remote.push("results")

        if all_settled and decisions:
            archive_one(src)
            remove_archived(for_date)
        return len(new_confirmed)