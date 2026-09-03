"""JSON 交易通道：读当日最新 decisions/results 带时间戳文件（不落库；schema v1）。

- 按业务日过滤后再取该日内最新版本（P2-02：跨日文件不互遮）。
- 决策**契约校验**（P1-09）：action 枚举、6 位无前缀 code、非负数量；任一不合法
  即抛 `DecisionValidationError` 阻止整批，绝不静默下单或错位。
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from lkl.broker import fileio, trade_date
from lkl.models.types import Signal

_SCHEMA = 1
_CODE = re.compile(r"^\d{6}$")


class DecisionValidationError(ValueError):
    """decisions 文件契约不合法——必须阻断，不得按推测下单。"""


def _payload_for_date(p: Path) -> str | None:
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return obj.get("for_date") if isinstance(obj, dict) else None


def decision_file(for_date: str | None = None) -> Path | None:
    """业务日最新 decisions 文件（绑定处理身份）。"""
    target = (for_date or trade_date.trade_date())[:10]
    cands = [p for p in fileio.versions("decisions")
             if _payload_for_date(p) == target]
    return max(cands, key=lambda p: p.name) if cands else None


def decision_date() -> str | None:
    p = fileio.latest("decisions")
    return _payload_for_date(p) if p else None


def _validate(it: dict, idx: int) -> tuple[str, str, int]:
    """逐条校验；返回 (code, action, volume)。不合法抛 DecisionValidationError。"""
    code = str(it.get("code", "") or "").strip()
    if not _CODE.fullmatch(code):
        raise DecisionValidationError(f"actions[{idx}]: code 非法 {code!r}（需 6 位数字）")
    action = str(it.get("action", "") or "").strip().upper()
    if action not in ("BUY", "SELL"):
        raise DecisionValidationError(f"actions[{idx}]: action 非法 {action!r}（BUY|SELL）")
    vol = it.get("volume")
    if vol is not None and (isinstance(vol, bool) or not isinstance(vol, (int, float))
                            or vol < 0):
        raise DecisionValidationError(f"actions[{idx}]: volume 非法 {vol!r}（需非负整数）")
    volume = int(vol or 0)
    return code, action, volume


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
        code, action, volume = _validate(it, i)
        out.append(Signal(confirm_date=target, code=code, action=action,
                          reason=it.get("reason", ""),
                          buy_window=it.get("window", ""), volume=volume))
    return out


def load_results(for_date: str | None = None) -> list:
    data = fileio.read("results")
    if data.get("for_date") != (for_date or trade_date.trade_date()):
        return []
    return data.get("trades", [])


def dump_results(for_date: str, trades: list) -> None:
    fileio.write("results", {"schema": _SCHEMA, "for_date": for_date, "trades": trades})