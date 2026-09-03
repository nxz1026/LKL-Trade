"""收尾功能测试：resolve 处置钩子、next_open 跨周末、KEEP_REMOTE、doctor 冒烟。"""
from __future__ import annotations

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from lkl.broker import config
    monkeypatch.setitem(config._DEFAULTS, "TRADE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "remote_host", lambda: "")
    monkeypatch.setattr(config, "remote_dir", lambda: "")
    from lkl.broker import governor
    governor.set_mode("armed", "test")
    return tmp_path


def _today():
    from lkl.broker import trade_date
    return trade_date.trade_date()


def _put(env, actions):
    from lkl.broker import fileio
    fileio.write("decisions", {"schema": 1, "for_date": _today(), "actions": actions})


class _Reject:
    def __init__(self):
        self.submits = []

    def submit(self, sig, volume=0):
        self.submits.append(sig)
        from lkl.broker.orderstate import OrderStatus
        from lkl.broker.result import ExecResult
        return ExecResult("", OrderStatus.REJECTED, reason="拒单")

    def status(self, order_id):
        from lkl.broker.orderstate import OrderStatus
        from lkl.broker.result import ExecResult
        return ExecResult(order_id, OrderStatus.NOT_FOUND)


def test_resolve_ignore_stops_auto(env):
    from lkl.broker import ledger, resolve, tradeops
    _put(env, [{"code": "601988", "action": "BUY"}])
    d = _today()
    resolve.resolve(f"{d}|601988|BUY", "ignore")
    ex = _Reject()
    tradeops.process_once(executor=ex)
    assert ex.submits == []                    # ignore：不下单
    assert not ledger.load()


def test_resolve_complete_marks_done(env):
    from lkl.broker import ledger, resolve, tradeops
    _put(env, [{"code": "601988", "action": "BUY"}])
    d = _today()
    resolve.resolve(f"{d}|601988|BUY", "complete")
    ex = _Reject()
    tradeops.process_once(executor=ex)
    assert ex.submits == []
    assert any("601988|BUY" in r for r in ledger.load())   # 人工完成入账本防重
    from lkl.broker import fileio
    # 该文件仅此一条动作且已人工完成 → 整份终态可归档（可追溯见 archive/）
    assert fileio.latest("decisions") is None


def test_resolve_retry_clears(env):
    from lkl.broker import resolve
    d = _today()
    resolve.resolve(f"{d}|601988|BUY", "retry")
    resolve.resolve(f"{d}|601988|BUY", "ignore")
    assert resolve._load()[f"{d}|601988|BUY"]["action"] == "ignore"


def test_next_open_skips_weekend(env):
    from datetime import datetime, timedelta
    from lkl.broker import session
    # 2026-09-04 周五 15:30 → 下一为 下周一(09-07) 09:30
    fri = datetime(2026, 9, 4, 15, 30, tzinfo=session.TZ)
    nxt = session.next_open(fri)
    assert nxt is not None
    assert nxt.date().weekday() == 0 and nxt.strftime("%H:%M") == "09:30"
    assert nxt.date().isoformat() == "2026-09-07"


def test_next_open_morning_same_day(env):
    from datetime import datetime
    from lkl.broker import session
    t = datetime(2026, 9, 3, 10, 0, tzinfo=session.TZ)   # 周四上午盘中
    nxt = session.next_open(t)
    assert nxt.strftime("%H:%M") == "13:00"              # 下午开盘


def test_keep_remote_flag(env, monkeypatch):
    """GM_KEEP_REMOTE=1 → tradeops 不自动删远端（对账前保留原始决策）。"""
    from lkl.broker import tradeops
    monkeypatch.setenv("GM_KEEP_REMOTE", "1")
    assert tradeops._keep_remote() is True
    monkeypatch.delenv("GM_KEEP_REMOTE")
    assert tradeops._keep_remote() is False


def test_doctor_runs(env):
    from lkl.broker import doctor
    r = doctor.run()
    assert r in (0, 1)   # 冒烟：不抛，逐项有结果