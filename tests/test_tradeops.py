"""tradeops 故障注入测试：拒单不记账、成交归档、window 展示标签（不拦单）、并发锁、崩溃一致性、部分成交。"""
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


def test_close_all_season_sell_executes(env):
    """验收①：SELL+window=NONE+exec=CLOSE_ALL → 正常下单、清仓、绝无 EXCLUDED。

    2026-09-04 事故回归：window=NONE 曾被误判「无明确执行语义，拒绝下单」→ EXCLUDED
    拒掉 601988 清仓。契约 v2 起 window 只是展示标签，执行只看 exec。
    本测试即 DB-CONFIRM.md #1 拍板的验收用例。
    """
    from lkl.broker import exchange, ledger, tradeops
    _put_decision(env, [{"code": "601988", "action": "SELL", "window": "NONE",
                         "exec": "CLOSE_ALL", "volume": 100}])
    ex = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex) == 1
    assert len(ex.submits) == 1
    sig, vol = ex.submits[0]
    assert sig.exec_ == "CLOSE_ALL"
    assert vol == 0                                          # 清仓量交 orders 按实时可用
    assert any("601988|SELL" in r for r in ledger.load())    # 成交入账
    assert _fileio().latest("decisions") is None             # 消费即归档
    rows = exchange.load_results(_today())
    assert rows and rows[0]["action"] == "SELL"
    assert rows[0]["ok"] is True
    assert not any(r["status"] == "EXCLUDED" for r in rows)  # 绝无 EXCLUDED
    # 再跑一轮：已终态(成交)不再重复记行
    tradeops.process_once(executor=ex)
    assert len(exchange.load_results(_today())) == 1


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


def test_duplicate_decision_consumed_not_reprocessed(env):
    """回归：已归档(已消费)决策的同名副本再次出现 → 跳过，绝不重发 results。

    线上双份 bug 链条：remove_archived 守卫经 remote.pull() 落盘，把远端 decisions
    残留进本地交换目录，次轮 process_once 把它当新决策 → 重处理 → 重发 results。
    """
    import shutil
    from lkl.broker import exchange, tradeops
    _put_decision(env, [{"code": "601988", "action": "BUY"}])   # schema:1 兜底 OPEN_POS
    ex = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex) == 1              # 成交 → 防重入账
    assert _fileio().latest("decisions") is None          # 首轮已归档
    n_results = len(list(env.glob("results_*.json")))
    assert n_results == 1
    # 模拟旧守卫 pull 落盘残留：把已归档决策以同名复制回交换目录
    archived = next(env.glob("archive/**/decisions_*.json"))
    shutil.copy(archived, env / archived.name)
    assert _fileio().latest("decisions") is not None      # 残留重现
    ex2 = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex2) == 0
    assert ex2.submits == []                              # 不重下
    assert len(list(env.glob("results_*.json"))) == n_results  # 不新增 results
    assert _fileio().latest("decisions") is None          # 残留副本被归档回收，不留垃圾


def _put_decision_at(tmp_path, actions, stamp):
    """按显式时间戳写决策文件（stamp=YYYYMMDD_HHMMSS），便于构造多份升序。"""
    import json as _json
    from lkl.broker import fileio
    p = fileio.directory() / f"decisions_{stamp}.json"
    p.write_text(_json.dumps({"schema": 1, "for_date": _today(), "actions": actions},
                             ensure_ascii=False), encoding="utf-8")
    return p


def test_multiple_decisions_execute_in_order(env):
    """核心：同一 code 多份跨 action 决策按文件时间升序执行（先 BUY 后 SELL）。"""
    from lkl.broker import exchange, tradeops
    _put_decision_at(env, [{"code": "601988", "action": "BUY"}], "20260904_093000")
    _put_decision_at(env, [{"code": "601988", "action": "SELL", "exec": "CLOSE_ALL"}], "20260904_093500")
    ex = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex) == 2          # 两笔都成交
    acts = [sig.action for sig, _ in ex.submits]
    assert acts == ["BUY", "SELL"], f"必须按投递顺序执行，实际 {acts}"
    assert _fileio().latest("decisions") is None            # 两份都已归档
    archived = sorted(env.glob("archive/**/decisions_*.json"))
    assert len(archived) == 2
    rows = exchange.load_results(_today())
    assert [r["action"] for r in rows] == ["BUY", "SELL"]   # results 同序


def test_multiple_decisions_partially_consumed_skipped(env):
    """多份中某份已归档(已消费) → 只处理未消费份，升序不被打乱。"""
    from lkl.broker import tradeops
    from lkl.broker.archiver import archive_one
    p1 = _put_decision_at(env, [{"code": "600000", "action": "BUY"}], "20260904_092000")
    _put_decision_at(env, [{"code": "600000", "action": "SELL", "exec": "CLOSE_ALL"}], "20260904_093000")
    archive_one(p1)                                          # 先消费归档第一份
    ex = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex) == 1          # 仅未消费份成交
    assert [sig.action for sig, _ in ex.submits] == ["SELL"]
    assert _fileio().latest("decisions") is None


