"""LKL-Trade CLI：sim 查询 | trade 执行 | sup 调度 | dash 看板。"""
import argparse
import logging
import sys


def _sim(argv): from lkl.broker import cli; return cli.run(argv)
def _trade(argv):
    if argv and argv[0] == "check":
        from lkl.broker.audit import run as a; return a()
    if argv and argv[0] == "preview":
        from lkl.broker import tradeops
        return tradeops.preview(argv[1] if len(argv) > 1 else None)
    if argv and argv[0] == "recon":
        from lkl.broker import recon
        return recon.run(argv[1] if len(argv) > 1 else None)
    if argv and argv[0] == "resolve":
        from lkl.broker import resolve
        if len(argv) < 3:
            print("用法: lkl trade resolve <ref|for_date> <retry|ignore|complete> [note]")
            return 1
        ref, act = argv[1], argv[2]
        note = " ".join(argv[3:]) if len(argv) > 3 else ""
        print(resolve.run_cli(ref, act, note))
        return 0
    if argv and argv[0] == "alerts":
        from lkl.broker import alerts
        s = alerts.summary()
        print(f"告警汇总：CRIT {s['crit']} / WARN {s['warn']} / 共 {s['total']}")
        for r in alerts.list_alerts(30):
            print(f"  [{r['level']}] {r['ts']}  {r['msg']}")
        return 0
    if argv and argv[0] == "govern":
        from lkl.broker import governor
        action = argv[1] if len(argv) > 1 else "status"
        reason = argv[2] if len(argv) > 2 else ""
        print(governor.run_cli(action, reason))
        return 0
    from lkl.broker import trader; return trader.run(argv)
def _sup(argv):
    from lkl.supervisor import run as s; return s(argv)
def _dash(argv):
    from dashboard.trade_server import run as d; return d(argv)
def _archive(argv):
    from lkl.broker.archiver import run as a; return a(argv)


def _doctor(argv):
    from lkl.broker import doctor
    return doctor.run()


_CMDS = {
    "sim": (_sim, "账户|order|orders|sync"),
    "doctor": (_doctor, "首次使用自检向导"),
    "trade": (_trade, "check|执行[date]|watch"),
    "sup": (_sup, "交易调度器[interval=60]"),
    "dash": (_dash, "看板 [port]"),
    "archive": (_archive, "归档已消费文件 [YYYY-MM-DD]"),
}


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="lkl", description="LKL-Trade 自动交易端")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    for name, (_f, help_text) in _CMDS.items():
        sub.add_parser(name, help=help_text)
    a, rest = ap.parse_known_args(argv)
    if not a.command:
        ap.print_help(); return 1
    return _CMDS[a.command][0](rest)


if __name__ == "__main__":
    raise SystemExit(main())