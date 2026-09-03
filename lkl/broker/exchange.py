"""JSON 交易通道：读当日最新 decisions/results 带时间戳文件（不落库；schema v1）。"""
from __future__ import annotations

from datetime import date

from lkl.broker import fileio, trade_date
from lkl.models.types import Signal

_SCHEMA = 1


def load_decisions(for_date: str | None = None) -> list:
    """读最新 decisions_*.json 当日动作 → Signal[]；缺/日期不符返回空。"""
    target = date.fromisoformat(for_date) if for_date else date.fromisoformat(trade_date.trade_date())
    data = fileio.read("decisions")
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
    data = fileio.read("results")
    if data.get("for_date") != (for_date or trade_date.trade_date()):
        return []
    return data.get("trades", [])


def decision_date() -> str | None:
    return fileio.read("decisions").get("for_date")


def dump_results(for_date: str, trades: list) -> None:
    """写 results_{时间戳}.json（trades 已去重；每份唯一保留历史）。"""
    fileio.write("results", {"schema": _SCHEMA, "for_date": for_date, "trades": trades})