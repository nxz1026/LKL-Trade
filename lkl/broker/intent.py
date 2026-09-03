"""下单意图日志（pending.json）：可重启一致性的关键（对应审查 P0-03）。

顺序：**先**持久记录「意图(ref, 目标单量)」→ 再向券商下单 → 拿到 order_id 回填 →
查询终态后结清。进程在任一环节崩溃，重启后：
- 有 order_id 的 → 向券商对账该委托终态（FILLED 才算 done，其作按状态结清）。
- 无 order_id 的（崩在下单瞬间）→ 本轮不重下该 ref，保留在行免得重复。

同一 ref 只要还有在途记录，就绝不再重复提交（防 P0-04 并发/崩溃双下）。
"""
from __future__ import annotations

import json

from lkl.broker import fileio

_PEND = "pending"


class PendingCorruptError(RuntimeError):
    """pending.json 损坏——须阻断交易而非当作空。"""


def _path():
    return fileio.directory() / f"{_PEND}.json"


def load() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeDecodeError) as e:
        raise PendingCorruptError(f"pending.json 损坏：{e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("refs"), dict):
        raise PendingCorruptError("pending.json 结构非法（refs 缺失/非对象）")
    return data["refs"]


def _dump(refs: dict) -> None:
    fileio.atomic_write(_path(), json.dumps({"refs": refs}, ensure_ascii=False, indent=1))


def record(ref: str, order_id: str = "", status: str = "SUBMITTED",
           qty: int = 0) -> None:
    """登记一条待审批在途（幂等；不覆盖已有 order_id）。"""
    refs = load()
    cur = refs.get(ref, {})
    cur.setdefault("order_id", order_id)
    if order_id:
        cur["order_id"] = order_id
    cur["status"] = status
    cur["qty"] = qty
    refs[ref] = cur
    _dump(refs)


def has(ref: str) -> bool:
    return ref in load()


def finish(ref: str) -> None:
    """终态结清：从在途移除（唯一确定不再据此下单的路径）。"""
    refs = load()
    refs.pop(ref, None)
    _dump(refs)