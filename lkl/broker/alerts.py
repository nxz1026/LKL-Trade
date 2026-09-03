"""分级告警中心（产品7 第9条：失败通知/待办；第6条：缓存与消息分级）。

- 写 `alerts.jsonl`（交换目录）追加式，级别 INFO/WARN/CRIT。
- 关键路径触发高危事件（急停/服务异常/对账不符/风控拦截）；普通成功静默。
- 看板读到 CRIT/WARN 汇总为「待办中心」；将来可插推送通道（webhook/邮件）在此挂钩。
"""
from __future__ import annotations

import json

from lkl.broker import fileio, session

LEVELS = ("INFO", "WARN", "CRIT")
_LEVEL = {"INFO": 0, "WARN": 1, "CRIT": 2}


def _path():
    return fileio.directory() / "alerts.jsonl"


def emit(level: str, msg: str) -> None:
    level = level.upper() if level.upper() in LEVELS else "INFO"
    line = json.dumps({"level": level, "ts": session.now().isoformat(timespec="seconds"), "msg": msg},
                      ensure_ascii=False)
    try:
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _records() -> list:
    if not _path().exists():
        return []
    out = []
    for line in _path().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def list_alerts(limit: int = 200) -> list:
    return _records()[-limit:]


def summary() -> dict:
    recs = _records()
    return {"total": len(recs),
            "crit": sum(1 for r in recs if r.get("level") == "CRIT"),
            "warn": sum(1 for r in recs if r.get("level") == "WARN"),
            "last": recs[-1] if recs else None}


def alertcrit(msg: str) -> None:
    emit("CRIT", msg)


def alert_warn(msg: str) -> None:
    emit("WARN", msg)


def alert_info(msg: str) -> None:
    emit("INFO", msg)