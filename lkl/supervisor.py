"""调度：盘内执行当日决策；12:01-12:59/17:30-18:01 每分拉取；未来日留至次日执行。"""
from __future__ import annotations
import logging
import time
from lkl.broker import gate, remote, session
from lkl.broker.archiver import pack; from lkl.broker.cleanup import remove_archived; from lkl.broker.sync import snapshot; from lkl.broker.tradeops import process_once

log = logging.getLogger("lkl.supervisor")
_RETRY, _MIN = 30, 60

def _poll_now(t) -> bool:
    h, m = t.hour, t.minute
    return (h == 12 and 1 <= m <= 59) or (h == 17 and 30 <= m) or (h == 18 and m <= 1)

def run(argv: list[str]) -> int:
    interval = int(argv[0]) if argv and argv[0].isdigit() else 60
    today = None
    while True:
        dt = session.now()
        day = dt.date().isoformat()
        if day != today:
            if today and pack(today):
                remove_archived(today)
            today = day
            _daily()
        if not gate.account_ready():
            log.warning("终端/账户未就绪，%s秒后重试", _RETRY)
            time.sleep(_RETRY); continue
        if session.is_open(dt):
            n = process_once()
            if n:
                log.info("本轮实单 %d 单", n)
            time.sleep(min(_MIN, interval))
        elif _poll_now(dt):
            remote.pull("decisions")
            time.sleep(_MIN)
        else:
            time.sleep(_MIN)

def _daily() -> None:
    if gate.wait(120):
        try:
            log.info("持仓快照→ %s 条", snapshot())
        except Exception as e:
            log.warning("快照失败: %s", e)
    from lkl.broker.audit import run as a
    try:
        log.info("check=%s", "OK" if a() == 0 else "异常")
    except Exception as e:
        log.warning("check 异常: %s", e)
