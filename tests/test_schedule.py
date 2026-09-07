"""schedule 窗口与闭市睡眠测试：窗口边界、sleep_until/sleep_sec、next_pull。

窗口：09:00-10:00（早盘，覆盖盘前投递）/12:58-13:00（午间）/17:30-18:01（尾盘）；
窗口外计算式睡眠到下一窗口起点（跨日到次日 09:00），步长封顶 1h。
"""
from __future__ import annotations

from datetime import datetime

from lkl.broker import schedule, session

_MON = (2026, 9, 7)     # 周一；窗口纯钟点不依赖星期，跨日断言只按自然日偏移


def _dt(h, m, s=0, day=_MON):
    y, mo, d = day
    return datetime(y, mo, d, h, m, s, tzinfo=session.TZ)


def test_windows_boundaries():
    assert schedule.in_read_window(_dt(9, 0))
    assert schedule.in_read_window(_dt(9, 29, 59))
    assert schedule.in_read_window(_dt(10, 0))           # 10:00 处于盘中（is_open）
    assert not schedule.in_read_window(_dt(12, 57))
    assert schedule.in_read_window(_dt(12, 58))
    assert schedule.in_read_window(_dt(12, 59, 59))
    assert schedule.in_read_window(_dt(13, 0))           # 盘中（is_open）
    assert not schedule.in_read_window(_dt(15, 30))
    assert schedule.in_read_window(_dt(17, 30))
    assert schedule.in_read_window(_dt(18, 0, 59))
    assert not schedule.in_read_window(_dt(18, 1))       # 尾盘窗口 [17:30,18:01) 不含终点
    assert not schedule.in_read_window(_dt(20, 0))


def test_windows_weekend_calendar_clock():
    """窗口按日历钟点，周末照常拉取（决策可能周末投递）；执行由交易日门禁把关。"""
    sat = (2026, 9, 5)
    assert schedule.in_read_window(_dt(9, 30, day=sat))
    assert schedule.in_read_window(_dt(13, 30, day=sat))  # is_open 只看钟点


def test_sleep_until_windows():
    assert schedule.sleep_until(_dt(8, 0)) == _dt(9, 0)
    assert schedule.sleep_until(_dt(11, 40)) == _dt(12, 58)
    assert schedule.sleep_until(_dt(15, 30)) == _dt(17, 30)
    assert schedule.sleep_until(_dt(18, 30)) == _dt(9, 0, day=(2026, 9, 8))          # 次日 09:00
    assert schedule.sleep_until(_dt(18, 30, day=(2026, 9, 5))) == _dt(9, 0, day=(2026, 9, 6))  # 周六→周日
    assert schedule.sleep_until(_dt(9, 15)) == _dt(9, 15, 1)                          # 窗口内：下一整秒


def test_sleep_sec_cap():
    assert schedule.sleep_sec(_dt(8, 0)) == 3600        # 到 09:00 正好 1h
    assert schedule.sleep_sec(_dt(18, 30)) == 3600      # 夜间长睡封顶 1h（不空转也不失联）
    assert schedule.sleep_sec(_dt(11, 40)) == 3600      # 午休 78min 封顶 1h
    assert schedule.sleep_sec(_dt(9, 15)) == 60         # 窗口内最短步长


def test_next_pull_matches_supervisor():
    assert schedule.next_pull(_dt(8, 0)) == _dt(9, 0)
    assert schedule.next_pull(_dt(9, 15)) == _dt(9, 15, 1)    # 窗口内：下一整秒
    assert schedule.next_pull(_dt(13, 30)) == _dt(13, 30, 1)  # 盘中：下一整秒
    assert schedule.next_pull(_dt(15, 30)) == _dt(17, 30)
    assert schedule.next_pull(_dt(18, 30)) == _dt(9, 0, day=(2026, 9, 8))