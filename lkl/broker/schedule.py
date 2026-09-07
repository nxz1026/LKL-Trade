"""调度活跃判定与闭市睡眠：窗口内 60s 轮询，窗口外计算式睡眠（步长 ≤1h）。

窗口：09:00-10:00（早盘拉取，覆盖盘前投递）、12:58-13:00（午间拉取）、
17:30-18:01（尾盘拉取，决策过夜就位）；盘内时段本就 60s 执行轮询。
窗口外睡到下一窗口起点（跨日到次日 09:00），步长封顶 1h——保留每小时
心跳与终端检测，避免 18h 长睡导致离线/急停响应延迟与午夜跨日归档漂移。
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from lkl.broker import session

PULL_CYCLE_SEC = 60   # supervisor 主循环固定轮询周期（sup 启动可传参覆盖，运行中不变）
_READ_SEC = PULL_CYCLE_SEC          # 窗口内每 60s 读写一次
SLEEP_CAP_SEC = 3600                # 闭市睡眠步长上限：1h 一醒（心跳/终端检测/跨日归档）

_MORNING = (time(9, 0), time(10, 0))      # 早盘拉取：09:00 起持续 1 小时
_LUNCH = (time(12, 58), time(13, 0))      # 午间拉取：开盘前 2 分钟
_EVENING = (time(17, 30), time(18, 1))    # 尾盘拉取：31 分钟
_WINDOW_STARTS = (time(9, 0), time(12, 58), time(17, 30))


def _in_span(t, span) -> bool:
    return span[0] <= t.time() < span[1]


def in_read_window(t=None) -> bool:
    """盘内(实单/写) 或 09:00-10:00/12:58-13:00/17:30-18:01(拉取/读)。"""
    t = t or session.now()
    return (session.is_open(t) or _in_span(t, _MORNING)
            or _in_span(t, _LUNCH) or _in_span(t, _EVENING))


def sleep_until(t=None) -> datetime:
    """闭市睡眠的下一唤醒时刻：下一拉取窗口起点（今日剩余窗口优先，否则次日 09:00）。

    窗口/盘内已是活跃态 → 下一轮 60s 内即醒（调用方 sleep 步长会再封顶）。
    不跳过周末/休市日——窗口是日历钟点，周末照常拉取（决策可能周末投递），
    执行侧另由交易日门禁把关。
    """
    t = t or session.now()
    if in_read_window(t):
        return (t + timedelta(seconds=1)).replace(microsecond=0)
    tm = t.time()
    for s in _WINDOW_STARTS:
        if s > tm:
            return t.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
    return (t + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)


def sleep_sec(t=None) -> int:
    """闭市睡眠步长（秒）：到下一窗口起点，封顶 SLEEP_CAP_SEC 保每小时心跳/终端检测。"""
    dt = t or session.now()
    return min(max(int((sleep_until(dt) - dt).total_seconds()), _READ_SEC), SLEEP_CAP_SEC)


def next_pull(t=None) -> datetime:
    """下一次进入拉取分支的最近时刻（看板倒计时，对齐 supervisor 实时判定）。

    - 当前已在拉取窗口（盘内/早盘/午间/尾盘）→ 下一轮 60s 内即拉，返回下一整秒；
    - 窗口外 → 返回下一窗口起点（今日剩余窗口优先，否则次日 09:00）。
    """
    t = t or session.now()
    if in_read_window(t):
        return (t + timedelta(seconds=1)).replace(microsecond=0)
    return sleep_until(t)


def refresh_sec(t=None) -> int:
    """活跃窗口内 = 60s；否则 0（不自动刷新）。"""
    return _READ_SEC if in_read_window(t) else 0