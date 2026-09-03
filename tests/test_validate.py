"""P1-09 决策契约校验测试。"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def dir(tmp_path, monkeypatch):
    from lkl.broker import config
    monkeypatch.setitem(config._DEFAULTS, "TRADE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "remote_host", lambda: "")
    return tmp_path


def _write(dir, actions):
    from lkl.broker import fileio
    fileio.write("decisions", {"schema": 1, "for_date": "2026-09-03",
                               "actions": actions})


def _load(dir):
    from lkl.broker import exchange
    return exchange.load_decisions("2026-09-03")


def test_valid_decision_parses(dir):
    from lkl.broker import exchange
    _write(dir, [{"action": "BUY", "code": "601988", "volume": 100},
                 {"action": "SELL", "code": "600000", "volume": 0}])
    sigs = _load(dir)
    assert [s.action for s in sigs] == ["BUY", "SELL"]
    assert sigs[0].code == "601988" and sigs[0].volume == 100


def test_bad_action_rejected(dir):
    from lkl.broker import exchange
    _write(dir, [{"action": "HOLD", "code": "601988", "volume": 100}])
    with pytest.raises(exchange.DecisionValidationError):
        _load(dir)


def test_bad_code_rejected(dir):
    from lkl.broker import exchange
    _write(dir, [{"action": "BUY", "code": "60", "volume": 100}])
    with pytest.raises(exchange.DecisionValidationError):
        _load(dir)


def test_negative_volume_rejected(dir):
    from lkl.broker import exchange
    _write(dir, [{"action": "BUY", "code": "601988", "volume": -5}])
    with pytest.raises(exchange.DecisionValidationError):
        _load(dir)


def test_date_mismatch_empty(dir):
    from lkl.broker import exchange
    _write(dir, [{"action": "BUY", "code": "601988", "volume": 100}])
    assert exchange.load_decisions("2026-09-04") == []