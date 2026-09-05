"""调度：盘内执行当日决策；12:01-12:59/17:30-18:01 每分拉取；未来日留至次日执行。

主循环单轮失败必须**记录并继续**；写分级心跳
（last_success + 各活动时间戳：拉取/下单/快照/账户），终端离线与凭证缺失会告警。
"""
from __future__ import annotations
import json
import logging
import time
from datetime import datetime

from lkl.broker import alerts, config, fileio, gate, governor, intent, ledger, remote, schedule, session
from lkl.broker.archiver import pack
from lkl.broker.cleanup import remove_archived
from lkl.broker.sync import snapshot
from lkl.broker.tradeops import process_once

log = logging.getLogger("lkl.supervisor")
_RETRY, _MIN = 30, 60
_OFFLINE_ALERTED = {"v": False}   # 离线告警去重（状态翻转才发）


def _now() -> str:
    return datetime.now(session.TZ).isoformat(timespec="seconds")


def _heartbeat(activity: str = "", note: str = "") -> None:
    """activity ∈ pull|order|snapshot|connect|account。写分级心跳。"""
    try:
        hb = json.loads((config.trade_dir() / "heartbeat.json")
                        .read_text(encoding="utf-8")) if (config.trade_dir() / "heartbeat.json").exists() else {}
    except Exception:
        hb = {}
    hb["last_success"] = _now()
    hb["note"] = note
    if activity:
        hb[f"last_{activity}"] = _now()
    try:
        fileio.atomic_write(config.trade_dir() / "heartbeat.json",
                            json.dumps(hb, ensure_ascii=False))
    except OSError:
        pass


def _daily(day: str) -> None:
    try:
        pack(day)
    except Exception as e:  # noqa: BLE001
        log.warning("归档失败: %s", e)
    try:
        remove_archived(day)
    except Exception as e:  # noqa: BLE001
        log.warning("远端清理失败: %s", e)
    if gate.wait(120):
        try:
            n = snapshot()
            log.info("持仓快照→ %s 条", n)
            _heartbeat("snapshot", f"快照 {n} 条")
        except Exception as e:  # noqa: BLE001
            log.warning("快照失败: %s", e)
            alerts.emit("WARN", f"持仓快照失败：{e}")
    from lkl.broker.audit import run as a
    try:
        ok = a()
        log.info("check=%s", "OK" if ok == 0 else "异常")
        if ok != 0:
            alerts.emit("WARN", "trade check 发现不一致/缺文件")
    except Exception as e:  # noqa: BLE001
        log.warning("check 异常: %s", e)


def run(argv: list[str]) -> int:
    interval = max(int(argv[0]) if argv and argv[0].isdigit() else 60, 5)
    today = None
    while True:
        try:
            dt = session.now()
            day = dt.date().isoformat()
            if day != today:
                if today is not None:
                    _daily(today)
                today = day
                _heartbeat("connect")

            if not gate.account_ready():
                if not _OFFLINE_ALERTED["v"]:
                    alerts.emit("WARN", "终端/账户离线或未登录")
                    _OFFLINE_ALERTED["v"] = True
                log.warning("终端/账户未就绪，%s秒后重试", _RETRY)
                _heartbeat(note="账户未就绪")
                time.sleep(_RETRY)
                continue
            _OFFLINE_ALERTED["v"] = False

            if session.is_open(dt):
                n = process_once()  # 内部已加锁/对账/门禁/绑定
                if n:
                    log.info("本轮实单 %d 单", n)
                    _heartbeat("order", f"成交/尝试 {n} 单")
                _heartbeat()
                time.sleep(min(_MIN, interval))
            elif schedule.in_read_window(dt):
                remote.pull("decisions")
                _heartbeat("pull", "已拉取")
                time.sleep(_MIN)
            else:
                _heartbeat()
                time.sleep(_MIN)
        except Exception as e:  # noqa: BLE001
            log.exception("调度单轮异常（存活继续）: %s", e)
            if isinstance(e, (ledger.LedgerCorruptError, intent.PendingCorruptError)):
                # 防重账本/在途意图损坏：安全记录失效，必须停市而非仅告警继续
                try:
                    governor.halt(f"{type(e).__name__}，安全记录损坏，自动停市")
                except Exception:  # noqa: BLE001
                    pass
            alerts.emit("CRIT", f"调度异常：{type(e).__name__}: {e}")
            _heartbeat(note=f"异常: {e}")
            time.sleep(_MIN)