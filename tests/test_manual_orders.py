"""manual_orders 回捞测试：manifest 生成、source 区分、增量幂等、状态变化触发新写。"""
from __future__ import annotations

import json
import sys
import types

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """交换目录指向临时目录，且关闭远端 SSH（纯本地，不触网）。"""
    from lkl.broker import config
    monkeypatch.setitem(config._DEFAULTS, "TRADE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "remote_host", lambda: "")
    monkeypatch.setattr(config, "remote_dir", lambda: "")
    # 假 gmtrade：CI/本机无掘金 SDK 也能导入 status 模块
    gm = types.ModuleType("gmtrade")
    api = types.ModuleType("gmtrade.api")
    api.get_orders = lambda: []
    gm.api = api
    monkeypatch.setitem(sys.modules, "gmtrade", gm)
    monkeypatch.setitem(sys.modules, "gmtrade.api", api)
    return tmp_path


def _mo():
    from lkl.broker import manual_orders
    return manual_orders


def _today():
    from lkl.broker import trade_date
    return trade_date.trade_date()


def _order(oid="oid-1", symbol="SHSE.600000", side="买", filled=100,
           total=100, price=10.0, status="FILLED", label="已成交"):
    return {"id": oid[:8], "full_id": oid, "symbol": symbol, "side": side,
            "volume": total, "price": price, "filled": filled,
            "remaining": max(total - filled, 0), "status": status,
            "status_label": label}


def _manifest():
    from lkl.broker import fileio
    p = fileio.latest("manual_orders")
    assert p is not None, "manual_orders manifest 未生成"
    return json.loads(p.read_text(encoding="utf-8"))


def test_fetch_writes_manifest_source_manual(env, monkeypatch):
    monkeypatch.setattr(_mo(), "list_orders", lambda: [_order()])
    assert _mo().fetch() == 1
    data = _manifest()
    assert data["for_date"] == _today()
    assert data["schema"] == 1
    row = data["orders"][0]
    assert row["source"] == "manual"
    assert row["action"] == "BUY"
    assert row["code"] == "600000"
    assert row["ok"] is True and row["confirmed"] is True
    assert row["order_id"] == "oid-1"
    assert row["ref"] == f"{_today()}|600000|BUY|oid-1"


def test_fetch_idempotent_no_new_file(env, monkeypatch):
    monkeypatch.setattr(_mo(), "list_orders", lambda: [_order()])
    assert _mo().fetch() == 1
    n = len(list(env.glob("manual_orders_*.json")))
    assert _mo().fetch() == 0
    assert len(list(env.glob("manual_orders_*.json"))) == n


def test_fetch_status_change_triggers_new_manifest(env, monkeypatch):
    state = {"status": "FILLED", "label": "已成交"}
    monkeypatch.setattr(_mo(), "list_orders",
                        lambda: [_order(status=state["status"], label=state["label"])])
    assert _mo().fetch() == 1
    assert _manifest()["orders"][0]["status"] == "FILLED"
    state["status"], state["label"] = "PARTIAL", "部分成交"
    assert _mo().fetch() == 1                     # 状态变化 → 写新 manifest
    assert _manifest()["orders"][0]["status"] == "PARTIAL"


def test_fetch_sources_distinguish_decision(env, monkeypatch):
    from lkl.broker import fileio
    fileio.write("results", {"schema": 2, "for_date": _today(),
                             "trades": [{"order_id": "oid-lkl", "action": "BUY",
                                         "code": "600000", "ok": True}]})
    monkeypatch.setattr(_mo(), "list_orders",
                        lambda: [_order(oid="oid-lkl", filled=0, total=100,
                                        status="SUBMITTED", label="已报"),
                                 _order(oid="oid-hand")])
    assert _mo().fetch() == 2
    by_id = {r["order_id"]: r for r in _manifest()["orders"]}
    assert by_id["oid-lkl"]["source"] == "decision"
    assert by_id["oid-lkl"]["note"] == "LKL自动单"
    assert by_id["oid-hand"]["source"] == "manual"
    assert by_id["oid-hand"]["note"] == "手动终端操作"
