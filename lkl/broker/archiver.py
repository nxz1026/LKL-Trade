"""归档：当日生成的带时间戳 JSON 收进 archive/<日期>/；消费即归档决策。"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from lkl.broker import fileio, session

_KINDS = ("decisions", "results", "holdings")


def archive_one(src, day=None):
    """只归档绑定到的一份文件（不搬同批未处理版本）。"""
    src = Path(src)
    day = day or datetime.now(session.TZ).date().isoformat()
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
    day = day or datetime.now(session.TZ).date().isoformat()
    return sum(consume(k, day) for k in _KINDS)


def run(argv: list[str]) -> int:
    day = argv[0] if argv and argv[0].strip() else None
    print(f"已归档 {pack(day)} 个 → archive/{day or datetime.now(session.TZ).date()}")
    return 0