def test_all_consumed_no_new_results(env):
    """全部决策文件已归档(已消费)残留 → 不处理、不重写 results（防空 results 门控）。"""
    from lkl.broker import tradeops
    from lkl.broker.archiver import archive_one
    p1 = _put_decision_at(env, [{"code": "601988", "action": "BUY"}], "20260904_093000")
    p2 = _put_decision_at(env, [{"code": "601988", "action": "SELL", "exec": "CLOSE_ALL"}], "20260904_093500")
    archive_one(p1)
    archive_one(p2)
    n_results = len(list(env.glob("results_*.json")))
    ex = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex) == 0
    assert ex.submits == []                                  # 不重下
    assert len(list(env.glob("results_*.json"))) == n_results  # 不新增 results
    assert _fileio().latest("decisions") is None             # 残留已被回收


def test_remove_archived_guard_no_residue_and_cleanup(env, monkeypatch):
    """remove_archived 守卫校验不再 pull 落盘污染本地；清理旧残留；不误删新一天。"""
    import json
    from lkl.broker import cleanup, fileio, remote
    monkeypatch.setattr(remote, "enabled", lambda: True)
    monkeypatch.setattr(remote, "newest", lambda kind: "decisions_20260904_093235.json")
    removed = []
    monkeypatch.setattr(remote, "rm", lambda name: removed.append(name))
    # 本地已存在同名残留（旧守卫 pull 落盘产物），应被清理
    residue = fileio.directory() / "decisions_20260904_093235.json"
    residue.write_text(json.dumps({"for_date": "2026-09-04"}), encoding="utf-8")
    assert cleanup._for_date_from_name("decisions_20260904_093235.json") == "2026-09-04"
    assert cleanup.remove_archived("2026-09-04") == 1
    assert removed == ["decisions_20260904_093235.json"]
    assert not residue.exists()                           # 本地残留被清理
    # 远端是别一天 → 保留，不删、不产生任何本地新文件
    monkeypatch.setattr(remote, "newest", lambda kind: "decisions_20260905_093000.json")
    n_before = len(list(fileio.directory().glob("decisions_*.json")))
    assert cleanup.remove_archived("2026-09-04") == 0
    assert removed == ["decisions_20260904_093235.json"]  # 未新增删除
    assert len(list(fileio.directory().glob("decisions_*.json"))) == n_before


def test_open_pos_buy_normal(env):
    """验收②：exec=OPEN_POS + BUY → 正常开仓，按决策建议量提交。"""
    from lkl.broker import exchange, ledger, tradeops
    _put_decision(env, [{"code": "601988", "action": "BUY", "exec": "OPEN_POS",
                         "volume": 100}])
    ex = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex) == 1
    assert len(ex.submits) == 1
    sig, vol = ex.submits[0]
    assert sig.exec_ == "OPEN_POS"
    assert vol == 100                                        # 按建议量开仓
    assert any("601988|BUY" in r for r in ledger.load())
    rows = exchange.load_results(_today())
    assert rows and rows[0]["ok"] is True
    assert not any(r["status"] == "EXCLUDED" for r in rows)


def test_legacy_schema1_sell_fallback_close_all(env):
    """验收③：schema:1 旧 SELL（无 exec）→ 不崩溃、兜底 CLOSE_ALL、正常提交。"""
    from lkl.broker import exchange, tradeops
    _put_decision(env, [{"code": "601988", "action": "SELL", "volume": 100}])
    sigs = exchange.load_decisions()
    assert sigs[0].exec_ == "CLOSE_ALL"                      # 解析层兜底归一
    ex = FakeExecutor(_filled())
    assert tradeops.process_once(executor=ex) == 1
    assert len(ex.submits) == 1
    assert ex.submits[0][0].exec_ == "CLOSE_ALL"
    assert ex.submits[0][1] == 0                             # 兜底 CLOSE_ALL → 交 orders 清仓
    assert _fileio().latest("decisions") is None


def test_exec_action_mismatch_rejected(env):
    """exec 与 action 强配对：OPEN_POS 只配 BUY、CLOSE_ALL 只配 SELL → 拒绝整批。"""
    from lkl.broker import exchange

    _put_decision(env, [{"code": "601988", "action": "SELL", "exec": "OPEN_POS"}])
    with pytest.raises(exchange.DecisionValidationError):
        exchange.load_decisions()

    _put_decision(env, [{"code": "601988", "action": "BUY", "exec": "CLOSE_ALL"}])
    with pytest.raises(exchange.DecisionValidationError):
        exchange.load_decisions()

    _put_decision(env, [{"code": "601988", "action": "BUY", "exec": "FROB"}])
    with pytest.raises(exchange.DecisionValidationError):
        exchange.load_decisions()