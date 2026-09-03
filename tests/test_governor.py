"""安全治理测试：演练/实盘门禁、急停、风控护栏、tradeops 门禁接线。"""
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


def _put(env, actions):
    from lkl.broker import fileio
    fileio.write("decisions", {"schema": 1, "for_date": _today(), "actions": actions})


def test_default_is_dry_no_trade(env):
    from lkl.broker import tradeops
    _put(env, [{"code": "601988", "action": "BUY"}])
    ex = _Filled()
    assert tradeops.process_once(executor=ex) == 0   # dry 默认不自动下单
    assert ex.submits == []


def test_tradeops_gate_follows_governance(env):
    from lkl.broker import governor, tradeops
    _put(env, [{"code": "601988", "action": "BUY"}])
    governor.set_mode("armed", "测试实盘")
    ex = _Filled()
    assert tradeops.process_once(executor=ex) == 1   # armed 后允许
    assert len(ex.submits) == 1
    # 若急切停止：新决策不下单
    _put(env, [{"code": "600000", "action": "BUY"}])
    governor.halt("停止")
    ex2 = _Filled()
    assert tradeops.process_once(executor=ex2) == 0
    assert ex2.submits == []


def test_governance_state_machine(env):
    from lkl.broker import governor
    assert governor.allow_trade() == (False, "演练(dry)模式，未 arm，不自动下单")
    governor.set_mode("armed")
    assert governor.allow_trade()[0] is True
    governor.halt("风控")
    assert governor.allow_trade()[0] is False
    governor.resume()
    assert governor.allow_trade()[0] is True
    governor.set_mode("dry")
    assert governor.allow_trade()[0] is False


def test_risk_block(env, monkeypatch):
    from lkl.broker import governor
    monkeypatch.setenv("GM_RISK_MAX_QTY", "5")
    assert governor.risk_block(6, 0, 0)[0] is True     # 超单笔
    monkeypatch.setenv("GM_RISK_MAX_ORDERS", "2")
    assert governor.risk_block(1, 2, 0)[0] is True     # 达下单次数
    monkeypatch.setenv("GM_RISK_MAX_CODES", "1")
    assert governor.risk_block(1, 0, 1)[0] is True     # 达操作只数
    monkeypatch.setenv("GM_RISK_MAX_QTY", "")
    monkeypatch.setenv("GM_RISK_MAX_ORDERS", "")
    monkeypatch.setenv("GM_RISK_MAX_CODES", "")
    assert governor.risk_block(99999, 0, 0)[0] is False  # 全关=放行


def test_cli_governance_roundtrip(env):
    from lkl.broker import governor
    assert "演练" in governor.run_cli("status")
    governor.run_cli("arm")
    assert "实盘" in governor.run_cli("status")
    governor.run_cli("resume")
    governor.run_cli("dry")


class _Filled:
    def __init__(self):
        self.submits = []

    def submit(self, sig, volume=0):
        self.submits.append((sig, volume))
        from lkl.broker.orderstate import OrderStatus
        from lkl.broker.result import ExecResult
        return ExecResult("oid-1", OrderStatus.FILLED, filled=100, remaining=0,
                          avg_price=10.5)

    def status(self, order_id):
        from lkl.broker.orderstate import OrderStatus
        from lkl.broker.result import ExecResult
        return ExecResult(order_id, OrderStatus.NOT_FOUND)