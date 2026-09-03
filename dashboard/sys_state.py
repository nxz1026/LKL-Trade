"""系统运行状态数据层：终端/账户/时段 + 文件体检 + 心跳与陈旧 + 治理（/api/sys）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from lkl.broker import config, fileio, gate, governor, session

_FILES = ("decisions", "results", "holdings")
_STALE_MIN = 3   # 心跳超过该分钟未更新 = 调度疑似停止


def _finfo(p: Path) -> dict:
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
    except Exception:
        return {"last_success": None, "note": "无心跳", "stale": True,
                "activities": {}}
    act = {k: v for k, v in obj.items()
           if k.startswith("last_") and k != "last_success"}
    stale = False
    last = obj.get("last_success")
    if last:
        try:
            t = datetime.fromisoformat(last)
            if t.tzinfo is None:
                t = t.replace(tzinfo=session.TZ)
            stale = (session.now() - t) > timedelta(minutes=_STALE_MIN)
        except ValueError:
            stale = True
    return {"last_success": last, "note": obj.get("note", ""),
            "stale": stale, "activities": act}



def _last_file_activity() -> str | None:
    """本地交换文件最近真实活动（results/holdings/decisions 最新 mtime 最大者）。"""
    best = None
    for kind in _FILES:
        f = fileio.latest(kind)
        if f:
            try:
                ts = datetime.fromtimestamp(f.stat().st_mtime, session.TZ)
                if best is None or ts > best:
                    best = ts
            except OSError:
                continue
    return best.isoformat(timespec="seconds") if best else None


def state() -> dict:
    now = session.now()
    phase = ("盘中" if session.market_open(now) else
             "盘前" if session.pre_open(now) else "休市")
    hb = _heartbeat()          # heartbeat=本地 sup 进程脉冲（只读给同机看板；不进 v2 契约/不推远端）
    gov = governor.state()
    return {
        "last_file_activity": _last_file_activity(),
        "now": now.isoformat(timespec="seconds"),
        "phase": phase,
        "trading_day": session.is_trading_day(now),
        "next_open": (session.next_open(now).isoformat(timespec="seconds")
                       if session.next_open(now) else None),
        "endpoint": config.endpoint(),
        "exchange_dir": str(fileio.directory()),
        "terminal": "在线" if gate.up() else "离线",
        "account_ready": gate.account_ready(),
        "creds_ok": bool(config.token() and config.account_id()),
        "govern": gov,
        "auto_trade": governor.allow_trade()[0],
        "bound_account": governor.bound_account(),
        "heartbeat": hb,
        "scheduler_alive": not hb.get("stale", False),
        "files": {n: _finfo(fileio.latest(n) or fileio.directory() / (n + ".json"))
                  for n in _FILES},
    }