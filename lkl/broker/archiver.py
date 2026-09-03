"""归档：JSON 移入 archive/<日期>/，防同名覆盖丢历史；撞名加时间戳后缀不覆盖已有。"""
from __future__ import annotations

import shutil
from datetime import datetime

from lkl.broker import fileio, session

_NAMES = ("decisions.json", "results.json", "holdings.json", "executed.json")


def _target(day: str, src: object) -> object:
    folder = fileio.directory() / "archive" / day
    folder.mkdir(parents=True, exist_ok=True)
    t = folder / src.name
    n = 1
    while t.exists():
        t = folder / f"{src.stem}_{datetime.now(session.TZ):%H%M%S}_{n}{src.suffix}"
        n += 1
    return t


def _move_one(name: str, day: str) -> int:
    src = fileio.directory() / name
    if not src.exists():
        return 0
    shutil.move(str(src), str(_target(day, src)))
    return 1


def pack_one(name: str, day: str) -> int:
    """单个文件即时归档（消费即归档，供 process 后调用）。"""
    return _move_one(name, day)


def pack(day: str | None = None) -> int:
    """盘后归档存量四件套；返回条数。"""
    day = day or datetime.now(session.TZ).date().isoformat()
    return sum(_move_one(n, day) for n in _NAMES)


def run(argv: list[str]) -> int:
    """lkl archive [YYYY-MM-DD]：手动归档该日文件。"""
    day = argv[0] if argv and argv[0].strip() else None
    print(f"已归档 {pack(day)} 个 → archive/{day or datetime.now(session.TZ).date()}")
    return 0