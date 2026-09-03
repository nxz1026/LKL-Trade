"""远端策略交换目录 SSH 同步：拉 decisions、推 results/holdings（env 开关，免手工拷贝）。

scp 直连策略机 `/home/ubuntu/DSH/.../trade`；未配置 GM_REMOTE_HOST 时 no-op 走本地。
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from lkl.broker import config, fileio

log = logging.getLogger("lkl.remote")


def enabled() -> bool:
    """配置了远端主机即启用。"""
    return bool(config.remote_host())


def _target() -> str:
    return f"{config.remote_host()}:{config.remote_dir()}"


def _scp(args: list) -> bool:
    base = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new",
            "-i", str(config.remote_key())]
    return subprocess.run(base + args, timeout=30,
                          capture_output=True).returncode == 0


def pull(name: str) -> bool:
    """远端 → 本地；未启用/失败返回 False（不阻断本地交易）。"""
    if not enabled():
        return True
    ok = _scp([f"{_target()}/{name}", str(fileio.directory() / name)])
    if not ok:
        log.warning("拉取远端 %s 失败", name)
    return ok


def push(name: str) -> bool:
    """本地 → 远端；未启用返回 True。"""
    if not enabled():
        return True
    ok = _scp([str(fileio.directory() / name), f"{_target()}/"])
    if not ok:
        log.warning("推送远端 %s 失败", name)
    return ok