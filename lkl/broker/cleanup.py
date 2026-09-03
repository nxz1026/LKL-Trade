"""盘后终结：远端已消费并归档的 decisions.json → 删除（for_date 守卫防删新一天）。"""
from __future__ import annotations

import json
import logging
import subprocess

from lkl.broker import config, remote

log = logging.getLogger("lkl.cleanup")


def _ssh(args: list) -> str:
    if not remote.enabled():
        return ""
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                        "-i", str(config.remote_key()), config.remote_host(), *args],
                       capture_output=True, text=True)
    return r.stdout.strip()


def remove_archived(day: str) -> int:
    """远端 decisions 的 for_date 恰为 day（本地已归档）才删；返回删除数 0/1。"""
    path = f"{config.remote_dir()}/decisions.json"
    out = _ssh(["cat", path])
    if not out:
        return 0  # 远端无此文件/不可达
    try:
        fd = json.loads(out).get("for_date")
    except ValueError:
        log.warning("远端 decisions 解析失败，跳过删除")
        return 0
    if fd != day:
        log.info("远端 decisions 是 %s(≠%s)，保留不删", fd, day)
        return 0
    _ssh(["rm", "-f", path])
    log.info("已删除远端已归档决策 %s", path)
    return 1