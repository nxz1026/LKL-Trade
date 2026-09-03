"""JSON 交易通道：读 decisions.json、读写 results.json（不落库；schema v1）。"""
from __future__ import annotations

import json
from datetime import date

from lkl.broker import fileio, trade_date
from lkl.models.types import Signal

_SCHEMA = 1


def load_decisions(for_date: str | None = None) -> list:
    """读 decisions.json 当日动作 → Signal[]；缺文件/日期不符返回空。"""
    target = date.fromisoformat(for_date) if for_date else date.fromisoformat(trade_date.trade_date())
    data = fileio.read("decisions.json")
    if data.get("for_date") != target.isoformat():
        return []
    return [
        Signal(confirm_date=target, code=it["code"].strip(),
               action=it["action"].upper(),
               reason=it.get("reason", ""), buy_window=it.get("window", ""),
               volume=int(it.get("volume") or 0))
        for it in data.get("actions", [])
    ]


def load_results(for_date: str | None = None) -> list:
    """读 results.json 该日已回报（watch 去重基准）。"""
    data = fileio.read("results.json")
    if data.get("for_date") != (for_date or trade_date.trade_date()):
        return []
    return data.get("trades", [])



def decision_date() -> str | None:
    """decisions.json 顶层 for_date；无文件返回 None（供本地比对提示）。"""
    return fileio.read("decisions.json").get("for_date")

def dump_results(for_date: str, trades: list) -> None:
    """覆盖写 results.json（trades 已去重）。"""
    fileio.directory().mkdir(parents=True, exist_ok=True)
    fileio.results_path().write_text(json.dumps(
        {"schema": _SCHEMA, "for_date": for_date, "trades": trades},
        ensure_ascii=False, indent=2), encoding="utf-8")