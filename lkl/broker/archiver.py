"""盘后归档：把已成功消费/产出的当日 JSON 移入 archive/<日期>/，防同名覆盖丢历史。

安全前提：仅在上一个交易日收盘后调用（supervisor 跨日翻转 / 手动 lkl archive），
盘中/正在消费时不调用；同日目录已存在则给文件加时间戳后缀防撞名。
"""
from __future__ import annotations

import shutil
from datetime import datetime

from lkl.broker import fileio, session

_NAMES = ("decisions.json", "results.json", "holdings.json", "executed.json")


def _dest(dst: object, day: str) -> object:
    """目标路径撞名则加 _HHMMSS[_n] 后缀。"""
    folder = fileio.directory() / "archive" / day
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / dst.name
    n = 1
    while target.exists():
        target = folder / f"{dst.stem}_{datetime.now(session.TZ):%H%M%S}_{n}{dst.suffix}"
        n += 1
    return target


def pack(day: str | None = None) -> int:
    """归档指定交易日（默认今天 Shanghai）trade/ 下的存量 JSON；返回归档数。"""
    day = day or datetime.now(session.TZ).date().isoformat()
    n = 0
    for name in _NAMES:
        src = fileio.directory() / name
        if not src.exists():
            continue
        shutil.move(str(src), str(_dest(src, day)))
        n += 1
    return n


def run(argv: list[str]) -> int:
    """lkl archive [YYYY-MM-DD]：手动归档该交易日文件。"""
    day = argv[0] if argv and argv[0].strip() else None
    n = pack(day)
    print(f"已归档 {n} 个文件 → archive/{day or datetime.now(session.TZ).date()}")
    return 0