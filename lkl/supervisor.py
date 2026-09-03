"""交易调度器：跨日 sync/check + 盘中轮询实单；终端离线自愈等待。"""
from __future__ import annotations

import logging
import time

from lkl.broker import gate, session
from lkl.broker.sync import snapshot
from lkl.broker.tradeops import process_once

log = logging.getLogger("lkl.supervisor")
_RETRY = 30


def run(argv: list[str]) -> int:
    """lkl supervisor [interval=60]：常驻交易调度（Ctrl+C 退出）。"""
    interval = int(argv[0]) if argv and argv[0].isdigit() else 60
    log.info("调度器启动 interval=%ss（Asia/Shanghai）", interval)
    today = None
    while True:
        dt = session.now()
        day = dt.date().isoformat()
        if day != today:
            today = day
            _daily()
        if not gate.account_ready():
            tip = "金矿终端不在线" if not gate.up() else "终端在但账户未连接"
            log.warning("%s，%s 秒后重试", tip, _RETRY)
            time.sleep(_RETRY)
            continue
        if session.is_open(dt):
            n = process_once()
            if n:
                log.info("本轮实单 %d 单", n)
        time.sleep(float(interval if session.is_open() else 60))


def _daily() -> None:
    """新交易日一次：持仓快照 + 三文件一致性 check。"""
    if gate.wait(120):
        try:
            log.info("持仓快照→ holdings %s 条", snapshot())
        except Exception as e:
            log.warning("持仓快照失败：%s", e)
    from lkl.broker.audit import run as audit_run
    try:
        code = audit_run()
        log.info("一致性 check(明日)=%s", "OK" if code == 0 else "异常")
    except Exception as e:
        log.warning("check 异常：%s", e)