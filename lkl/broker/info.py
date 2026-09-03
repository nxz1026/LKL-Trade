"""基本用户信息：登录模拟盘并取回账户/资金/持仓。"""
from __future__ import annotations

from . import client, queries
from .models import UserInfo


def user_info() -> UserInfo:
    """连接模拟盘并组合基本用户信息；连接失败上抛。"""
    acc = client.connect()
    return UserInfo(
        account_id=acc,
        cash=queries.cash(),
        positions=queries.positions(),
    )