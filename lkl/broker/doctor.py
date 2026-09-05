"""首次使用自检向导（产品7-建议1）：逐项验证才允许启用交易。

`lkl doctor`：python/gmtrade/凭据/终端/账户登录/交换目录(可写)/决策样例 逐项 OK/✗。
arm（切实盘）前置调用 `quick()`：关键项不过即拒绝进入实盘。
"""
from __future__ import annotations

import sys


def _check(name: str, ok: bool, why: str = "") -> tuple[str, bool, str]:
    return (name, ok, why)


def run() -> int:
    """打印全部自检项；0=全部通过。"""
    checks = _all_checks()
    bad = 0
    for name, ok, why in checks:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}" + (f"  ({why})" if why and not ok else ""))
        bad += (not ok)
    print(f"自检完成：通过 {len(checks) - bad}/{len(checks)}" + ("（可切实盘）" if bad == 0 else "（存在失败项）"))
    return 0 if bad == 0 else 1


def quick() -> tuple[bool, list[str]]:
    """arm 前置的关键项：python/gmtrade/凭据/交换目录可写。返回 (通过?, 失败清单)。"""
    fails = [why for n, ok, why in _all_checks()
             if not ok and n in ("python", "gmtrade", "凭据", "交换目录")]
    return (not fails, fails)


def table() -> dict:
    """全部自检项 → JSON 可序列化 {ok, checks:[{name,ok,why}]}（看板 /api/doctor）。"""
    checks = _all_checks()
    return {"ok": all(ok for _, ok, _ in checks),
            "checks": [{"name": n, "ok": ok, "why": why} for n, ok, why in checks]}


def _all_checks():
    from lkl.broker import config, exchange, fileio, gate

    checks = []
    # python / gmtrade
    checks.append(_check("python", sys.version_info >= (3, 10),
                         f"需 ≥3.10，当前 {sys.version.split()[0]}"))
    try:
        import gmtrade  # noqa: F401
        checks.append(_check("gmtrade", True))
    except ImportError:
        checks.append(_check("gmtrade", False, "未安装（需 .venv-trade 的 cp310 环境）"))
    # 凭据
    tok, acc = config.token(), config.account_id()
    checks.append(_check("凭据", bool(tok and acc),
                         "缺少 GM_TOKEN/GM_ACCOUNT_ID"))
    # 终端
    checks.append(_check("终端(7001)", gate.up(), "金矿终端未启动/端口不可达"))
    checks.append(_check("账户登录", gate.account_ready(), "终端可达但账户未登录"))
    # 交换目录
    d = fileio.directory()
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".doctor"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(_check("交换目录", True, str(d)))
    except OSError as e:
        checks.append(_check("交换目录", False, f"不可写 {d}: {e}"))
    # 决策样例
    p = exchange.decision_file()
    checks.append(_check("决策样例", p is not None, "交换目录暂无当日 decisions（可等策略端投递）"))
    return checks