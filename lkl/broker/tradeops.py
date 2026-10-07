"""单次执行核心：Signal→实单回报；去重、崩溃一致、并发互斥、绑定消费、治理门禁。

- 只有 FILLED 才入防重账本；REJECTED/NO_POSITION/PARTIAL 可重试。
- 先记意图再下单、重启对账，绝不重复提交。
- 单执行器锁；只归档绑定文件身份。
- 固定顺序——先远端拉取，再选文件、校验、领取、执行。
- 治理（产品7）：默认 dry 演练不得自动下单；急诊 halt 持久；风控护栏拦截。
- v2 契约：results 行输出 action/code/ok/price/shares/order_id/reason。
- 成交即入账本（循环内即时记账）：同 ref 同日多份文件同轮不重发（#11 回归）。
"""
from __future__ import annotations

import logging

from lkl.broker import alerts, config, exchange, fileio, governor, intent, ledger, remote, remote_http, resolve, session, trade_date
from lkl.broker.archiver import archive_one, is_archived
from lkl.broker.cleanup import remove_archived, remove_archived_name
from lkl.broker.lock import single_executor
from lkl.broker.orderstate import OrderStatus
from lkl.broker.result import ExecResult
from lkl.models.types import Signal

log = logging.getLogger("lkl.tradeops")
MAX_ATTEMPTS = 3  # 每 ref 每日自动尝试上限


def _ref(sig: Signal) -> str:
    """防重/幂等的唯一键。

    ⚠️ 2026-10-07 加来源维度：`sig.source` 非空时前缀进去，ref 变
    `来源|日期|代码|动作`。接第二个上游（CPT）时，两个上游对同一只票发出的
    同向指令原本会被 `ledger` / `resolve` 当成**同一笔**——先成交的那笔让另一笔
    被防重挡住，即**静默丢单**。

    **空 source 时格式与旧版逐字一致**（`日期|代码|动作`），所以历史
    `executed.json` / `pending.json` 里的 ref 继续有效——这是不能破坏的连续性。
    """
    base = f"{sig.confirm_date}|{sig.code}|{sig.action}"
    return f"{sig.source}|{base}" if sig.source else base


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

    判定走 archiver.is_archived：归档目录按文件名时间戳落盘（可先于 for_date
    生成，如隔夜投递），查询与实际落盘路径永远一致，不再业务层自行推导。
    """
    return is_archived(src.name)


def process_once(for_date: str | None = None, executor=None) -> int:
    """去重执行当日全部决策；返回本轮新确认成交条数。

    HTTP mode (GM_REMOTE_URL set): pull decisions from oracle Trade API,
    check batch_id for idempotency, push results back via HTTP.
    SFTP mode (legacy): pull decision files from SFTP, process, push results.
    """
    for_date = for_date or trade_date.trade_date()
    executor = executor or _executor()

    # ── HTTP mode ────────────────────────────────────────────
    if config.remote_url():
        return _process_once_http(for_date, executor)

    # ── SFTP mode (legacy) ──────────────────────────────────
    return _process_once_sftp(for_date, executor)


def _process_once_http(for_date: str, executor) -> int:
    """HTTP mode: pull decisions from oracle Trade API, process, push results.

    ⚠️ 2026-10-07 加固三处（均为「接第二个上游 CPT」的前置条件）：
      1. **来源维度** `GM_SOURCE` 贯穿 ref / batch_id —— 两个上游对同一只票的
         同向指令不再互相防重（原实现会**静默丢单**）。
      2. **for_date 一致性** —— 原实现拿请求参数直接当 `confirm_date`，
         **从不校验上游回传的日期**，上游串日期时昨天的决策会被当今天执行。
      3. **契约校验复用** —— 原实现直接 `a["code"]` / `a["action"]` 取值，
         **完全绕过 `exchange._validate`**（6 位码 / action 枚举 / exec 配对 /
         volume 非负），新上游的脏数据没有第二道防线。

    校验一律放在拿 `single_executor()` 锁**之前**：坏批次不该碰到任何状态。
    """
    source = config.source()
    try:
        data = remote_http.http_pull_decisions(for_date)
    except Exception as e:
        log.warning("HTTP pull decisions failed: %s", e)
        return 0

    batch_id = data.get("batch_id", "")
    actions = data.get("actions", [])

    if not actions:
        return 0

    # ① 上游回传的 for_date 必须与请求的一致，否则整批拒绝（防串日误执行）
    got_date = str(data.get("for_date") or "")[:10]
    if got_date and got_date != for_date:
        log.error("上游 for_date=%s 与请求 %s 不一致，整批拒绝", got_date, for_date)
        alerts.emit("ERROR", f"决策日期不一致：上游 {got_date} vs 请求 {for_date}，整批拒绝")
        return 0

    # ② 复用 SFTP 模式的契约校验；任一动作不合法 → 整批中止，绝不按推测下单
    from datetime import date as date_type
    try:
        target_date = date_type.fromisoformat(for_date)
        signals = []
        for i, a in enumerate(actions):
            code, action, ex, volume = exchange._validate(a, i)
            signals.append(Signal(
                confirm_date=target_date,
                code=code,
                action=action,
                reason=a.get("reason", ""),
                buy_window=a.get("window", ""),
                exec_=ex,
                volume=volume,
                source=source,
            ))
    except exchange.DecisionValidationError as e:
        log.error("决策契约校验失败，整批拒绝（来源=%s）: %s", source or "-", e)
        alerts.emit("ERROR", f"决策契约非法（来源 {source or '-'}），整批拒绝：{e}")
        return 0

    # ③ 幂等按来源分桶：两个上游的 batch_id 空间独立
    if remote_http.is_processed(batch_id, source):
        log.info("batch %s（来源 %s）已处理，跳过", batch_id, source or "-")
        return 0

    with single_executor():
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

        file_settled = True
        for sig in signals:
            ref = _ref(sig)
            verdict = resolve.apply(verdicts, ref)
            if verdict == "skip":
                continue
            if verdict == "done":
                if ref not in done:
                    ledger.mark([ref])
                    done.add(ref)
                continue
            if verdict == "retry":
                intent.finish(ref)
                log.info("ref=%s 人工 retry，已清在途", ref)
            if ref in done or any(_st(r["status"]).terminal
                                  for r in by_ref.get(ref, [])):
                if ref in done:
                    log.warning("ref=%s 已成交，跳过防重", ref)
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
                ledger.mark([ref])
                done.add(ref)
                new_confirmed.append(ref)
            elif bool(res.order_id):
                file_settled = False
            else:
                intent.finish(ref)
                file_settled = False

        # Write local results and push via HTTP
        exchange.dump_results(for_date, attempts)
        try:
            remote_http.http_push_results({
                "batch_id": batch_id,
                "for_date": for_date,
                "source": source,
                "trades": attempts,
            })
            remote_http.mark_processed(batch_id, source)
        except Exception as e:
            log.warning("HTTP push results failed: %s", e)

    return len(new_confirmed)


def _process_once_sftp(for_date: str, executor) -> int:
    """SFTP mode (legacy): pull decision files from SFTP, process, push results."""
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
                        done.add(ref)
                    continue
                if verdict == "retry":
                    intent.finish(ref)              # 人工 retry：唯一在途释放通道，清 pending 后放行重试
                    log.info("ref=%s 人工 retry，已清在途", ref)
                if ref in done or any(_st(r["status"]).terminal
                                      for r in by_ref.get(ref, [])):
                    if ref in done:
                        log.warning("ref=%s 同日重复投递且已成交，跳过防重", ref)
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
                    ledger.mark([ref])          # 循环内即时记账：同 ref 同日多文件不重发（#11）
                    done.add(ref)
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

        if any_processed:                       # 全部已消费残留 → 无实质处理，不重写 results
            exchange.dump_results(for_date, attempts)
            remote.push("results")
        return len(new_confirmed)


def _keep_remote() -> bool:
    """GM_KEEP_REMOTE=1：最终成交/对账确认前不自动删远端决策（可追溯）。"""
    import os
    return os.environ.get("GM_KEEP_REMOTE", "") == "1"