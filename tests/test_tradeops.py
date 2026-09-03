"""tradeops 故障注入测试：拒单不记账、成交归档、window 排除、并发锁、崩溃一致性、部分成交。"""
from __future__ import annotations

import pytest


def _today():
    from lkl.broker import trade_date
    return trade_date.trade_date()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """交换目录指向临时目录，且关闭远端 SSH（纯本地，不触网）。"""
    from lkl.broker import config
    monkeypatch.setitem(config._DEFAULTS, "TRADE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "remote_host", lambda: "")
    monkeypatch.setattr(config, "remote_dir", lambda: "")
    monkeypatch.setattr(config, "remote_dir", lambda: "")
    from lkl.broker import governor; governor.set_mode("armed", "test")
    return tmp_path


def _put_decision(tmp_path, actions):
    from lkl.broker import fileio
    fileio.write("decisions", {"schema": 1, "for_date": _today(), "actions": actions})


def _to():
    from lkl.broker import tradeops
    return tradeops


def _fileio():
    from lkl.broker import fileio
    return fileio


def _trade_date():
    from lkl.broker import trade_date
    return trade_date.trade_date()


class FakeExecutor:
    def __init__(self, outcome):
        self.outcome = outcome
        self.submits = []
        self._status = "NOT_FOUND"

    def submit(self, sig, volume=0):
        self.submits.append((sig, volume))
        return self.outcome(sig, volume) if callable(self.outcome) else self.outcome

    def status(self, order_id):
        from lkl.broker.orderstate import OrderStatus
        from lkl.broker.result import ExecResult
        return ExecResult(order_id, OrderStatus(self._status))


def _filled(**kw):
    from lkl.broker.orderstate import OrderStatus
    from lkl.broker.result import ExecResult
    return ExecResult("oid-1", OrderStatus.FILLED, filled=100, remaining=0,
                      avg_price=10.5, **kw)


def _rejected(reason="超量"):
    from lkl.broker.orderstate import OrderStatus
    from lkl.broker.result import ExecResult
    return ExecResult("", OrderStatus.REJECTED, reason=reason)


def _partial(filled=60, total=100):
    from lkl.broker.orderstate import OrderStatus
    from lkl.broker.result import ExecResult
    return ExecResult("oid-2", OrderStatus.PARTIAL, filled=filled,
                      remaining=max(total - filled, 0))


def test_rejected_never_ledgered_file_kept(env):
    from lkl.broker import ledger, tradeops
    _put_decision(env, [{"code": "601988", "action": "BUY"}])
    ex = FakeExecutor(_rejected())
    assert tradeops.process_once(executor=ex) == 0
    assert not ledger.load()
    assert _fileio().latest("decisions") is not None   # 保留可重试


def test_filled_confirm_archives_and_idempotent(env):
    from lkl.broker import ledger, tradeops
    _put_decision(env, [{"code": "601988", "action": "BUY"}])
    ex = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex) == 1
    assert any("601988|BUY" in r for r in ledger.load())
    assert _fileio().latest("decisions") is None            # 已归档
    ex2 = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex2) == 0
    assert ex2.submits == []                                 # 幂等不再下单


def test_window_none_excluded_no_order(env):
    from lkl.broker import exchange, ledger, tradeops
    _put_decision(env, [{"code": "601988", "action": "BUY", "window": "NONE"}])
    ex = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex) == 0
    assert not ledger.load()
    assert ex.submits == []                                  # 绝不下单
    assert _fileio().latest("decisions") is None             # 排除即终态→归档
    rows = exchange.load_results(_today())
    assert rows and rows[0]["status"] == "EXCLUDED"
    # 再跑一轮：已终态(EXCLUDED)不再重复记行
    tradeops.process_once(executor=ex)
    rows2 = exchange.load_results(_today())
    assert len([r for r in rows2 if r["status"] == "EXCLUDED"]) == 1


def test_retry_cap_stops_after_max(env):
    from lkl.broker import ledger, tradeops
    _put_decision(env, [{"code": "601988", "action": "BUY"}])
    ex = FakeExecutor(_rejected())
    for _ in range(tradeops.MAX_ATTEMPTS):
        tradeops.process_once(executor=ex)
    n_before = len(ex.submits)
    tradeops.process_once(executor=ex)                        # 已到上限 → 不再下单
    assert len(ex.submits) == n_before
    assert not ledger.load()
    assert _fileio().latest("decisions") is not None          # 未消费，待人工


def test_single_executor_lock(env):
    from lkl.broker.lock import ExecutorBusyError, single_executor
    with single_executor("a"):
        with pytest.raises(ExecutorBusyError):
            with single_executor("b"):
                pass


def test_crash_inflight_not_resubmitted(env):
    """崩在下单后：有 order_id 在途 → 本轮绝不重下，且不归档。"""
    from lkl.broker import intent, ledger, tradeops
    _put_decision(env, [{"code": "601988", "action": "BUY"}])
    intent.record(f"{_today()}|601988|BUY", order_id="oid-9", status="SUBMITTED")
    ex = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex) == 0
    assert ex.submits == []                                       # 不重下
    assert _fileio().latest("decisions") is not None             # 保留待对账
    assert intent.has(f"{_today()}|601988|BUY")


def test_partial_keeps_inflight_no_duplicate(env):
    from lkl.broker import tradeops
    _put_decision(env, [{"code": "601988", "action": "BUY"}])
    ex = FakeExecutor(_partial())
    assert tradeops.process_once(executor=ex) == 0
    assert ex.submits                        # 首次下
    n_first = len(ex.submits)
    tradeops.process_once(executor=ex)
    assert len(ex.submits) == n_first         # 部分成交在途，不再追加下单