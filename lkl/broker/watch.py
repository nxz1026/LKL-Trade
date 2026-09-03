"""watch：盘中轮询 decisions.json，新动作即实单并回报（去重、循环到截止）。"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from lkl.broker import tradeops


def run(argv: list[str]) -> int:
    """lkl trade watch [interval=60s] [until=HH:MM]：盯盘轮询实单。"""
    interval = int(argv[0]) if argv and argv[0].isdigit() else 60
    until = _until(argv[1] if len(argv) > 1 else "15:00")
    print(f"watch 开始：每 {interval}s 轮询，截止 {until:%H:%M:%S}，Ctrl+C 退出")
    while datetime.now() < until:
        try:
            n = tradeops.process_once()
            print(f"[{_now()}] 新执行 {n} 单")
        except Exception as e:
            print(f"[{_now()}] 轮询异常：{e}")
        time.sleep(interval)
    print("watch 结束（到达截止时间）")
    return 0


def _until(spec: str) -> datetime:
    """HH:MM 默认今天；已过则顺延明日。"""
    hh, _, mm = (spec or "15:00").partition(":")
    base = datetime.now().replace(hour=int(hh), minute=int(mm),
                                  second=0, microsecond=0)
    return base if base > datetime.now() else base + timedelta(days=1)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")