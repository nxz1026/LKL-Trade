"""盘后终结：远端已消费并归档的最新 decisions → 删除（for_date 守卫防删新一天）。

v2：受限 SFTP，无 shell，不能 `cat` 远端文件；改为先把最新 decisions 拉到本地，
解析 for_date 与 day 一致才删对应文件。
"""
from __future__ import annotations

import logging

from lkl.broker import fileio, remote

log = logging.getLogger("lkl.cleanup")


def remove_archived(day: str) -> int:
    """远端最新 decisions 的 for_date 恰为 day 才删；返回删除数 0/1。"""
    if not remote.enabled():
        return 0
    base = remote.newest("decisions")
    if not base:
        return 0
    remote.pull("decisions")           # 经 sftp 拉回本地解析
    fd = fileio.read("decisions").get("for_date")
    if fd != day:
        log.info("远端决策 %s 是 %s(≠%s)，保留", base, fd, day)
        return 0
    remote.rm(base)
    log.info("已删除远端已消费决策 %s", base)
    return 1