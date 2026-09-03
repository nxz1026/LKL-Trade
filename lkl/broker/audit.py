"""交易三文件一致性核对：decisions/results/holdings 日期 + 成交覆盖率。"""
from __future__ import annotations

from lkl.broker import fileio, ledger, remote, trade_date


def _label(when: str | None, today: str) -> str:
    if when is None:
        return "缺文件"
    return "今日 ✓" if when == today else f"过期/错日({when}) ✗"


def run() -> int:
    """打印三文件日期与今日(Shanghai)比对 + 决策成交覆盖率。"""
    remote.pull("decisions")
    today = trade_date.trade_date()
    d = fileio.read("decisions")
    r = fileio.read("results")
    h = fileio.read("holdings")
    bad = []
    for name, data in (("decisions", d), ("results", r), ("holdings", h)):
        when = data.get("for_date") or data.get("trade_date")
        if when != today:
            bad.append(name)
        print(f"  {name:10} {when or '-':12} {_label(when, today)} (今日={today})")
    refs = {(it.get("action"), it.get("code")) for it in d.get("actions", [])}
    try:
        done = {tuple(ref.split("|")[1:]) for ref in ledger.load()}
    except ledger.LedgerCorruptError as e:
        print(f"  ✗ executed.json 损坏，阻断核对：{e}")
        return 1
    # 去重只信防重账本（已成交）；results 现为尝试明细（含未成交/重试）
    missing = refs - done
    if not d.get("for_date"):
        print("  (decisions 缺——本机不会执行)")
    print(f"  决策{len(refs)}条 / 已成交{len(done)}条 / 差{sorted(missing)}"
          if missing else f"  决策{len(refs)}条已全部成交 ✓")
    print(f"  (executed 账本 {len(done)} 条=已成交防重；results=尝试明细)")
    return 0 if not bad and not missing else 1