"""执行防重账本：executed.json 持久记录「已确认成交」ref（跨日，防丢重下）。

按审查 P0-01/P0-03：只有 FILLED 才会 mark；账本损坏**阻断交易并上抛**，
绝不静默回退为空（否则会把全部历史决策重新下单）。
写采用原子改名，读侧不会看到半截账本。
"""
from __future__ import annotations

import json

from lkl.broker import fileio


class LedgerCorruptError(RuntimeError):
    """executed.json 不可解析/损坏——必须阻断交易而非当作空账本。"""


def _path():
    return fileio.directory() / "executed.json"


def _load() -> dict:
    p = _path()
    if not p.exists():
        return {"refs": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeDecodeError) as e:
        raise LedgerCorruptError(f"executed.json 损坏：{e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("refs"), list):
        raise LedgerCorruptError("executed.json 结构非法（refs 缺失/非列表）")
    return data


def load() -> set:
    """已执行 ref 集合；账本损坏时上抛 LedgerCorruptError。"""
    return set(_load().get("refs", []))


def mark(refs) -> None:
    """把已终态成交 ref 合并写入 executed.json（原子、持久、幂等）。"""
    cur = _load()
    merged = sorted(set(cur.get("refs", [])) | set(refs))
    fileio.atomic_write(
        _path(),
        json.dumps({"refs": merged}, ensure_ascii=False, indent=1))