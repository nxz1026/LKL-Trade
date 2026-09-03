"""watch：盘中轮询 decisions.json，新动作即实单回报（去重、循环到截止）。

- 时间一律 Asia/Shanghai（P2-04），不得用本机 UTC/本地。
- 参数边界（P2-09）：interval≥5s、until 必须 HH:MM 合法。
- 下单受交易日/盘中门禁约束，盘外自动拒单可重试（P1-03）。
"""
from __future__ import annotations

import re
import time
from datetime import timedelta

from lkl.broker import session, tradeops

_MIN, _MAX = 5, 3600


def _clamp(v: int) -> int:
    return min(max(v, _MIN), _MAX)


def _until(spec: str):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (spec or "15:00").strip())
    if not m or not (0 <= int(m[1]) <= 23 and 0 <= int(m[2]) <= 59):
        raise ValueError(f"非法截止时间 {spec!r}（需 HH:MM）")
    base = session.now().replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
    return base if base > session.now() else base + timedelta(days=1)


def run(argv: list[str]) -> int:
    """lkl trade watch [interval=60] [until=15:00]：盯盘轮询。"""
    interval = _clamp(int(argv[0]) if argv and argv[0].isdigit() else 60)
    until = _until(argv[1] if len(argv) > 1 else "15:00")
    print(f"watch 开始：每 {interval}s 轮询，截止 {until:%H:%M:%S}，Ctrl+C 退出")
    while session.now() < until:
        try:
            n = tradeops.process_once()  # 内部已加锁/对账/门禁
            if n:
                print(f"[{_now()}] 新成交 {n} 单")
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 轮询异常：{e}")
        time.sleep(interval)
    print("watch 结束（到达截止时间）")
    return 0


def _now() -> str:
    return session.now().isoformat(timespec="seconds")