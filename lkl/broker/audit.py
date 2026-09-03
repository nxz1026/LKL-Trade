"""交易三文件一致性核对：decisions/results/holdings 日期 + 执行覆盖率。"""
from __future__ import annotations

from lkl.broker import fileio, ledger, remote, trade_date


def _label(when: str | None, today: str) -> str:
    if when is None:
        return "缺文件"
    return "今日 ✓" if when == today else f"过期/错日({when}) ✗"


def run() -> int:
    """打印三文件日期与今日(Shanghai)比对 + 决策执行覆盖率。"""
    remote.pull("decisions.json")
    today = trade_date.trade_date()
    d = fileio.read("decisions.json")
    r = fileio.read("results.json")
    h = fileio.read("holdings.json")
    bad = []
    for name, data in (("decisions", d), ("results", r), ("holdings", h)):
        when = data.get("for_date") or data.get("trade_date")
        if when != today:
            bad.append(name)
        print(f"  {name:10} {when or '-':12} {_label(when, today)} (今日={today})")
    refs = {(it.get("action"), it.get("code")) for it in d.get("actions", [])}
    done_r = {(t.get("action"), t.get("code")) for t in r.get("trades", [])}
    done_l = {tuple(ref.split("|")[1:]) for ref in ledger.load()}
    done = done_r | done_l
    missing = refs - done
    if not d.get("for_date"):
        print("  (decisions 缺——本机不会执行)")
    print(f"  决策{len(refs)}条 / 已执行{len(done)}条 / 缺回报{sorted(missing)}"
          if missing else f"  决策{len(refs)}条已全部执行 ✓")
    print(f"  (results 缺=已消费/待生成；executed 账本 {len(done_l)} 条为持续防重)")
    return 0 if not bad and not missing else 1