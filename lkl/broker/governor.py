"""安全治理（产品第7节）：演练/实盘模式、总开关、紧急停止、风控护栏。

持久于 exchange 目录 `governance.json`（重启保留）：
  {"mode": "dry"|"armed", "halt": bool, "reason": str, "updated_at": ISO}

- 默认 **dry（只读演练）**：任何入口都不允许自动下单。
- 进入实盘必须显式 `armed`；紧急停止 `halt=True` 立即生效并持久，重启仍停。
- 风控护栏读取 `config.risk_limits()`：单笔股数 / 当日下单次数 / 当日操作只数。
"""
from __future__ import annotations

import json
from datetime import datetime

from lkl.broker import alerts, config, fileio, session

_DEFAULTS = {"mode": "dry", "halt": False, "reason": "", "updated_at": ""}


def _path():
    return fileio.directory() / "governance.json"


def state() -> dict:
    if not _path().exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (ValueError, OSError):
        # 治理文件损坏 = 安全起见按禁止自动交易处理
        return {"mode": "dry", "halt": True,
                "reason": "governance.json 损坏，自动按停市处理", "updated_at": ""}
    g = dict(_DEFAULTS)
    g.update(data or {})
    return g


def _save(g: dict) -> None:
    g["updated_at"] = datetime.now(session.TZ).isoformat(timespec="seconds")
    fileio.atomic_write(_path(), json.dumps(g, ensure_ascii=False, indent=1))


def set_mode(mode: str, reason: str = "") -> dict:
    if mode not in ("dry", "armed"):
        raise ValueError(f"非法模式 {mode!r}（dry|armed）")
    g = state()
    g["mode"] = mode
    if reason:
        g["reason"] = reason
    _save(g)
    return g


def halt(reason: str = "") -> dict:
    g = state()
    g["halt"], g["reason"] = True, reason or g.get("reason", "")
    _save(g)
    alerts.emit("CRIT", f"紧急停止：{g['reason'] or '人工'}")
    return g


def resume() -> dict:
    g = state()
    g["halt"], g["reason"] = False, ""
    _save(g)
    return g


def allow_trade() -> tuple[bool, str]:
    """是否允许自动下单：(允许?, 原因)。"""
    g = state()
    if g.get("halt"):
        return False, "已紧急停止"
    if g.get("mode") != "armed":
        return False, "演练(dry)模式，未 arm，不自动下单"
    return True, ""


def risk_block(qty: int, today_orders: int, today_codes: int) -> tuple[bool, str]:
    r = config.risk_limits()
    if r["max_qty"] and qty > r["max_qty"]:
        return True, f"单笔 {qty} 股 > 上限 {r['max_qty']}"
    if r["max_orders"] and today_orders >= r["max_orders"]:
        return True, f"当日已下 {today_orders} 单，达上限 {r['max_orders']}"
    if r["max_codes"] and today_codes >= r["max_codes"]:
        return True, f"当日已操作 {today_codes} 只，达上限 {r['max_codes']}"
    return False, ""


def run_cli(action: str, reason: str = "") -> str:
    """lkl trade govern <status|dry|arm|halt|resume> [reason]。"""
    a = action.lower()
    if a == "status":
        g = state()
        mode = "实盘(armed)" if g["mode"] == "armed" else "演练(dry)"
        return (f"模式: {mode} | 紧急停止: {'是' if g.get('halt') else '否'} | "
                f"原因: {g.get('reason') or '-'} | 更新: {g.get('updated_at') or '-'}")
    if a == "dry":
        set_mode("dry", reason)
        return "已切演练模式（不自动下单）"
    if a == "arm":
        set_mode("armed", reason)
        return "已切实盘(armed)模式——可自动下单"
    if a == "halt":
        halt(reason or "人工紧急停止")
        return "已紧急停止（持久，重启仍停）"
    if a == "resume":
        resume()
        return "已解除停止"
    return "未知动作（status|dry|arm|halt|resume）"