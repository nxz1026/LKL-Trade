"""交换文件 = 带时间戳名 {kind}_YYYYMMDD_HHMMSS.json；读取取最新一份。

- 命名遵循 v2 契约：时间戳秒级、时区一律 Asia/Shanghai(+8)，勿用 UTC。
- 写采用「临时文件 + os.replace 原子改名」，读者只可能看到完整旧版或完整新版。
  sort(文件名) 即时间序，读「当日最新」取倒序第一份。
- 读分两族：执行路径 read/read_path 显式失败（损坏即抛，绝不静默当空）；
  展示路径 read_json_safe 兜底返回 None（看板等只读场景）。
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
    """读「该 kind 最新一份」；无文件返回 {}。损坏上抛（执行路径要显式失败，不静默当空）。"""
    p = latest(kind)
    return json.loads(p.read_text(encoding="utf-8")) if p else {}


def read_path(p: Path | None) -> dict:
    """读指定路径文件；None/无文件返回 {}。与 read 的区别：read 自动定位最新版，read_path 用显式路径。"""
    return json.loads(p.read_text(encoding="utf-8")) if p else {}


def read_json_safe(p: Path | None) -> dict | None:
    """读 JSON 文件；缺失/损坏返回 None（不抛）。看板/预演等只读展示路径使用。"""
    if not p:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeDecodeError):
        return None


def remove(name: str) -> None:
    """删除交换目录内一份文件（清理远端已消费决策的本地同名残留）。"""
    (directory() / name).unlink()


def _p2(v):
    """交换文件数值收缩：价格一律保留 2 位小数（A股最小变动 0.01）。

    递归收敛 dict/list 中所有 float；int/bool/str/None 原样 —— 决策 volume
    取整不在此列，价格字段（results price/avg_price、holdings cost/price/
    vwap/last_price/fpnl）全部 2 位，DB 对账与展示一致。
    """
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, dict):
        return {k: _p2(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_p2(x) for x in v]
    return v


def write(kind: str, payload: dict) -> Path:
    """写 {kind}_{时间戳}.json（原子，每份唯一，历史即版本）；价格收敛 2 位。"""
    d = directory()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{kind}_{_stamp()}.json"
    atomic_write(p, json.dumps(_p2(payload), ensure_ascii=False, indent=2))
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