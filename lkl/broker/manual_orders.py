"""手动委托回捞：从金矿终端拉当日全部委托 → 写 manual_orders manifest + 上传远端。

手动下单（股票软件终端操作）不经 decisions 链路，交易端无从感知；本模块周期性
全量读取终端当日委托（含手动单与 LKL 自动单），以 v2 契约的 results 行结构写入
`manual_orders_{YYYYMMDD_HHMMSS}.json`（Asia/Shanghai，秒级时间戳）并 push 远端，
供服务端对账手动操作。

增量幂等：仅当委托集合（order_id × status）较上次 manifest 有新增/状态变化时才
写新文件；无变化不写不传，避免盘中每轮堆积。source 区分委托来源：
- manual   —— order_id 不在当日 results（LKL 自动单）中 → 手动操作
- decision —— 已在当日 results 的 LKL 自动单（顺带全量对账，可被 DB 过滤）
"""
from __future__ import annotations

import logging
from datetime import datetime

from lkl.broker import fileio, remote, session, trade_date
from lkl.broker.status import list_orders

log = logging.getLogger("lkl.manual_orders")
_SCHEMA = 1


def _stamp() -> str:
    return datetime.now(session.TZ).strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now(session.TZ).isoformat(timespec="seconds")


def _code(symbol: str) -> str:
    return symbol.rsplit(".", 1)[-1] if "." in symbol else symbol


def _known_order_ids(day: str) -> set:
    """当日 results 中已出现的 order_id（LKL 自动单）；跨日/缺失返回空。"""
    data = fileio.read("results")
    if data.get("for_date") != day:
        return set()
    return {t.get("order_id", "") for t in data.get("trades", []) if t.get("order_id")}


def _row(o: dict, day: str, known: set) -> dict:
    code = _code(o["symbol"])
    action = "BUY" if o["side"] == "买" else "SELL"
    status = o.get("status", "UNKNOWN")
    source = "decision" if o["full_id"] in known else "manual"
    filled = int(o.get("filled") or 0)
    price = float(o.get("price") or 0)
    return {
        "action": action, "code": code,
        "ok": status == "FILLED",
        "price": price, "shares": filled,
        "order_id": o["full_id"], "reason": "",
        "status": status, "status_label": o.get("status_label", status),
        "confirmed": status == "FILLED",
        "filled": filled, "remaining": int(o.get("remaining") or 0),
        "avg_price": price,
        "note": "手动终端操作" if source == "manual" else "LKL自动单",
        "traded_at": _now_iso(),
        "source": source,
        "ref": f"{day}|{code}|{action}|{o['full_id']}",
    }


def _latest() -> tuple:
    """最新 manifest 的 (for_date, {(order_id, status)})；无/损坏返回 (None, 空)。"""
    p = fileio.latest("manual_orders")
    if not p:
        return None, set()
    data = fileio.read_json_safe(p)
    if data is None:
        return None, set()
    return (data.get("for_date"),
            {(r.get("order_id", ""), r.get("status", ""))
             for r in data.get("orders", [])})


def fetch() -> int:
    """回捞当日终端委托 → 写 manifest + push 远端；返回本次写入的委托条数（无变化 0）。

    best-effort：终端查询失败记日志返回 0，绝不抛（不影响调用方主流程）。
    """
    day = trade_date.trade_date()
    try:
        raw = list_orders()
    except Exception as e:  # noqa: BLE001
        log.warning("手动委托回捞失败（终端查询）: %s", e)
        return 0
    if not raw:
        return 0
    known = _known_order_ids(day)
    rows = [_row(o, day, known) for o in raw]
    sig = {(r["order_id"], r["status"]) for r in rows}
    prev_day, prev_sig = _latest()
    if prev_day == day and prev_sig == sig:
        return 0                      # 无新增/无状态变化 → 不写不传
    fileio.write("manual_orders",
                 {"schema": _SCHEMA, "for_date": day,
                  "generated_at": _now_iso(), "orders": rows})
    try:
        if remote.enabled():
            remote.push("manual_orders")
    except Exception as e:  # noqa: BLE001
        log.warning("manual_orders push 失败: %s", e)
    log.info("手动委托回捞 %d 条 → manual_orders_%s.json", len(rows), _stamp())
    return len(rows)
