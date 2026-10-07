"""HTTP-based remote exchange for LKL-Trade (oracle emotion-core Trade API).

Replaces SFTP file-based exchange with simple HTTP calls.
When GM_REMOTE_URL is set, uses HTTP mode; otherwise falls back to SFTP.

Batch tracking: processed_batches.json records which batch_ids have been
processed, providing simple idempotent deduplication.

Server: emotion-core presentation layer (Python standard library http.server)
- nginx at /trade/ proxies to emotion-core :8098/api/trade/
- Decisions generated from strategy_signal table via gen_decisions.py
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

import requests

from lkl.broker import config, fileio

LOG = logging.getLogger("lkl.remote_http")
BATCHES_FILE = Path("processed_batches.json")


# ── batch tracking ───────────────────────────────────────────
# ⚠️ 2026-10-07：key 加**来源维度**。原实现只用 batch_id 作键，而 batch_id 是
# 上游生成的 UUID4 —— 两个上游各自为政时空间独立，撞车概率极低；但一旦同一
# 个交易机接了 emotion-core 与 CPT 两个上游，且某个上游**复用了** batch_id
# （重放、重试、从旧备份恢复），第二份决策会被静默跳过。这里显式分桶，
# 不依赖「UUID 不会撞」这种运气。
def _key(batch_id: str, source: str = "") -> str:
    return f"{source}:{batch_id}" if source else batch_id


def _load_batches() -> dict:
    p = fileio.directory() / BATCHES_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {"batches": []}
    return {"batches": []}


def _save_batches(data: dict):
    p = fileio.directory() / BATCHES_FILE
    fileio.atomic_write(p, json.dumps(data, ensure_ascii=False, indent=2))


def is_processed(batch_id: str, source: str = "") -> bool:
    if not batch_id:
        return False
    return _key(batch_id, source) in _load_batches().get("batches", [])


def mark_processed(batch_id: str, source: str = ""):
    if not batch_id:
        return
    key = _key(batch_id, source)
    data = _load_batches()
    if key not in data["batches"]:
        data["batches"].append(key)
        _save_batches(data)


# ── HTTP API calls ───────────────────────────────────────────
def _api_url() -> str:
    """Get the Trade API base URL (e.g., https://140.83.62.161/trade)."""
    url = config.remote_url().rstrip("/")
    if not url:
        raise RemoteError("GM_REMOTE_URL not configured")
    return url


def http_pull_decisions(for_date: str | None = None) -> dict:
    """Pull decisions from oracle emotion-core Trade API.
    
    Returns dict with batch_id, for_date, actions[].
    Empty actions list means no decisions for the date.
    """
    for_date = for_date or date.today().isoformat()
    url = f"{_api_url()}/decisions"
    resp = requests.get(url, params={"date": for_date}, timeout=10, verify=_ssl_verify())
    resp.raise_for_status()
    return resp.json()


def http_push_results(data: dict) -> dict:
    """Push results to oracle emotion-core Trade API.
    
    Returns dict with status, batch_id, and optionally note (idempotent).
    """
    url = f"{_api_url()}/results"
    resp = requests.post(url, json=data, timeout=10, verify=_ssl_verify())
    resp.raise_for_status()
    return resp.json()


def _ssl_verify() -> bool | str:
    """SSL verification: False for self-signed certs, or path to CA cert."""
    val = os.environ.get("GM_SSL_VERIFY", "false").lower()
    if val in ("false", "0", "no"):
        return False
    if val in ("true", "1", "yes"):
        return True
    return val  # treat as path to CA cert


class RemoteError(RuntimeError):
    """HTTP remote exchange failure."""
