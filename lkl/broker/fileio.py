"""交换文件 = 带时间戳名 {kind}_{YYYYMMDD_HHMMSS}.json；读取取最新一份（默认回退固定名）。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from lkl.broker import config, session


def directory() -> Path:
    return config.trade_dir()


def _stamp() -> str:
    return datetime.now(session.TZ).strftime("%Y%m%d_%H%M%S")


def latest(kind: str) -> Path | None:
    """最新一份 {kind}_*.json（按文件名倒序）；无则 None。"""
    fs = sorted(directory().glob(f"{kind}_*.json"), key=lambda p: p.name, reverse=True)
    return fs[0] if fs else None


def read(kind: str) -> dict:
    p = latest(kind)
    return json.loads(p.read_text(encoding="utf-8")) if p else {}


def write(kind: str, payload: dict) -> Path:
    """写 {kind}_{YYYYMMDD_HHMMSS}.json（每份唯一，历史即版本）。"""
    d = directory(); d.mkdir(parents=True, exist_ok=True)
    p = d / f"{kind}_{_stamp()}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p