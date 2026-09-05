"""归档：带时间戳 JSON 收进 archive/<日期>/；消费即归档决策。

归档目录统一按文件名时间戳（生成日）落盘，与 consume/pack 的按文件名日期归档
语义一致；is_archived 是「该决策是否已消费归档」的权威判定，业务层不再自行推导。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from lkl.broker import fileio, session

_KINDS = ("decisions", "results", "holdings")


def day_from_name(name: str) -> str:
    """文件名时间戳 → 归档日（YYYY-MM-DD）：{kind}_{YYYYMMDD_HHMMSS}.json。

    文件名的日期是生成时刻（可先于 for_date 生成，如隔夜投递）；归档目录与守卫
    判定都用它，保证消费判定与实际落盘路径永远一致。
    """
    ts = name.split("_")[1] if name.count("_") >= 2 else ""
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) >= 8 else ""


def is_archived(name: str) -> bool:
    """归档目录中是否存在同名文件（消费判定的唯一权威来源）。

    供 tradeops 判定决策是否已消费：查的是 archive_one 实际落盘的同一路径，
    不依赖业务层对文件名/目录规则的重复推导（防重发 results 双份 bug）。
    """
    return (fileio.directory() / "archive" / day_from_name(name) / name).exists()


def archive_one(src, day=None):
    """只归档绑定到的一份文件（不搬同批未处理版本）。

    归档目录默认取文件名时间戳（与 consume/pack 语义一致，is_archived 同路径命中）；
    显式传 day 时覆盖（供 pack/手工归档用）。
    """
    src = Path(src)
    day = day or day_from_name(src.name) or session.now().date().isoformat()
    dest = fileio.directory() / "archive" / day
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / src.name
    i = 1
    while target.exists():
        target = dest / f"{src.stem}_{i}{src.suffix}"
        i += 1
    shutil.move(str(src), str(target))
    return target


def consume(kind: str, day: str) -> int:
    """把该日(kind=YYYYMMDD_*)所有版本移入 archive/<day>/；返回条数。"""
    dest = fileio.directory() / "archive" / day
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    prefix = f"{kind}_{day.replace('-', '')}_"
    for src in sorted(fileio.directory().glob(f"{kind}_*"),
                      key=lambda p: p.name):
        if not src.name.startswith(prefix):
            continue
        target = dest / src.name
        i = 1
        while target.exists():
            target = dest / f"{src.stem}_{i}{src.suffix}"
            i += 1
        shutil.move(str(src), str(target))
        n += 1
    return n


def pack(day: str | None = None) -> int:
    day = day or session.now().date().isoformat()
    return sum(consume(k, day) for k in _KINDS)


def run(argv: list[str]) -> int:
    day = argv[0] if argv and argv[0].strip() else None
    print(f"已归档 {pack(day)} 个 → archive/{day or session.now().date()}")
    return 0