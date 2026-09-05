"""v2 交换契约测试：文件名秒级取上海时区、results 行齐、远端目录防越界。"""
from __future__ import annotations

import re
from datetime import datetime

import pytest


def test_filename_stamp_is_second_level_shanghai():
    """文件名 = {kind}_YYYYMMDD_HHMMSS.json（秒级，+8 非 UTC）。"""
    from lkl.broker import fileio, session
    name = fileio.write("results", {"x": 1}).name
    assert re.fullmatch(r"results_\d{8}_\d{6}\.json", name)
    stamp = re.match(r"[a-z]+_(\d{8}_\d{6})\.json", name).group(1)
    expect = datetime.now(session.TZ).strftime("%Y%m%d_%H%M%S")
    assert abs((datetime.strptime(stamp, "%Y%m%d_%H%M%S")
                - datetime.strptime(expect, "%Y%m%d_%H%M%S")).seconds) < 2


def test_results_row_v2_fields(tmp_path, monkeypatch):
    """results 行含 v2 契约字段 action/code/ok/price/shares/order_id/reason。"""
    from lkl.broker import config, exchange, fileio, trade_date, tradeops
    monkeypatch.setitem(config._DEFAULTS, "TRADE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "remote_host", lambda: "")
    monkeypatch.setattr(config, "remote_dir", lambda: "")
    monkeypatch.setattr(config, "remote_dir", lambda: "")
    from lkl.broker import governor; governor.set_mode("armed", "test")
    d = trade_date.trade_date()
    fileio.write("decisions", {"schema": 1, "for_date": d,
                               "actions": [{"code": "601988", "action": "BUY"}]})
    assert tradeops.process_once(executor=_FilledExecutor()) == 1
    rows = exchange.load_results(d)
    row = rows and rows[0]
    assert row["code"] == "601988" and row["action"] == "BUY"
    for k in ("ok", "price", "shares", "order_id", "status", "reason", "note"):
        assert k in row, k
    assert row["ok"] is True and row["price"] == 10.5 and row["shares"] == 100
    assert row["order_id"] == "oid-1"


def test_exchange_prices_rounded_to_2(tmp_path, monkeypatch):
    """交换文件价格收敛 2 位小数（A股最小变动 0.01），DB 对账不遇长尾。"""
    import json
    from lkl.broker import config, fileio
    monkeypatch.setitem(config._DEFAULTS, "TRADE_DIR", str(tmp_path))
    p = fileio.write("holdings", {
        "schema": 1, "for_date": "2026-09-04", "account": "a1",
        "holdings": [{"code": "601988", "symbol": "SHSE.601988",
                      "volume": 100, "available": 100, "cost": 6.7345,
                      "price": 6.7088, "vwap": 6.7300,
                      "last_price": 6.7088, "fpnl": -2.57}]})
    body = json.loads(p.read_text(encoding="utf-8"))
    row = body["holdings"][0]
    assert row["cost"] == 6.73
    assert row["price"] == 6.71 and row["last_price"] == 6.71
    assert row["vwap"] == 6.73
    assert body["schema"] == 1 and body["account"] == "a1"


def test_remote_cd_rejects_escape(tmp_path, monkeypatch):
    """v2 受限目录：.. 与绝对路径一律拒绝，防越界到他人目录/根。"""
    from lkl.broker import config, remote
    monkeypatch.setattr(config, "remote_host", lambda: "h")
    for bad in ("..", "user1/../user2", "/abs/path", "../../etc"):
        monkeypatch.setattr(config, "remote_dir", lambda: bad)
        with pytest.raises(remote.RemoteError):
            remote._cd()
    monkeypatch.setattr(config, "remote_dir", lambda: "user1")
    assert remote._cd() == "cd user1\n"
    monkeypatch.setattr(config, "remote_dir", lambda: "a/b")
    assert remote._cd() == "cd a/b\n"


class _FilledExecutor:
    def submit(self, sig, volume=0):
        from lkl.broker.orderstate import OrderStatus
        from lkl.broker.result import ExecResult
        return ExecResult("oid-1", OrderStatus.FILLED, filled=100,
                          remaining=0, avg_price=10.5)

    def status(self, order_id):
        from lkl.broker.orderstate import OrderStatus
        from lkl.broker.result import ExecResult
        return ExecResult(order_id, OrderStatus.NOT_FOUND)

def test_traded_at_uses_shanghai_now():
    """traded_at 一律 Asia/Shanghai（session.now），不得用机器本地时区。"""
    from lkl.broker import session, tradeops
    from lkl.broker.orderstate import OrderStatus
    from lkl.broker.result import ExecResult
    from lkl.models.types import Signal
    from datetime import date
    sig = Signal(confirm_date=date(2026, 9, 5), code="601988", action="BUY")
    res = ExecResult("oid", OrderStatus.FILLED, filled=100, remaining=0, avg_price=10.5)
    before = session.now().isoformat(timespec="seconds")
    row = tradeops._row(sig, res, "note")
    after = session.now().isoformat(timespec="seconds")
    assert before <= row["traded_at"] <= after
    assert row["traded_at"].endswith("+08:00")   # 上海时区，非本机 UTC/本地
