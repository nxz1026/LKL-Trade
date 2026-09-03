"""交换文件路径与 JSON 读取（exchange 的底层 IO，路径来自 config.trade_dir）。"""
from __future__ import annotations

import json
from pathlib import Path

from lkl.broker import config


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