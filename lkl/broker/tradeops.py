"""单次执行核心：Signal→实单回报；去重、崩溃一致、并发互斥、绑定消费、治理门禁。

- 只有 FILLED 才入防重账本；REJECTED/NO_POSITION/PARTIAL 可重试。
- 先记意图再下单、重启对账，绝不重复提交。
- 单执行器锁；只归档绑定文件身份。
- 固定顺序——先远端拉取，再选文件、校验、领取、执行。
- 治理（产品7）：默认 dry 演练不得自动下单；急诊 halt 持久；风控护栏拦截。
- v2 契约：results 行输出 action/code/ok/price/shares/order_id/reason。
"""
from __future__ import annotations

import logging

from lkl.broker import alerts, config, exchange, fileio, governor, intent, ledger, remote, resolve, session, trade_date
from lkl.broker.archiver import archive_one
from lkl.broker.cleanup import remove_archived, remove_archived_name
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
    return session.now().isoformat(timespec="seconds")


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
    if sig.exec_ == "CLOSE_ALL":
        return 0  # 清仓全量：交 orders 按实时可用量
    if sig.volume > 0:
        return max(sig.volume - filled_total, 0)
    return 0  # 未标 exec 的旧 SELL，volume=0 → 清仓


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
    """交易前预演（产品7-1）：展示执行日/是否交易日/账户/每笔计划与阻断，不下单。"""
    for_date = for_date or trade_date.trade_date()
    with single_executor():
        remote.pull_all("decisions")
        srcs = exchange.decision_files(for_date)
        is_day = session.is_trading_day()
        acc = config.account_id() or "-"
        print(f"[预演 {for_date}] 交易日={'是' if is_day else '否'} 账户={acc} 模式={governor.state()['mode']}（只读不下单）")
        if not srcs:
            print("  无可执行动作（今日无待处理决策）")
            return 0
        done = ledger.load()
        attempts = exchange.load_results(for_date)
        by_ref: dict[str, list] = {}
        for r in attempts:
            by_ref.setdefault(r["ref"], []).append(r)
        prices = _price_map()
        count = 0
        for src in srcs:                            # 升序展示，与执行顺序一致
            decisions = exchange.load_decisions(for_date, path=src)
            for sig in decisions:
                ref = _ref(sig)
                reasons = []
                if ref in done:
                    reasons.append("已成交")
                elif any(_st(r["status"]).terminal for r in by_ref.get(ref, [])):
                    reasons.append("已达终态")
                if intent.has(ref):
                    reasons.append("在途待对账")
                qty = sig.volume or 100
                est = ""
                if sig.action == "BUY" and prices.get(sig.code):
                    est = f" 约占用 ¥{qty * prices[sig.code]:,.0f}@{prices[sig.code]}"
                if sig.action == "BUY":
                    b, why = governor.risk_block(qty, len(attempts), len({r.get("code") for r in attempts}))
                    if b:
                        reasons.append(why)
                count += 1
                print(f"  {sig.action:<4} {sig.code}  拟{qty}股{est}  "
                      + ("✓ 可执行" if not reasons else "✗ " + "；".join(reasons)))
        return count



def _price_map() -> dict:
    """已知最新价（持仓快照/实时持仓），用于预演资金占用粗估。"""
    out = {}
    for p in _try_positions():
        code = p.symbol.rsplit(".", 1)[-1]
        out[code] = p.last_price or 0.0
    return out


def _try_positions() -> list:
    """预演/价格粗估用持仓；查询失败记日志并返回空（只读路径，不阻断）。"""
    try:
        from lkl.broker import queries
        return queries.positions()
    except Exception as e:
        log.warning("持仓查询失败（预演按空仓估算）: %s", e)
        return []


def _consumed_archived(src) -> bool:
    """archive/ 已存在同名决策 → 该决策已消费归档，禁止二次处理。

    防线：即使旧守卫（remove_archived 的 pull 落盘）或外部渠道把已归档决策的
    同名副本再次放进交换目录，也绝不重处理/重发 results（双份 results bug）。
    """
    day = src.name.split("_")[1]
    arch = fileio.directory() / "archive" / f"{day[:4]}-{day[4:6]}-{day[6:]}"
    return (arch / src.name).exists()


