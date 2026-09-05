"""单执行器锁：同一交换目录同时只允许一个执行权持有者。

`sup` / `trade` / `trade watch` 启动必须先抢占该锁，
抢不到即明确退出，绝不并行处理同一决策。Windows 用 msvcrt 字节锁，
POSIX 用 fcntl.flock（均跨进程的 advisory 锁，双方都遵守即有效）。
"""
from __future__ import annotations

import os
from pathlib import Path

from lkl.broker import fileio


class ExecutorBusyError(RuntimeError):
    """另一执行器已持有锁，拒绝重复启动。"""


def _try_lock(fh):
    if os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fh):
    if os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class single_executor:
    """with single_execution("sup"): …  —— 进程内/跨进程单写者。"""

    def __init__(self, owner: str = "trade"):
        self.owner = owner
        self.path: Path = fileio.directory() / ".lkl.lock"
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            # 空文件先落 1 字节，保证有可锁区间
            if fh.seek(0, 2) == 0:
                fh.write(b"\0")
                fh.flush()
            fh.seek(0)
            _try_lock(fh)
        except OSError:
            fh.close()
            raise ExecutorBusyError(
                f"交换目录 {self.path.parent} 已有执行器持有锁——拒绝并发执行") from None
        fh.seek(0)
        fh.truncate()
        fh.write(f"{self.owner} pid={os.getpid()}".encode("utf-8"))
        fh.flush()
        self._fh = fh
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            try:
                _unlock(self._fh)
            finally:
                self._fh.close()
                self._fh = None
        return False