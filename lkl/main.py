"""LKL-Trade 本地交易 CLI：sim 查询/手动 | trade 执行/check/watch | dash 看板。"""
from __future__ import annotations

import argparse
import logging
import sys

def _sim(argv: list[str]) -> int:
    """lkl sim [info|order <code> <BUY|SELL> [股数]|orders|sync]。"""
    from lkl.broker import cli
    return cli.run(argv)


def _trade(argv: list[str]) -> int:
    """lkl trade check|执行[YYYY-MM-DD]|watch。"""
    if argv and argv[0] == "check":
        from lkl.broker.audit import run as audit_run
        return audit_run()
    from lkl.broker import trader
    return trader.run(argv)


def _dash(argv: list[str]) -> int:
    """lkl dash [port=8200]：本地看板。"""
    from dashboard.trade_server import run as dash_run
    return dash_run(argv)
_COMMANDS = {
    "sim":   (_sim, "info 账户|order <code> <BUY|SELL> [股数]|orders|sync"),
    "trade": (_trade, "交易：check 核对 | [YYYY-MM-DD] 执行 | watch 盯盘"),
    "dash":  (_dash, "本地看板 [port=8200]"),
}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="lkl", description="LKL-Trade 自动交易端")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for name, (_fn, help_text) in _COMMANDS.items():
        sub.add_parser(name, help=help_text)
    args, rest = parser.parse_known_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    return _COMMANDS[args.command][0](rest)


if __name__ == "__main__":
    raise SystemExit(main())