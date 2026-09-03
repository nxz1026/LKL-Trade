"""执行防重账本：executed.json 持久记录已执行 ref（跨日，防 results 丢后重下单）。"""
from __future__ import annotations

import json

from lkl.broker import fileio


def _path():
    return fileio.directory() / "executed.json"


def load() -> set:
    """已执行 ref 集合 {for_date:list} 平铺为 set。"""
    if not _path().exists():
        return set()
    return set(_load().get("refs", []))


def _load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {"refs": []}


def mark(refs) -> None:
    """把新执行 ref 合并写入 executed.json（持久，幂等）。"""
    cur = _load()
    merged = sorted(set(cur.get("refs", [])) | set(refs))
    _path().write_text(json.dumps({"refs": merged}, ensure_ascii=False,
                                  indent=1), encoding="utf-8")