def process_once(for_date: str | None = None, executor=None) -> int:
    """去重执行当日全部决策文件；返回本轮新确认成交条数。

    顺序保证：一次拉取远端**全部** decisions，按文件名时间**升序**（旧→新）逐份
    处理——同一 code 的多份决策严格按投递顺序执行（先 BUY 后 SELL，绝不倒序）。
    每份文件独立结算：该份全部 settle → 归档本地 + 删远端；未 settle（在途/重试/
    风控）→ 保留待下轮。results 跨文件累积，轮末一次落盘。
    """
    for_date = for_date or trade_date.trade_date()
    executor = executor or _executor()
    with single_executor():
        remote.pull_all("decisions")
        srcs = exchange.decision_files(for_date)
        if not srcs:
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

        attempts = exchange.load_results(for_date)
        by_ref: dict[str, list] = {}
        for r in attempts:
            by_ref.setdefault(r["ref"], []).append(r)
        codes_today = {r.get("code") for r in attempts}

        done = ledger.load()
        new_confirmed: list[str] = []
        verdicts = resolve.load()
        any_processed = False

        for src in srcs:                            # 升序：先投递的先执行
            if _consumed_archived(src):
                archive_one(src)                    # 已消费残留副本收进 archive(_1)
                log.info("决策 %s 已消费归档，残留已回收，跳过二次处理", src.name)
                continue
            any_processed = True
            decisions = exchange.load_decisions(for_date, path=src)
            file_settled = True
            for sig in decisions:
                ref = _ref(sig)
                verdict = resolve.apply(verdicts, ref)
                if verdict == "skip":
                    continue                        # 人工 ignore：不自动下单
                if verdict == "done":
                    if ref not in done:
                        ledger.mark([ref])          # 人工 complete：按成交防重
                    continue
                if verdict == "retry":
                    intent.finish(ref)              # 人工 retry：唯一在途释放通道，清 pending 后放行重试
                    log.info("ref=%s 人工 retry，已清在途", ref)
                if ref in done or any(_st(r["status"]).terminal
                                      for r in by_ref.get(ref, [])):
                    continue

                if intent.has(ref):
                    log.info("ref=%s 已在途，本轮不重下", ref)
                    file_settled = False
                    continue
                retried = [r for r in by_ref.get(ref, []) if _st(r["status"]).retryable]
                if len(retried) >= MAX_ATTEMPTS:
                    log.warning("ref=%s 达 %d 次仍不成，留待人工", ref, MAX_ATTEMPTS)
                    file_settled = False
                    continue

                filled_total = sum(r.get("filled", 0) for r in by_ref.get(ref, []))
                want = _remaining_wanted(sig, filled_total)
                if want <= 0 and sig.action == "BUY":
                    file_settled = False
                    continue

                if sig.action == "BUY":
                    blocked, why = governor.risk_block(want, len(attempts), len(codes_today))
                    if blocked:
                        log.warning("风控阻断 %s: %s", ref, why)
                        alerts.emit("WARN", f"风控拦截 {sig.code}: {why}")
                        file_settled = False
                        continue

                intent.record(ref, qty=want)
                try:
                    res = executor.submit(sig, volume=want)
                except Exception as e:
                    intent.finish(ref)
                    log.error("下单异常 ref=%s: %s", ref, e)
                    file_settled = False
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
                    file_settled = False
                else:
                    intent.finish(ref)
                    file_settled = False

            if file_settled:
                archive_one(src)
                if not _keep_remote():
                    remove_archived_name(src.name)

        if new_confirmed:
            ledger.mark(new_confirmed)

        if any_processed:                       # 全部已消费残留 → 无实质处理，不重写 results
            exchange.dump_results(for_date, attempts)
            remote.push("results")
        return len(new_confirmed)


def _keep_remote() -> bool:
    """GM_KEEP_REMOTE=1：最终成交/对账确认前不自动删远端决策（可追溯）。"""
    import os
    return os.environ.get("GM_KEEP_REMOTE", "") == "1"