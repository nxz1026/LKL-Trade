"""远端策略交换目录 SSH 同步：拉/推「最新带时间戳」文件；未配置则纯本地。"""
from __future__ import annotations
import subprocess
from lkl.broker import config, fileio


def enabled() -> bool:
    return bool(config.remote_host())


def _ssh(cmd: list) -> str:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                           "-i", str(config.remote_key()), config.remote_host(), *cmd],
                          capture_output=True, text=True).stdout.strip()


def _scp(a: list) -> bool:
    base = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new", "-i", str(config.remote_key())]
    return subprocess.run(base + a, timeout=30, capture_output=True).returncode == 0

def newest(kind: str) -> str:
    """远端最新 basename；无则 ''。"""
    return _ssh(["sh", "-c",
                 f"ls -1t {config.remote_dir()}/{kind}_*.json 2>/dev/null | head -n1"])


def rm(base: str) -> bool:
    if not enabled() or not base:
        return True
    _ssh(["sh", "-c", f"rm -f '{config.remote_dir()}/{base}'"])
    return True


def pull(kind: str) -> bool:
    if not enabled():
        return True
    name = newest(kind)
    if not name:
        return True
    dst = f"{config.remote_host()}:{config.remote_dir()}/{name}"
    return _scp([dst, str(fileio.directory() / name)])


def push(kind: str) -> bool:
    if not enabled():
        return True
    p = fileio.latest(kind)
    if not p:
        return True
    return _scp([str(p), f"{config.remote_host()}:{config.remote_dir()}/"])