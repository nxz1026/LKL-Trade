"""调度活跃判定：仅文件读写窗口才需前端/任务活跃；统一 60s 周期。"""
from __future__ import annotations

from lkl.broker import session

_READ_SEC = 60  # 每 60s 读写一次


def in_read_window(t=None) -> bool:
    """盘内(实单/写) 或 12:01-12:59/17:30-18:01(拉取/读)。"""
    t = t or session.now()
    if session.is_open(t):
        return True
    h, m = t.hour, t.minute
    return (h == 12 and 1 <= m <= 59) or (h == 17 and 30 <= m) or (h == 18 and m <= 1)


def refresh_sec(t=None) -> int:
    """活跃窗口内 = 60s；否则 0（不自动刷新）。"""
    return _READ_SEC if in_read_window(t) else 0