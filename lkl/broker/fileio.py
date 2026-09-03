"""交换文件 = 带时间戳名 {kind}_YYYYMMDD_HHMMSS.json；读取取最新一份。

- 命名遵循 v2 契约：时间戳秒级、时区一律 Asia/Shanghai(+8)，勿用 UTC。
- 写采用「临时文件 + os.replace 原子改名」，读者只可能看到完整旧版或完整新版
  （P1-06）。sort(文件名) 即时间序，读「当日最新」取倒序第一份。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from lkl.broker import config, session


def directory() -> Path:
    return config.trade_dir()


def _stamp() -> str:
    # v2 契约：{kind}_YYYYMMDD_HHMMSS.json，Asia/Shanghai(+8)
    return datetime.now(session.TZ).strftime("%Y%m%d_%H%M%S")


def versions(kind: str) -> list:
    """某 kind 全部带时间戳文件（按文件名倒序）。"""
    return sorted(directory().glob(f"{kind}_*.json"),
                  key=lambda p: p.name, reverse=True)


def latest(kind: str) -> Path | None:
    """最新一份 {kind}_*.json；无则 None。"""
    fs = versions(kind)
    return fs[0] if fs else None


def read(kind: str) -> dict:
    p = latest(kind)
    return json.loads(p.read_text(encoding="utf-8")) if p else {}


def read_path(p: Path | None) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p else {}


def write(kind: str, payload: dict) -> Path:
    """写 {kind}_{时间戳}.json（原子，每份唯一，历史即版本）。"""
    d = directory()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{kind}_{_stamp()}.json"
    atomic_write(p, json.dumps(payload, ensure_ascii=False, indent=2))
    return p


def atomic_write(target: Path, text: str) -> None:
    """临时文件 + os.replace 原子落盘；异常时清理临时文件并上抛。"""
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise