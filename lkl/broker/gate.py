"""金矿终端就绪门：轮询 7001，未达则等待不报错（供 supervisor 用）。"""
from __future__ import annotations

import time

from lkl.broker import config, reachability

_RETRY = 30


def up() -> bool:
    """终端服务此刻可达？"""
    return reachability.endpoint_reachable(config.endpoint())


def wait(timeout: float = 300.0, step: float = 5.0) -> bool:
    """等到终端可达或超时；返回最终是否就绪。"""
    end = time.time() + timeout
    while time.time() < end:
        if up():
            return True
        time.sleep(step)
    return up()