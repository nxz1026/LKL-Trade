"""交换文件路径与 JSON 读取（exchange 的底层 IO，单独模块控体积）。"""
from __future__ import annotations

import json
import os
from pathlib import Path


def directory() -> Path:
    """交换目录：TRADE_DIR 或 LKL_TRADE_DIR（DB侧名）优先，默认 ~/trade。"""
    d = os.environ.get("TRADE_DIR") or os.environ.get("LKL_TRADE_DIR")
    return Path(d or "~/trade").expanduser()


def decisions_path() -> Path:
    return directory() / "decisions.json"


def results_path() -> Path:
    return directory() / "results.json"


def read(name: str) -> dict:
    """读交换目录下 JSON；文件缺失返回空 dict。"""
    p = directory() / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}