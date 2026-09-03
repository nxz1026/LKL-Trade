"""交换文件路径与 JSON 读取（exchange 的底层 IO，路径来自 config.trade_dir）。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from lkl.broker import config, session


def directory() -> Path:
    """交换目录（唯一来源 config.TRADE_DIR）。"""
    return config.trade_dir()


def decisions_path() -> Path:
    return directory() / "decisions.json"


def results_path() -> Path:
    return directory() / "results.json"


def read(name: str) -> dict:
    """读交换目录下 JSON；文件缺失返回空 dict。"""
    p = directory() / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def dump_json(name: str, payload: dict) -> None:
    """写固定名(契约) + 时间戳副本(日内多版本历史)。"""
    d = directory(); d.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    (d / name).write_bytes(body)
    stem, _, suf = name.rpartition(".")
    stamp = datetime.now(session.TZ).strftime("%Y%m%d_%H%M%S")
    (d / f"{stem}_{stamp}.{suf}").write_bytes(body)