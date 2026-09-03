"""跨进程/崩溃一致性测试：orderstate / ledger / intent / lock。"""
from __future__ import annotations

import pytest


def test_state_machine_contract():
    from lkl.broker.orderstate import OrderStatus as S
    assert S.FILLED.terminal and S.FILLED.confirmed and not S.FILLED.retryable
    assert S.EXCLUDED.terminal and not S.EXCLUDED.confirmed
    assert S.REJECTED.retryable and not S.REJECTED.terminal
    assert S.PARTIAL.retryable and not S.PARTIAL.terminal
    assert S.CANCELLED.terminal and not S.CANCELLED.confirmed


def test_execresult_fields():
    from lkl.broker.orderstate import OrderStatus as S
    from lkl.broker.result import ExecResult
    r = ExecResult("o1", S.FILLED, filled=100, remaining=0, avg_price=10.5)
    assert r.ok and r.terminal and not r.retryable
    assert r.to_row()["confirmed"] is True

    rej = ExecResult("o2", S.REJECTED, reason="超量")
    assert not rej.ok and rej.retryable


def test_ledger_atomic_and_corrupt_blocks(tmp_path):
    from lkl.broker import ledger
    from lkl.broker.config import _DEFAULTS
    _DEFAULTS["TRADE_DIR"] = str(tmp_path)
    ledger.mark(["a", "b"])
    assert ledger.load() == {"a", "b"}
    ledger.mark(["b", "c"])
    assert ledger.load() == {"a", "b", "c"}
    ledger._path().write_text("{bad", encoding="utf-8")
    with pytest.raises(ledger.LedgerCorruptError):
        ledger.load()


def test_intent_roundtrip_and_corrupt(tmp_path):
    from lkl.broker import intent
    from lkl.broker.config import _DEFAULTS
    _DEFAULTS["TRADE_DIR"] = str(tmp_path)
    intent.record("d|601988|BUY", qty=100)
    intent.record("d|601988|BUY", order_id="oid-9", status="SUBMITTED")
    assert intent.has("d|601988|BUY")
    rec = intent.load()["d|601988|BUY"]
    assert rec["order_id"] == "oid-9"
    intent.finish("d|601988|BUY")
    assert not intent.has("d|601988|BUY")
    intent._path().write_text("x", encoding="utf-8")
    with pytest.raises(intent.PendingCorruptError):
        intent.load()