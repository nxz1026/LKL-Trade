"""分级告警中心（产品7 第9条：失败通知/待办；第6条：缓存与消息分级）。

- 写 `alerts.jsonl`（交换目录）追加式，级别 INFO/WARN/CRIT。
- 关键路径触发高危事件（急停/服务异常/对账不符/风控拦截）；普通成功静默。
- 看板读到 CRIT/WARN 汇总为「待办中心」；外部可达通知走 notify()：
  读 GM_ALERT_WEBHOOK（逗号分隔 URL），CRIT/WARN 时 POST JSON 到各 URL；
  失败仅记日志，绝不抛（告警通道不可用不得影响主流程）。
"""
from __future__ import annotations

import json
import logging

from lkl.broker import config, fileio, session

log = logging.getLogger("lkl.alerts")

LEVELS = ("INFO", "WARN", "CRIT")


def _path():
    return fileio.directory() / "alerts.jsonl"


def _webhook_urls() -> list:
    """GM_ALERT_WEBHOOK 逗号分隔的推送 URL；无配置返回空。"""
    return [u.strip() for u in config._secret("GM_ALERT_WEBHOOK").split(",") if u.strip()]


def notify(level: str, msg: str) -> None:
    """外部可达通知（webhook POST JSON {level, ts, msg}）。

    仅在配置了 GM_ALERT_WEBHOOK 且级别为 CRIT/WARN 时推送；
    网络/HTTP 异常全部吞掉记日志，告警通道故障不阻断业务。
    """
    if level not in ("CRIT", "WARN"):
        return
    urls = _webhook_urls()
    if not urls:
        return
    import urllib.request
    body = json.dumps({"level": level, "ts": session.now().isoformat(timespec="seconds"),
                       "msg": msg}, ensure_ascii=False).encode("utf-8")
    for u in urls:
        try:
            req = urllib.request.Request(u, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception as e:  # noqa: BLE001
            log.warning("告警 webhook 推送失败 %s: %s", u, e)


def emit(level: str, msg: str) -> None:
    level = level.upper() if level.upper() in LEVELS else "INFO"
    line = json.dumps({"level": level, "ts": session.now().isoformat(timespec="seconds"), "msg": msg},
                      ensure_ascii=False)
    try:
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    notify(level, msg)


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