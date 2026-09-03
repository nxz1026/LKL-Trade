"""配置唯一出口：env 优先、回退 .secrets/gm.env；禁散落 os.environ。
GM_TOKEN/GM_ACCOUNT_ID/GM_ENDPOINT/TRADE_DIR/GM_ENV_FILE/GM_REMOTE_*。"""
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
