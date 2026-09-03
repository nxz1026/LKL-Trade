"""盘后终结：远端已消费并归档的最新 decisions → 删除（for_date 守卫防删新一天）。"""
from __future__ import annotations

import json
import logging

from lkl.broker import config, remote

log = logging.getLogger("lkl.cleanup")


def remove_archived(day: str) -> int:
    """远端最新 decisions 的 for_date 恰为 day 才删；返回删除数 0/1。"""
    if not remote.enabled():
        return 0
    base = remote.newest("decisions")
    if not base:
        return 0
    out = remote._ssh(["cat", f"{config.remote_dir()}/{base}"])
    try:
        fd = json.loads(out).get("for_date")
    except ValueError:
        log.warning("远端 %s 解析失败，跳过删除", base)
        return 0
    if fd != day:
        log.info("远端决策 %s 是 %s(≠%s)，保留", base, fd, day)
        return 0
    remote.rm(base)
    log.info("已删除远端已消费决策 %s", base)
    return 1