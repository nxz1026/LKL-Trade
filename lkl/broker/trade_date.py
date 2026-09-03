"""交易日统一日期：一律 Asia/Shanghai（防 DB 海外 UTC 时区漂移）。"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


def trade_date() -> str:
    """当前 Asia/Shanghai 自然日（YYYY-MM-DD）：所有交易日/执行日以此为准。"""
    return datetime.now(TZ).strftime("%Y-%m-%d")


def parse(iso: str) -> date:
    """ISO 日期或带时区时间戳 → 上海自然日 date。"""
    if "T" in iso or "+" in iso or "Z" in iso:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(TZ).date()
    return date.fromisoformat(iso[:10])