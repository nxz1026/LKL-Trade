"""HTTP-based remote exchange for LKL-Trade (oracle Trade API).

Replaces SFTP file-based exchange with simple HTTP calls.
When GM_REMOTE_URL is set, uses HTTP mode; otherwise falls back to SFTP.

Batch tracking: processed_batches.json records which batch_ids have been
processed, providing simple idempotent deduplication.
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


def is_processed(batch_id: str) -> bool:
    if not batch_id:
        return False
    return batch_id in _load_batches().get("batches", [])


def mark_processed(batch_id: str):
    if not batch_id:
        return
    data = _load_batches()
    if batch_id not in data["batches"]:
        data["batches"].append(batch_id)
        _save_batches(data)


# ── HTTP API calls ───────────────────────────────────────────
def _api_url() -> str:
    """Get the Trade API base URL."""
    url = config.remote_url().rstrip("/")
    if not url:
        raise RemoteError("GM_REMOTE_URL not configured")
    return url


def http_pull_decisions(for_date: str | None = None) -> dict:
    """Pull decisions from oracle HTTP API. Returns dict with batch_id, actions, etc."""
    for_date = for_date or date.today().isoformat()
    url = f"{_api_url()}/decisions"
    resp = requests.get(url, params={"date": for_date}, timeout=10, verify=_ssl_verify())
    resp.raise_for_status()
    return resp.json()


def http_push_results(data: dict) -> dict:
    """Push results to oracle HTTP API."""
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
