"""调度：盘内执行当日决策；12:01-12:59/17:30-18:01 每分拉取；未来日留至次日执行。

对应审查 P1-10：主循环单轮失败必须**记录并继续**，绝不因一个坏 JSON / 一次 SDK 或
磁盘异常退出无人值守进程；同时保留最后成功心跳供看板判断存活。
"""
from __future__ import annotations
import json
import logging
import time
from datetime import datetime

from lkl.broker import alerts, config, fileio, gate, remote, schedule, session
from lkl.broker.archiver import pack
from lkl.broker.cleanup import remove_archived
from lkl.broker.sync import snapshot
from lkl.broker.tradeops import process_once

log = logging.getLogger("lkl.supervisor")
_RETRY, _MIN = 30, 60


def _heartbeat(note: str = "") -> None:
    payload = {"last_success": datetime.now(session.TZ).isoformat(timespec="seconds"),
               "note": note}
    try:
        fileio.atomic_write(config.trade_dir() / "heartbeat.json",
                            json.dumps(payload, ensure_ascii=False))
    except OSError:
        pass


def _daily(day: str) -> None:
    """跨日收尾：归档昨日、删远端、盘前快照与 check（各自隔离）。"""
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
            log.info("持仓快照→ %s 条", snapshot())
        except Exception as e:  # noqa: BLE001
            log.warning("快照失败: %s", e)
    from lkl.broker.audit import run as a
    try:
        log.info("check=%s", "OK" if a() == 0 else "异常")
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

            if not gate.account_ready():
                log.warning("终端/账户未就绪，%s秒后重试", _RETRY)
                _heartbeat("账户未就绪")
                time.sleep(_RETRY)
                continue

            if session.is_open(dt):
                n = process_once()  # 内部已加锁/对账/去重/门禁
                if n:
                    log.info("本轮实单 %d 单", n)
                _heartbeat("")
                time.sleep(min(_MIN, interval))
            elif schedule.in_read_window(dt):
                remote.pull("decisions")
                _heartbeat("已拉取")
                time.sleep(_MIN)
            else:
                _heartbeat("")
                time.sleep(_MIN)
        except Exception as e:  # noqa: BLE001
            log.exception("调度单轮异常（存活继续）: %s", e)
            alerts.emit("CRIT", f"调度异常：{type(e).__name__}: {e}")
            _heartbeat(f"异常: {e}")
            time.sleep(_MIN)