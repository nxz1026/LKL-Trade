"""产品功能批次契约测试：webhook 推送、风控上限写读、doctor 表、委托合并视图。"""
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from lkl.broker import config
    monkeypatch.setitem(config._DEFAULTS, "TRADE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "remote_host", lambda: "")
    monkeypatch.setattr(config, "remote_dir", lambda: "")
    # 风控键一律走隔离环境文件，绝不触碰真实 .secrets/gm.env
    monkeypatch.delenv("GM_RISK_MAX_QTY", raising=False)
    monkeypatch.delenv("GM_RISK_MAX_ORDERS", raising=False)
    monkeypatch.delenv("GM_RISK_MAX_CODES", raising=False)
    monkeypatch.delenv("GM_ALERT_WEBHOOK", raising=False)
    f = tmp_path / "gm.env"
    monkeypatch.setenv("GM_ENV_FILE", str(f))
    return tmp_path


# ---------- S1 告警 webhook 推送 ----------

def test_alerts_webhook_fires_on_crit_warn(env, monkeypatch):
    from lkl.broker import alerts
    calls = []
    monkeypatch.setenv("GM_ALERT_WEBHOOK", "http://hook.example/x, http://hook.example/y")
    import urllib.request
    real = urllib.request.urlopen

    def fake(req, timeout=0):
        calls.append(json.loads(req.data))
        return real(req, timeout=timeout)  # 会真实请求？改为不请求
    # 不真实外呼：替换为记录即返回
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=5: calls.append(json.loads(req.data)) or _Resp())
    alerts.emit("CRIT", "急停测试")
    alerts.emit("WARN", "超限测试")
    alerts.emit("INFO", "静默测试")
    assert len(calls) == 4                    # 2 条告警 × 2 个 URL
    assert calls[0]["level"] == "CRIT" and calls[0]["msg"] == "急停测试"
    assert calls[2]["level"] == "WARN"
    assert not any(c["level"] == "INFO" for c in calls)


def test_alerts_webhook_no_config_noop(env, monkeypatch):
    from lkl.broker import alerts
    import urllib.request
    fired = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=5: fired.append(1) or None)
    alerts.emit("CRIT", "无配置不推送")
    assert fired == []


# ---------- S2 风控上限写读 ----------

def test_risk_limits_set_persist_read_back(env, monkeypatch):
    from lkl.broker import config
    cur = config.set_risk_limits({"max_qty": 10000, "max_orders": 8, "max_codes": 4})
    assert cur["max_qty"] == 10000
    # 读回（走 _secret：env 无 → gm.env 文件）
    assert config.risk_limits()["max_qty"] == 10000
    assert config.risk_limits()["max_orders"] == 8
    text = (env / "gm.env").read_text(encoding="utf-8")
    assert "GM_RISK_MAX_QTY=10000" in text
    assert "GM_RISK_MAX_CODES=4" in text


def test_risk_limits_update_overwrites(env):
    from lkl.broker import config
    config.set_risk_limits({"max_qty": 500})
    config.set_risk_limits({"max_qty": 700})
    assert config.risk_limits()["max_qty"] == 700
    text = (env / "gm.env").read_text(encoding="utf-8")
    assert text.count("GM_RISK_MAX_QTY") == 1


def test_risk_limits_rejects_bad_values(env):
    from lkl.broker import config
    import pytest as _pytest
    with _pytest.raises(ValueError):
        config.set_risk_limits({"max_qty": -1})
    with _pytest.raises(ValueError):
        config.set_risk_limits({"max_qty": "abc"})


# ---------- S3 doctor 表 ----------

def test_doctor_table_shape(env, monkeypatch):
    from lkl.broker import doctor, gate
    monkeypatch.setattr(gate, "up", lambda: False)
    monkeypatch.setattr(gate, "account_ready", lambda: False)
    t = doctor.table()
    assert set(t) == {"ok", "checks"}
    names = {c["name"] for c in t["checks"]}
    assert {"python", "gmtrade", "凭据", "终端(7001)", "交换目录"} <= names
    assert all(set(c) == {"name", "ok", "why"} for c in t["checks"])
    assert t["ok"] is False                      # 终端离线 → 表与 ok 一致


# ---------- M1 委托合并视图 ----------

def _order(fid, symbol="601988.SH", side="买"):
    return {"id": fid[:8], "full_id": fid, "symbol": symbol, "side": side,
            "volume": 100, "price": 5.0, "filled": 100, "remaining": 0,
            "status": 3, "status_label": "已成交"}


def test_merge_orders_marks_source_and_dedups(env):
    from dashboard.trade_state import _merge_orders
    live = {"ok": True, "rows": [_order("A1"), _order("A2"), _order("A3")]}
    manual = {"ok": True, "rows": [
        {**_order("A1"), "order_id": "A1", "source": "manual"},
        {**_order("A2"), "order_id": "A2", "source": "decision"},
    ]}
    m = _merge_orders(live, manual, "2026-09-05")
    assert m["source"] == "merged"
    by = {r["full_id"]: r for r in m["rows"]}
    assert set(by) == {"A1", "A2", "A3"}
    assert by["A1"]["source"] == "manual"
    assert by["A2"]["source"] == "decision"
    # A3 不在 manifest、不在 results → 归为手动（终端直接操作）
    assert by["A3"]["source"] == "manual"


def test_merge_orders_manifest_fallback_when_terminal_down(env):
    from dashboard.trade_state import _merge_orders
    manual = {"ok": True, "rows": [{**_order("M1"), "order_id": "M1", "source": "manual"}]}
    m = _merge_orders({"ok": False, "note": "连接被拒", "rows": []}, manual, "2026-09-05")
    assert m["source"] == "manifest"
    assert m["rows"][0]["full_id"] == "M1"
