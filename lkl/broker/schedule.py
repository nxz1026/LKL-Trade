"""调度活跃判定：仅文件读写窗口才需前端/任务活跃；统一 60s 周期。"""
from __future__ import annotations

from datetime import time

from lkl.broker import session

PULL_CYCLE_SEC = 60  # supervisor 主循环固定轮询周期（sup 启动可传参覆盖，运行中不变）
_READ_SEC = PULL_CYCLE_SEC  # 每 60s 读写一次


def in_read_window(t=None) -> bool:
    """盘内(实单/写) 或 12:01-12:59/17:30-18:01(拉取/读)。"""
    t = t or session.now()
    if session.is_open(t):
        return True
    h, m = t.hour, t.minute
    return (h == 12 and 1 <= m <= 59) or (h == 17 and 30 <= m) or (h == 18 and m <= 1)


_WINDOW_STARTS = (time(9, 30), time(12, 1), time(13, 0), time(17, 30))  # 盘内早/午间拉取/盘内下午/尾盘


def next_pull(t=None) -> datetime:
    """下一次进入拉取分支的最近时刻（对齐 supervisor 实时判定，非静态定点）。

    - 当前已在拉取窗口（盘内/午间/尾盘）→ 下一轮 60s 内即拉，返回下一整秒；
    - 窗口外 → 返回下一窗口起点（今日剩余窗口优先，否则次日 09:30；
      不跳过周末——sup 周末 09:30 同样进入 process_once 拉取，保持一致）。
    """
    from datetime import timedelta
    t = t or session.now()
    if in_read_window(t):
        return (t + timedelta(seconds=1)).replace(microsecond=0)
    for s in _WINDOW_STARTS:
        if s > t.time():
            return t.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
    nxt = (t + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
    return nxt


def refresh_sec(t=None) -> int:
    """活跃窗口内 = 60s；否则 0（不自动刷新）。"""
    return _READ_SEC if in_read_window(t) else 0