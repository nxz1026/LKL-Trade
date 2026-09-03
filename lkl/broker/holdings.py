"""真实持仓快照：写 ~/trade/holdings.json，供 DB 侧对照 position 表。"""
from __future__ import annotations

import json
from datetime import date, datetime

from lkl.broker import config, fileio, trade_date


_SCHEMA = 1


def path():
    """holdings.json 绝对路径。"""
    return fileio.directory() / "holdings.json"


def dump(rows: list) -> None:
    """写 holdings.json（真实持仓快照+时间戳副本）。"""
    fileio.dump_json("holdings.json",
                     {"schema": _SCHEMA, "for_date": date.today().isoformat(),
                      "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                      "account": config.account_id(), "holdings": rows})


def load() -> list:
    """读 holdings.json；无文件返回 []。"""
    p = fileio.directory() / "holdings.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("holdings", [])