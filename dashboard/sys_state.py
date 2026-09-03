"""系统运行状态数据层：终端/账户/时段 + 交换目录文件体检 + 心跳（供看板 /api/sys）。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from lkl.broker import config, fileio, gate, governor, session

_FILES = ("decisions", "results", "holdings")


def _finfo(p: Path) -> dict:
    """文件体检：存在/大小/mtime/今日/schema/for_date/解析状态。"""
    if not p.exists():
        return {"exists": False, "age": "", "today": False, "schema": None,
                "for_date": None, "parse": "ok"}
    st = p.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, session.TZ).isoformat(timespec="seconds")
    today = datetime.now(session.TZ).isoformat()[:10] == mtime[:10]
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return {"exists": True, "size": st.st_size, "mtime": mtime, "today": today,
                "schema": obj.get("schema"), "for_date": obj.get("for_date"),
                "parse": "ok"}
    except (ValueError, OSError) as e:
        return {"exists": True, "size": st.st_size, "mtime": mtime, "today": today,
                "schema": None, "for_date": None, "parse": f"损坏:{type(e).__name__}"}


def _heartbeat() -> dict:
    p = fileio.directory() / "heartbeat.json"
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return {"last_success": obj.get("last_success"), "note": obj.get("note", "")}
    except Exception:
        return {"last_success": None, "note": "无心跳"}


def state() -> dict:
    now = session.now()
    phase = ("盘中" if session.market_open(now) else
             "盘前" if session.pre_open(now) else "休市")
    return {
        "now": now.isoformat(timespec="seconds"),
        "phase": phase,
        "trading_day": session.is_trading_day(now),
        "endpoint": config.endpoint(),
        "exchange_dir": str(fileio.directory()),
        "terminal": "在线" if gate.up() else "离线",
        "account_ready": gate.account_ready(),
        "govern": governor.state(),
        "auto_trade": governor.allow_trade()[0],
        "heartbeat": _heartbeat(),
        "files": {n: _finfo(fileio.latest(n) or fileio.directory() / (n + ".json"))
                  for n in _FILES},
    }