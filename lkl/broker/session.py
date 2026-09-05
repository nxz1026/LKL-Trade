"""A股交易时段与交易日判定（一律 Asia/Shanghai）。

is_open 只看钟点；is_trading_day 进一步判定周末与休市日（节假日），
两者合起来才是「真实可下单」。（手工 trade / watch / sup 三个入口统一在此门禁，
见 policy.market_verdict。）
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from lkl.broker import config

TZ = ZoneInfo("Asia/Shanghai")

_MORNING = (time(9, 30), time(11, 30))
_AFTERNOON = (time(13, 0), time(15, 0))


def now() -> datetime:
    return datetime.now(TZ)


def is_trading_day(dt: datetime | None = None) -> bool:
    """周末与法定休市日（GM_HOLIDAYS）之外的日期。"""
    d = (dt or now()).date()
    if d.weekday() >= 5:            # 周六/周日休市
        return False
    hols = config.holidays()
    return d.isoformat() not in hols


def is_open(dt: datetime | None = None) -> bool:
    """处于连续竞价时段（钟点层面）。"""
    t = (dt or now()).time()
    return (_MORNING[0] <= t <= _MORNING[1] or
            _AFTERNOON[0] <= t <= _AFTERNOON[1])


def market_open(dt: datetime | None = None) -> bool:
    """「今日为交易日」且在竞价时段——真正的可交易判定。"""
    dt = dt or now()
    return is_trading_day(dt) and is_open(dt)


def pre_open(dt: datetime | None = None) -> bool:
    """盘前 08:00~09:30（偏持仓快照/对账窗口）。"""
    t = (dt or now()).time()
    return time(8, 0) <= t < time(9, 30)


def next_open(dt: datetime | None = None) -> datetime | None:
    """下一个可交易时段起点（跳过周末/休市日）；今日无则 None。"""
    from datetime import timedelta
    base = dt or now()
    if base.time() < _MORNING[0] and is_trading_day(base):
        return base.replace(hour=9, minute=30, second=0, microsecond=0)
    if _MORNING[0] <= base.time() < _AFTERNOON[0] and is_trading_day(base):
        return base.replace(hour=13, minute=0, second=0, microsecond=0)  # 上午/午休 → 当日 13:00
    for i in range(1, 8):
        cand = base.replace(hour=9, minute=30, second=0, microsecond=0) + timedelta(days=i)
        if is_trading_day(cand):
            return cand
    return None