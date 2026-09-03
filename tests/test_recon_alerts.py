"""对账 + 分级告警测试。"""
from __future__ import annotations

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from lkl.broker import config
    monkeypatch.setitem(config._DEFAULTS, "TRADE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "remote_host", lambda: "")
    monkeypatch.setattr(config, "remote_dir", lambda: "")
    return tmp_path


def _today():
    from lkl.broker import trade_date
    return trade_date.trade_date()


def _seed(env, *, decisions=(), results=(), holdings=(), done_refs=()):
    """四源文件播种后返回 reconcile 结果。"""
    from lkl.broker import fileio, ledger, recon
    d = _today()
    if decisions:
        fileio.write("decisions", {"schema": 1, "for_date": d, "actions": decisions})
    if results:
        fileio.write("results", {"schema": 1, "for_date": d, "trades": results})
    if holdings is not None:
        fileio.write("holdings", {"schema": 1, "for_date": d, "holdings": holdings})
    if done_refs:
        ledger.mark(list(done_refs))
    return recon.reconcile()


def test_alerts_grading(env):
    from lkl.broker import alerts
    alerts.emit("CRIT", "急停")
    alerts.emit("WARN", "超限")
    alerts.emit("INFO", "已扫")
    s = alerts.summary()
    assert s["crit"] == 1 and s["warn"] == 1 and s["total"] == 3
    recs = alerts.list_alerts(100)
    assert recs[0]["level"] == "CRIT"
    assert recs[-1]["level"] == "INFO"


def test_recon_buy_missing_holding(env):
    d = _today()
    ref = f"{d}|601988|BUY"
    r = _seed(env,
              decisions=[{"action": "BUY", "code": "601988", "volume": 100}],
              results=[{"ref": ref, "action": "BUY", "code": "601988",
                        "confirmed": True, "status": "FILLED", "order_id": "o1",
                        "reason": ""}],
              holdings=[],
              done_refs=[ref])
    assert r["summary"]["warn"] == 1
    assert r["rows"][0]["status"] == "成交但持仓缺失"


def test_recon_consistent(env):
    d = _today()
    buy = f"{d}|601988|BUY"
    sell = f"{d}|600000|SELL"
    r = _seed(env,
              decisions=[{"action": "BUY", "code": "601988", "volume": 100},
                         {"action": "SELL", "code": "600000", "volume": 100}],
              holdings=[{"code": "601988", "volume": 100}],
              done_refs=[buy, sell])
    assert r["summary"]["ok"] == 2 and r["summary"]["warn"] == 0


def test_recon_sell_still_holding(env):
    d = _today()
    sell = f"{d}|600000|SELL"
    r = _seed(env,
              decisions=[{"action": "SELL", "code": "600000", "volume": 100}],
              holdings=[{"code": "600000", "volume": 10}],
              done_refs=[sell])
    assert r["summary"]["warn"] == 1
    assert any("仍持仓" in row["status"] for row in r["rows"])