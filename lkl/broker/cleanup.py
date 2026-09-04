"""盘后终结：远端已消费并归档的最新 decisions → 删除（for_date 守卫防删新一天）。

v2：受限 SFTP，无 shell，不能 `cat` 远端文件；改为先把最新 decisions 拉到本地，
解析 for_date 与 day 一致才删对应文件。

v3 修正：守卫校验不再经 `remote.pull()` 落盘——那会把远端 decisions 残留进本地
交换目录，次轮 process_once 的 decision_file() 命中残留 → 重发 results（双份 bug）。
直接按文件名解析 for_date（决策身份即文件名，见 remote._FNAME 契约），并清理
远端已消费文件留下的本地同名残留。
"""
from __future__ import annotations

import logging

from lkl.broker import fileio, remote

log = logging.getLogger("lkl.cleanup")


def _for_date_from_name(name: str) -> str:
    """决策身份即文件名（{kind}_{YYYYMMDD_HHMMSS}.json）：从时间戳推导 for_date（ISO）。"""
    ts = name.split("_")[1] if name.count("_") >= 2 else ""
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) >= 8 else ""


def remove_archived_name(name: str) -> int:
    """按具体文件名删除远端决策 + 本地同名残留；返回 0/1。"""
    if not remote.enabled():
        return 0
    remote.rm(name)
    log.info("已删除远端已消费决策 %s", name)
    try:
        fileio.remove(name)
    except OSError as e:
        log.warning("本地残留清理失败 %s: %s", name, e)
    return 1


def remove_archived(day: str) -> int:
    """远端最新 decisions 的 for_date 恰为 day 才删；返回删除数 0/1（兼容旧调用）。"""
    if not remote.enabled():
        return 0
    base = remote.newest("decisions")
    if not base:
        return 0
    fd = _for_date_from_name(base)
    if fd != day:
        log.info("远端决策 %s 是 %s(≠%s)，保留", base, fd or "未知", day)
        return 0
    return remove_archived_name(base)