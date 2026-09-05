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

_DEFAULTS = {"mode": "dry", "halt": False, "reason": "", "account": "", "updated_at": ""}


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
    """切模式；进入 armed 时记录当前配置账户为绑定账户（产品7-7）。

    审计留痕：切实盘(armed)按 CRIT、切演练(dry)按 INFO 写入告警中心（带时间/原因）。
    """
    if mode not in ("dry", "armed"):
        raise ValueError(f"非法模式 {mode!r}（dry|armed）")
    g = state()
    g["mode"] = mode
    if mode == "armed" and not g.get("account"):
        g["account"] = config.account_id() or ""
    if reason:
        g["reason"] = reason
    _save(g)
    label = "实盘(armed)" if mode == "armed" else "演练(dry)"
    alerts.emit("CRIT" if mode == "armed" else "INFO",
                f"切{label}模式：{reason or '无原因'}")
    return g


def bound_account() -> str:
    return state().get("account") or ""


def verify_binding() -> tuple[bool, str]:
    """账户—策略绑定校验：当前配置账户若与绑定时不一致则不得交易。"""
    bound = bound_account()
    cur = config.account_id()
    if not bound or not cur:
        return True, ""
    if cur != bound:
        return False, f"账户绑定 {bound} ≠ 当前配置 {cur}，拒绝沿用旧账本/旧决策"
    return True, ""


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
    alerts.emit("INFO", "解除紧急停止")
    return g


def allow_trade() -> tuple[bool, str]:
    """是否允许自动下单：(允许?, 原因)。"""
    g = state()
    if g.get("halt"):
        return False, "已紧急停止"
    if g.get("mode") != "armed":
        return False, "演练(dry)模式，未 arm，不自动下单"
    ok, why = verify_binding()
    if not ok:
        return False, why
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
        inflight = _inflight_count()
        return (f"模式: {mode} | 紧急停止: {'是' if g.get('halt') else '否'} | "
                f"绑定账户: {g.get('account') or '-'} | 在途未成: {inflight} | "
                f"原因: {g.get('reason') or '-'} | 更新: {g.get('updated_at') or '-'}")
    if a == "dry":
        set_mode("dry", reason)
        return "已切演练模式（不自动下单）"
    if a == "arm":
        try:
            from lkl.broker import doctor
            ok, fails = doctor.quick()
        except Exception as e:
            ok, fails = False, [f"自检异常: {e}"]
        if not ok:
            return "切实盘被拒：关键自检未过 → " + "; ".join(fails) + "（先 lkl doctor）"
        set_mode("armed", reason)
        return "已切实盘(armed)模式——可自动下单"
    if a == "halt":
        inflight = _inflight_count()
        halt(reason or "人工紧急停止")
        tail = f"；注意：仍有 {inflight} 笔在途(已报未成)委托待核对" if inflight else ""
        return f"已紧急停止（持久，重启仍停）{tail}"
    if a == "resume":
        resume()
        return "已解除停止"
    return "未知动作（status|dry|arm|halt|resume）"

def _inflight_count() -> int:
    try:
        from lkl.broker import intent
        recs = intent.load()
        return sum(1 for r in recs.values() if r.get("order_id"))
    except Exception:
        return 0
