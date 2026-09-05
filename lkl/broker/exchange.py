"""JSON 交易通道：读当日最新 decisions/results 带时间戳文件（不落库；schema v2）。

- 按业务日过滤后再取该日内最新版本（跨日文件不互遮）。
- 决策**契约校验**：action 枚举、6 位无前缀 code、非负数量、exec 合法性；
  任一不合法即抛 `DecisionValidationError` 阻止整批，绝不静默下单或错位。
- exec 执行语义（契约 v2）：OPEN_POS↔BUY 开仓 / CLOSE_ALL↔SELL 清仓；
  schema:1 旧文件缺 exec → BUY 兜底 OPEN_POS、SELL 兜底 CLOSE_ALL（不拒单）。
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from lkl.broker import fileio, trade_date
from lkl.models.types import Signal

_SCHEMA = 2
_CODE = re.compile(r"^\d{6}$")
_EXEC = ("", "OPEN_POS", "CLOSE_ALL")


class DecisionValidationError(ValueError):
    """decisions 文件契约不合法——必须阻断，不得按推测下单。"""


def _payload_for_date(p: Path) -> str | None:
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return obj.get("for_date") if isinstance(obj, dict) else None


def decision_files(for_date: str | None = None) -> list:
    """业务日全部 decisions 文件，**按时间升序（旧→新）**，保证同一 code 多份决策
    按投递顺序执行（先买后卖，绝不倒序）。无则空列表。"""
    target = (for_date or trade_date.trade_date())[:10]
    cands = [p for p in fileio.versions("decisions")
             if _payload_for_date(p) == target]
    return sorted(cands, key=lambda p: p.name)


def decision_file(for_date: str | None = None) -> Path | None:
    """业务日最新 decisions 文件（绑定处理身份；只读用途，执行走 decision_files）。"""
    fs = decision_files(for_date)
    return fs[-1] if fs else None


def decision_date() -> str | None:
    p = fileio.latest("decisions")
    return _payload_for_date(p) if p else None


def _validate(it: dict, idx: int) -> tuple[str, str, str, int]:
    """逐条校验；返回 (code, action, exec_, volume)。不合法抛 DecisionValidationError。

    exec 是执行分发依据：OPEN_POS↔BUY、CLOSE_ALL↔SELL；缺省（schema:1 旧文件）按
    action 兜底：BUY→OPEN_POS、SELL→CLOSE_ALL（不再因缺 exec 拒单）。
    """
    code = str(it.get("code", "") or "").strip()
    if not _CODE.fullmatch(code):
        raise DecisionValidationError(f"actions[{idx}]: code 非法 {code!r}（需 6 位数字）")
    action = str(it.get("action", "") or "").strip().upper()
    if action not in ("BUY", "SELL"):
        raise DecisionValidationError(f"actions[{idx}]: action 非法 {action!r}（BUY|SELL）")
    ex = str(it.get("exec", "") or "").strip().upper()
    if ex not in _EXEC:
        raise DecisionValidationError(f"actions[{idx}]: exec 非法 {ex!r}（OPEN_POS|CLOSE_ALL）")
    if ex == "OPEN_POS" and action != "BUY":
        raise DecisionValidationError(f"actions[{idx}]: exec=OPEN_POS 只配 BUY（实际 {action}）")
    if ex == "CLOSE_ALL" and action != "SELL":
        raise DecisionValidationError(f"actions[{idx}]: exec=CLOSE_ALL 只配 SELL（实际 {action}）")
    if not ex:
        ex = "OPEN_POS" if action == "BUY" else "CLOSE_ALL"
    vol = it.get("volume")
    if vol is not None and (isinstance(vol, bool) or not isinstance(vol, (int, float))
                            or vol < 0):
        raise DecisionValidationError(f"actions[{idx}]: volume 非法 {vol!r}（需非负整数）")
    volume = int(vol or 0)
    return code, action, ex, volume


def load_decisions(for_date: str | None = None, path: Path | None = None) -> list:
    """读绑定 decisions → Signal[]；任一动作违反契约即抛。

    日期不匹配返回空；缺失返回空。"""
    target = date.fromisoformat(for_date) if for_date else date.fromisoformat(trade_date.trade_date())
    path = path or decision_file(for_date)
    data = fileio.read_path(path)
    if data.get("for_date") != target.isoformat():
        return []
    out = []
    for i, it in enumerate(data.get("actions", [])):
        code, action, ex, volume = _validate(it, i)
        out.append(Signal(confirm_date=target, code=code, action=action,
                          reason=it.get("reason", ""),
                          buy_window=it.get("window", ""),
                          exec_=ex, volume=volume))
    return out


def load_results(for_date: str | None = None) -> list:
    data = fileio.read("results")
    if data.get("for_date") != (for_date or trade_date.trade_date()):
        return []
    return data.get("trades", [])


def dump_results(for_date: str, trades: list) -> None:
    fileio.write("results", {"schema": _SCHEMA, "for_date": for_date, "trades": trades})