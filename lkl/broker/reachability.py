"""连通性预检：TCP 测仿真服务端口（判网络层拦不拦，不等 SDK）。"""
from __future__ import annotations

import socket


def endpoint_reachable(endpoint: str) -> bool:
    """TCP 连一次目标 host:port；拒绝/超时返回 False。"""
    host, sep, port = endpoint.rpartition(":")
    if not sep:
        return False
    try:
        sock = socket.create_connection((host, int(port)), timeout=5)
        sock.close()
        return True
    except OSError:
        return False