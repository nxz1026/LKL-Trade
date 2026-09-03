"""掘金仿真连接：凭据配置 + 登录模拟账户（gmtrade SDK 薄壳）。"""
from __future__ import annotations

import logging

from . import config, queries

log = logging.getLogger("lkl.broker")


def connect() -> str:
    """配置凭据并登录；返回 account_id。失败抛 ConnectionError/RuntimeError。"""
    from gmtrade.api import set_token, set_endpoint, account, login
    tok, acc, ep = config.token(), config.account_id(), config.endpoint()
    if not tok or not acc:
        raise RuntimeError("未配置 GM_TOKEN/GM_ACCOUNT_ID（.secrets/gm.env 或环境变量）")
    set_token(tok)
    set_endpoint(ep)
    login(account(account_id=acc, account_alias="模拟账户"))
    if queries.cash() is None:
        raise ConnectionError(
            f"无法连接仿真交易服务 {ep}：端口拒绝（10061）。"
            "掘金仿真 9000 端口限制海外来源，需在境内可达网络运行。")
    log.info("仿真账户登录成功 account=%s endpoint=%s", acc, ep)
    return acc