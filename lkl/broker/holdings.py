"""持仓快照：写 holdings_{时间戳}.json（v2 全量对账），日期/时间一律 Asia/Shanghai。"""
from __future__ import annotations

from datetime import datetime

from lkl.broker import config, fileio, session

_SCHEMA = 1


def path():
    """最新 holdings 快照路径（无则 None）。"""
    return fileio.latest("holdings")


def dump(rows: list) -> None:
    """写 holdings_{时间戳}.json（真实持仓快照，原子、每份唯一）。"""
    now = datetime.now(session.TZ)
    fileio.write("holdings",
                 {"schema": _SCHEMA, "for_date": now.date().isoformat(),
                  "generated_at": now.isoformat(timespec="seconds"),
                  "account": config.account_id(), "holdings": rows})


def load() -> list:
    data = fileio.read("holdings")
    return data.get("holdings", [])