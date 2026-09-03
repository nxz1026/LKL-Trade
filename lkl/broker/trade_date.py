"""交易日统一日期：一律 Asia/Shanghai（防海外 UTC 漂移）。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


def trade_date() -> str:
    """当前 Asia/Shanghai 自然日（YYYY-MM-DD）：所有交易日/执行日以此为准。"""
    return datetime.now(TZ).strftime("%Y-%m-%d")