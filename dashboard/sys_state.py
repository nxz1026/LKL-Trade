"""系统运行状态数据层：终端/账户/时段 + 交换目录四文件体检（供看板 /api/sys）。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from lkl.broker import config, fileio, gate, session

_FILES = ("decisions", "results", "holdings")


def _finfo(p: Path) -> dict:
    """文件体检：存在/大小/mtime/更新于今日/schema/for_date。"""
    if not p.exists():
        return {"exists": False, "age": "", "today": False, "schema": None, "for_date": None}
    st = p.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, session.TZ).isoformat(timespec="seconds")
    today = datetime.now(session.TZ).isoformat()[:10] == mtime[:10]
    obj = json.loads(p.read_text(encoding="utf-8"))
    return {"exists": True, "size": st.st_size, "mtime": mtime, "today": today,
            "schema": obj.get("schema"), "for_date": obj.get("for_date")}


def state() -> dict:
    now = session.now()
    phase = "盘中" if session.is_open(now) else "盘前" if session.pre_open(now) else "休市"
    return {
        "now": now.isoformat(timespec="seconds"),
        "phase": phase,
        "endpoint": config.endpoint(),
        "exchange_dir": str(fileio.directory()),
        "terminal": "在线" if gate.up() else "离线",
        "account_ready": gate.account_ready(),
        "files": {n: _finfo(fileio.latest(n) or fileio.directory() / (n + ".json")) for n in _FILES},
    }