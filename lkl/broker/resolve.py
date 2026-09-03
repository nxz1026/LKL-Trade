"""人工处置入口（产品7-建议5）：拒单/部分成交/持仓不符 → 明确处置并留痕。

写入 exchange 目录 `resolved.json`：
  {ref: {"action": "retry"|"ignore"|"complete", "by": str, "at": ISO, "note": str}}

- ``retry``：清除在途/防重后放行自动重试（下一轮 process_once 会再尝试）。
- ``ignore``：明确放弃该 ref（等同 EXCLUDED 语义：不再自动下单/重试，文件可归档）。
- ``complete``：人工确认完成（入防重账本，等同已成交语义，不再重试）。
供 `lkl trade resolve <for_date>|<code> <action> [note]` 使用。
"""
from __future__ import annotations

import json

from lkl.broker import fileio, session

_ACTIONS = ("retry", "ignore", "complete")


def _path():
    return fileio.directory() / "resolved.json"


def _load() -> dict:
    if not _path().exists():
        return {}
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _save(m: dict) -> None:
    fileio.atomic_write(_path(), json.dumps(m, ensure_ascii=False, indent=1))


load = _load  # 公开读取（tradeops 使用）


def resolve(ref: str, action: str, by: str = "manual", note: str = "") -> str:
    if action not in _ACTIONS:
        raise ValueError(f"非法处置 {action!r}（{'/'.join(_ACTIONS)}）")
    m = _load()
    m[ref] = {"action": action, "by": by, "note": note,
              "at": session.now().isoformat(timespec="seconds")}
    _save(m)
    return action


def apply(m: dict, ref: str) -> str | None:
    """process_once 调用：按处置决定 ref 命运；返回 'done'|'skip'|None(照常)。"""
    rec = m.get(ref)
    if not rec:
        return None
    act = rec.get("action")
    if act == "ignore":
        return "skip"           # 放弃：不自动下单/重试
    if act == "complete":
        return "done"           # 人工完成：按已成交处理
    return None                  # retry：放行（清除标记，让正常重试走）


def dismiss(ref: str) -> None:
    m = _load()
    m.pop(ref, None)
    _save(m)


def run_cli(ref: str, action: str, note: str = "") -> str:
    r = resolve(ref, action, note=note)
    return f"已记录 {ref} → {r}"
