"""掘金仿真凭据与接入配置：env 优先，回退 gitignored 的 .secrets/gm.env。

遵循仓库纪律（同 ~/.dbconfig）：token/account_id 不入库不入代码文件。
"""
from __future__ import annotations

import os
from pathlib import Path

SECRETS_FILE = Path(__file__).resolve().parents[2] / ".secrets" / "gm.env"
# 掘金新流程：本地跑金矿终端(Hongshu Goldminer3)，SDK 连 127.0.0.1:7001；云端 api.myquant.cn:9000 已不部署(V11.5)
ENDPOINT_DEFAULT = "127.0.0.1:7001"


def _file_values() -> dict:
    """解析 .secrets/gm.env 的 K=V 行；文件缺失返回空表。"""
    if not SECRETS_FILE.exists():
        return {}
    values: dict[str, str] = {}
    for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _pick(name: str) -> str:
    """env 优先，其次 .secrets/gm.env。"""
    return os.environ.get(name) or _file_values().get(name, "")


def token() -> str:
    """掘金用户 token（身份识别，等同账号+密码，勿泄露）。"""
    return _pick("GM_TOKEN")


def account_id() -> str:
    return _pick("GM_ACCOUNT_ID")


def endpoint() -> str:
    return _pick("GM_ENDPOINT") or ENDPOINT_DEFAULT