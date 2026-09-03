"""A股交易时段判定（一律 Asia/Shanghai）。"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

_MORNING = (time(9, 30), time(11, 30))
_AFTERNOON = (time(13, 0), time(15, 0))


def now() -> datetime:
    return datetime.now(TZ)


def is_open(dt: datetime | None = None) -> bool:
    """处于连续竞价时段。"""
    t = (dt or now()).time()
    return (_MORNING[0] <= t <= _MORNING[1] or
            _AFTERNOON[0] <= t <= _AFTERNOON[1])


def pre_open(dt: datetime | None = None) -> bool:
    """盘前 08:00~09:30（偏持仓快照/对账窗口）。"""
    t = (dt or now()).time()
    return time(8, 0) <= t < time(9, 30)