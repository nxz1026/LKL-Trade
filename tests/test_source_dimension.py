"""决策来源维度（GM_SOURCE）与 HTTP 模式加固的回归测试。

背景（2026-10-07）：接第二个上游（CPT）时发现三处会**静默丢单或误执行**的缺陷，
本文件把它们逐条钉住：

1. `ref` = `日期|代码|动作` 没有来源维度 ⇒ 两个上游对同一只票的同向指令
   被 `ledger` / `resolve` 当成**同一笔**，先成交的那笔让另一笔被防重挡住。
2. 幂等键只用 `batch_id`，两个上游空间混在一起。
3. HTTP 模式**绕过 `exchange._validate`**（SFTP 模式才有契约校验）。
4. HTTP 模式**从不校验上游回传的 `for_date`**，串日期的决策会被当今天执行。

外加一条向后兼容约束：**`source` 为空时 `ref` 必须与旧版逐字一致**，
否则历史 `executed.json` / `pending.json` 里的防重记录全部失效、一天内重发同一笔。
"""
from __future__ import annotations

from datetime import date

import pytest


def _env(tmp_path, monkeypatch, source=""):
    from lkl.broker import config, governor
    monkeypatch.setitem(config._DEFAULTS, "TRADE_DIR", str(tmp_path))
    monkeypatch.setenv("GM_SOURCE", source)
    governor.set_mode("armed", "test")
    return tmp_path


def _filled():
    from lkl.broker.orderstate import OrderStatus
    from lkl.broker.result import ExecResult
    return ExecResult("oid-1", OrderStatus.FILLED, filled=100, remaining=0, avg_price=10.5)


class _FakeExecutor:
    def __init__(self, outcome):
        self.outcome = outcome
        self.submits = []

    def submit(self, sig, volume=0):
        self.submits.append((sig, volume))
        return self.outcome

    def status(self, order_id):
        from lkl.broker.orderstate import OrderStatus
        from lkl.broker.result import ExecResult
        return ExecResult(order_id, OrderStatus.NOT_FOUND)


def _sig(code="601988", action="BUY", source=""):
    from lkl.models.types import Signal
    return Signal(confirm_date=date(2026, 10, 8), code=code, action=action, source=source)


# ── 1. ref 的来源维度 ────────────────────────────────────────────────

def test_ref_without_source_keeps_legacy_format():
    """向后兼容硬约束：source 空 ⇒ ref 与旧版逐字相同，否则历史防重账本失效。"""
    from lkl.broker.tradeops import _ref
    assert _ref(_sig()) == "2026-10-08|601988|BUY"


def test_ref_with_source_is_namespaced():
    from lkl.broker.tradeops import _ref
    assert _ref(_sig(source="emotion")) == "emotion|2026-10-08|601988|BUY"


def test_two_sources_same_code_are_different_refs():
    """★核心：两个上游对同一只票的同向指令**必须是两笔**，否则先成交的挡掉后一笔。"""
    from lkl.broker.tradeops import _ref
    a = _ref(_sig(source="emotion"))
    b = _ref(_sig(source="cpt"))
    assert a != b


# ── 2. batch 幂等按来源分桶 ─────────────────────────────────────────

def test_batch_ids_are_namespaced_by_source(tmp_path, monkeypatch):
    from lkl.broker import fileio, remote_http
    monkeypatch.setattr(fileio, "directory", lambda: tmp_path)
    assert remote_http._key("b1", "emotion") == "emotion:b1"
    assert remote_http._key("b1", "cpt") == "cpt:b1"
    assert remote_http._key("b1", "") == "b1"          # 向后兼容


def test_same_batch_id_two_sources_not_confused(tmp_path, monkeypatch):
    """上游复用 batch_id（重放/重试）时，第二个来源不该被误判为已处理。"""
    from lkl.broker import fileio, remote_http
    monkeypatch.setattr(fileio, "directory", lambda: tmp_path)
    remote_http.mark_processed("same-id", "emotion")
    assert remote_http.is_processed("same-id", "emotion") is True
    assert remote_http.is_processed("same-id", "cpt") is False


# ── 3+4. HTTP 模式：日期一致性与契约校验 ────────────────────────────

def _http_payload(actions, for_date="2026-10-08", batch_id="b-x"):
    return {"batch_id": batch_id, "for_date": for_date, "actions": actions}


def _run_http(monkeypatch, payload, executor, for_date="2026-10-08"):
    from lkl.broker import remote_http, tradeops
    monkeypatch.setattr(remote_http, "http_pull_decisions", lambda d: payload)
    monkeypatch.setattr(remote_http, "http_push_results", lambda d: {"status": "ok"})
    monkeypatch.setattr(remote_http, "mark_processed", lambda *a, **k: None)
    return tradeops._process_once_http(for_date, executor)


def test_http_rejects_for_date_mismatch(tmp_path, monkeypatch):
    """★上游串日期（缓存键写错/时区错位）时，昨天决策会被当今天执行 ⇒ 整批拒绝。"""
    _env(tmp_path, monkeypatch)
    ex = _FakeExecutor(_filled())
    payload = _http_payload([{"code": "601988", "action": "BUY"}], for_date="2026-10-07")
    assert _run_http(monkeypatch, payload, ex) == 0
    assert ex.submits == [], "日期不一致仍下单了"


def test_http_rejects_contract_violation(tmp_path, monkeypatch):
    """★HTTP 模式必须复用 exchange._validate：6 位码/action 枚举/exec 配对。"""
    _env(tmp_path, monkeypatch)
    ex = _FakeExecutor(_filled())
    payload = _http_payload([{"code": "60198A", "action": "BUY"}])   # 非法码
    assert _run_http(monkeypatch, payload, ex) == 0
    assert ex.submits == [], "契约非法仍下单了"


def test_http_rejects_unknown_action(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    ex = _FakeExecutor(_filled())
    payload = _http_payload([{"code": "601988", "action": "HOLD"}])
    assert _run_http(monkeypatch, payload, ex) == 0
    assert ex.submits == []


def test_http_normalizes_action_case(tmp_path, monkeypatch):
    """小写 action 被**归一化**而非拒绝——与 SFTP 模式口径一致。

    旧 HTTP 实现直接 `a["action"]` 取值、不做 upper()，小写会在下游
    `orders.py` 的 action→exec 映射上 KeyError（而不是被干净地归一）。
    """
    _env(tmp_path, monkeypatch)
    ex = _FakeExecutor(_filled())
    payload = _http_payload([{"code": "601988", "action": "buy"}])
    assert _run_http(monkeypatch, payload, ex) == 1
    assert ex.submits[0][0].action == "BUY"


def test_http_rejects_exec_action_mismatch(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    ex = _FakeExecutor(_filled())
    payload = _http_payload([{"code": "601988", "action": "SELL", "exec": "OPEN_POS"}])
    assert _run_http(monkeypatch, payload, ex) == 0
    assert ex.submits == []


def test_http_bad_batch_touches_no_state(tmp_path, monkeypatch):
    """校验失败必须发生在拿锁**之前**：坏批次不该动 ledger/pending/results。"""
    _env(tmp_path, monkeypatch)
    from lkl.broker import fileio, ledger
    ex = _FakeExecutor(_filled())
    payload = _http_payload([{"code": "bad", "action": "BUY"}])
    assert _run_http(monkeypatch, payload, ex) == 0
    assert not ledger.load()
    assert fileio.latest("results") is None


def test_http_accepts_valid_batch(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, source="cpt")
    ex = _FakeExecutor(_filled())
    payload = _http_payload([{"code": "601988", "action": "BUY",
                              "exec": "OPEN_POS", "volume": 100}])
    assert _run_http(monkeypatch, payload, ex) == 1
    assert len(ex.submits) == 1
    assert ex.submits[0][0].source == "cpt"


@pytest.mark.parametrize("bad_volume", [-1, "100", True])
def test_http_rejects_bad_volume(tmp_path, monkeypatch, bad_volume):
    _env(tmp_path, monkeypatch)
    ex = _FakeExecutor(_filled())
    payload = _http_payload([{"code": "601988", "action": "BUY", "volume": bad_volume}])
    assert _run_http(monkeypatch, payload, ex) == 0
    assert ex.submits == []


def test_missing_volume_defaults_to_100_shares(tmp_path, monkeypatch):
    """缺 volume ⇒ 仍按 100 股（旧行为：`.get("volume", 100)`；新实现靠 `volume or 100`）。"""
    _env(tmp_path, monkeypatch)
    ex = _FakeExecutor(_filled())
    payload = _http_payload([{"code": "601988", "action": "BUY"}])
    assert _run_http(monkeypatch, payload, ex) == 1
    assert ex.submits[0][1] == 100