"""配置唯一出口：env 优先、回退 .secrets/gm.env；禁散落 os.environ。

交易：GM_TOKEN/GM_ACCOUNT_ID/GM_ENDPOINT/GM_ENV_FILE/TRADE_DIR
时段：GM_HOLIDAYS(休市日补充)
风控：GM_RISK_MAX_QTY/GM_RISK_MAX_ORDERS/GM_RISK_MAX_CODES
对账/追溯：GM_RECON_ORDERS(对账联券商委托)、GM_KEEP_REMOTE(保留远端决策)
远端：GM_REMOTE_HOST/GM_REMOTE_KEY/GM_REMOTE_DIR(受限SFTP用户子目录)
模板见 .env.example，取值见 README。"""
from __future__ import annotations
import os
from pathlib import Path

_DEFAULTS = {"GM_ENDPOINT": "127.0.0.1:7001", "TRADE_DIR": "~/trade"}
_REPO = Path(__file__).resolve().parents[2]

def _env(key: str) -> str:
    return os.environ.get(key) or _DEFAULTS.get(key, "")

def secrets_file() -> Path:
    return Path(_env("GM_ENV_FILE") or str(_REPO / ".secrets" / "gm.env")).expanduser()

def _secret(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    f = secrets_file()
    if not f.exists():
        return ""
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip() and line.partition("=")[0] == name:
            return line.partition("=")[2].strip()
    return ""

def token() -> str:
    return _secret("GM_TOKEN")

def account_id() -> str:
    return _secret("GM_ACCOUNT_ID")

def endpoint() -> str:
    return _env("GM_ENDPOINT")

def trade_dir() -> Path:
    return Path(_env("TRADE_DIR")).expanduser()

def remote_host() -> str:
    return _secret("GM_REMOTE_HOST")

def remote_key() -> Path:
    return Path(_secret("GM_REMOTE_KEY")).expanduser()

def remote_dir() -> str:
    return _secret("GM_REMOTE_DIR")


def holidays() -> tuple:
    """休市日集合（YYYY-MM-DD 逗号分隔），来自 GM_HOLIDAYS 或 .secrets/gm.env。"""
    return tuple(x.strip() for x in _secret("GM_HOLIDAYS").split(",") if x.strip())


def risk_limits() -> dict:
    """风控护栏上限（0=不限制）：
    GM_RISK_MAX_QTY 单笔最大股数 / GM_RISK_MAX_ORDERS 当日最大下单次数 /
    GM_RISK_MAX_CODES 当日最多操作只数。
    """
    out = {}
    for key, name in (("GM_RISK_MAX_QTY", "max_qty"),
                      ("GM_RISK_MAX_ORDERS", "max_orders"),
                      ("GM_RISK_MAX_CODES", "max_codes")):
        raw = _env(key).strip()
        try:
            out[name] = int(raw) if raw else 0
        except ValueError:
            out[name] = 0
    return out
