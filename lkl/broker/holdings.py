"""真实持仓快照：写 holdings_{时间戳}.json，供 DB 侧对照 position 表、对账。"""
from __future__ import annotations

from datetime import date, datetime

from lkl.broker import config, fileio

_SCHEMA = 1


def path():
    """最新 holdings 快照路径（无则 None）。"""
    return fileio.latest("holdings")


def dump(rows: list) -> None:
    """写 holdings_{时间戳}.json（真实持仓快照，每份唯一）。"""
    fileio.write("holdings",
                 {"schema": _SCHEMA, "for_date": date.today().isoformat(),
                  "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                  "account": config.account_id(), "holdings": rows})


def load() -> list:
    data = fileio.read("holdings")
    return data.get("holdings", [])