"""LKL-Trade 打包入口（frozen/onedir 环境）。

PyInstaller 打包后无 `-m` 模块运行方式，托盘/CLI 统一经本入口：
    LKL-Trade.exe tray|sup [interval]|dash [port]|health|doctor|govern ...
源码环境仍走 lkl.main / scripts/lkl_tray.py，不受影响。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOG = Path(sys.executable).resolve().parent / "logs"


def _cmd_health() -> int:
    from lkl.broker import config
    config.ensure_config()
    from scripts.lkl_tray import health
    return health()


def _cmd_doctor() -> int:
    from lkl.broker import config
    config.ensure_config()
    from lkl.broker import doctor
    return doctor.run()


def _cmd_tray() -> int:
    from lkl.broker import config
    config.ensure_config()
    from scripts.lkl_tray import main as tray_main
    return tray_main()


def _cmd_dash(argv: list[str]) -> int:
    from lkl.broker import config
    config.ensure_config()
    from dashboard.trade_server import run as d
    return d(argv)


def _cmd_sup(argv: list[str]) -> int:
    from lkl.broker import config
    config.ensure_config()
    from lkl.supervisor import run as s
    return s(argv)

def _cmd_govern(argv: list[str]) -> int:
    from lkl.broker import governor
    action = argv[0] if argv else "status"
    reason = argv[1] if len(argv) > 1 else ""
    print(governor.run_cli(action, reason))
    return 0


def _cmd_update(argv: list[str]) -> int:
    """update check：CLI 版更新检查（调试/无人值守机器用）。

    完整更新闭环（下载→静默安装→重启托盘）在托盘菜单；CLI 只查不装。
    """
    from lkl.broker import config, updater
    config.ensure_config()
    url = config.update_url()
    if not url:
        print("未配置更新源：config.env 填 GM_UPDATE_URL 后重试", file=sys.stderr)
        return 1
    try:
        info = updater.check(url, config.APP_VERSION)
    except updater.UpdaterError as e:
        print(f"检查更新失败：{e}", file=sys.stderr)
        return 1
    if info is None:
        print(f"已是最新版本 v{config.APP_VERSION}")
        return 0
    print(f"发现新版本 v{info['version']}（当前 v{config.APP_VERSION}）")
    print(f"安装包：{info['url']}")
    if info.get("note"):
        print(f"说明：{info['note']}")
    print("更新请在托盘菜单点「立即更新」，或手动下载安装包。")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "tray"
    rest = argv[1:]
    try:
        if cmd == "tray":
            return _cmd_tray()
        if cmd == "sup":
            return _cmd_sup(rest)
        if cmd == "dash":
            return _cmd_dash(rest)
        if cmd == "health":
            return _cmd_health()
        if cmd == "doctor":
            return _cmd_doctor()
        if cmd == "govern":
            return _cmd_govern(rest)
        if cmd == "update":
            return _cmd_update(rest)
        print(f"未知命令: {cmd}（可用 tray|sup|dash|health|doctor|govern|update）", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    except Exception:
        import traceback
        try:
            _LOG.mkdir(parents=True, exist_ok=True)
            (_LOG / "boot.err").write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
