"""LKL-Trade 系统托盘（Windows）：替代两个 python 黑框，托管 sup/dash。

- 子进程用 pythonw + CREATE_NO_WINDOW 启动（无控制台黑框），日志写 <repo>/logs/。
- 托盘菜单每 3 秒重建（状态行实时）：演练/实盘/急停/解除、启动/停止 调度与看板、
  打开看板、退出（退出默认停止托管子进程）。
- 运行：pythonw scripts/lkl_tray.py（计划任务 LKLTray 开机拉起，无黑框）。
- 自检：python scripts/lkl_tray.py health。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_LOG = _REPO / "logs"
sys.path.insert(0, str(_REPO))

_PY = _REPO / ".venv-trade" / "Scripts" / "python.exe"
_PYW = _REPO / ".venv-trade" / "Scripts" / "pythonw.exe"
_PY = _PY if _PY.exists() else Path(sys.executable)
_PYW = _PYW if _PYW.exists() else _PY
_DASH_PORT = "8200"

_SERVICES = {
    "sup": [_PYW, "-m", "lkl.main", "sup"],
    "dash": [_PYW, "-m", "lkl.main", "dash", _DASH_PORT],
}


class TrayManager:
    """托管 sup/dash：隐藏窗口启动 + 停止 + 存活查询。"""

    def __init__(self):
        self.procs: dict[str, subprocess.Popen] = {}

    def start(self, name: str) -> str:
        if self.is_alive(name):
            return f"{name} 已在运行"
        _LOG.mkdir(parents=True, exist_ok=True)
        logf = open(_LOG / f"{name}.log", "ab", buffering=0)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.Popen(_SERVICES[name], cwd=str(_REPO),
                             stdin=subprocess.DEVNULL,
                             stdout=logf, stderr=logf, creationflags=flags)
        self.procs[name] = p
        time.sleep(0.6)
        return f"{name} 已启动（隐藏）" if self.is_alive(name) else f"{name} 启动失败"

    def stop(self, name: str) -> str:
        p = self.procs.get(name)
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        self.procs.pop(name, None)
        return f"{name} 已停止"

    def is_alive(self, name: str) -> bool:
        p = self.procs.get(name)
        return bool(p and p.poll() is None)

    def status(self) -> dict:
        return {n: self.is_alive(n) for n in _SERVICES}

    def stop_all(self) -> None:
        for n in list(self.procs):
            self.stop(n)


_mgr = TrayManager()


def _govern(action: str, note: str = "") -> str:
    from lkl.broker import governor
    return governor.run_cli(action, note)


def _import(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def health() -> int:
    ok = True
    for label, cond in (("pythonw", Path(_PYW).exists()),
                        ("pystray", _import("pystray")),
                        ("pillow", _import("PIL")),
                        ("lkl", _import("lkl"))):
        print(("  ✓ " if cond else "  ✗ ") + label)
        ok = ok and cond
    return 0 if ok else 1


def _run_tray() -> None:
    import pystray
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (64, 64), "#1a1a2e")
    d = ImageDraw.Draw(img)
    d.rectangle((6, 6, 58, 58), outline="#2a6", width=4)
    d.text((12, 18), "LKL", fill="#ffffff")
    icon = pystray.Icon("LKL-Trade", img, "LKL-Trade")

    def rebuild(_icon=None):
        try:
            st = _mgr.status()

            def sep():
                return pystray.MenuItem("—", lambda: None, enabled=False)
            items = []
            items.append(pystray.MenuItem(
                "调度 sup: " + ("运行中" if st["sup"] else "停止"),
                lambda: None, enabled=False))
            items.append(pystray.MenuItem(
                "看板 dash: " + ("运行中" if st["dash"] else "停止"),
                lambda: None, enabled=False))
            items.append(sep())
            items.append(pystray.MenuItem("打开看板", _open_web))
            items.append(pystray.MenuItem("启动服务", pystray.Menu(
                pystray.MenuItem("启动调度 sup", lambda: _act("sup", "start")),
                pystray.MenuItem("启动看板 dash", lambda: _act("dash", "start")))))
            items.append(pystray.MenuItem("停止服务", pystray.Menu(
                pystray.MenuItem("停止调度 sup", lambda: _act("sup", "stop")),
                pystray.MenuItem("停止看板 dash", lambda: _act("dash", "stop")))))
            items.append(pystray.MenuItem("交易模式", pystray.Menu(
                pystray.MenuItem("演练 dry", lambda: _govern_then("dry")),
                pystray.MenuItem("实盘 armed", lambda: _govern_then("arm")),
                pystray.MenuItem("紧急停止", lambda: _govern_then("halt", "托盘急停")),
                pystray.MenuItem("解除停止", lambda: _govern_then("resume")))))
            items.append(sep())
            items.append(pystray.MenuItem("退出（停止服务）", _exit))
            icon.menu = pystray.Menu(*items)
        except Exception:
            pass

    def _open_web():
        webbrowser.open(f"http://127.0.0.1:{_DASH_PORT}")
        _notify("已在浏览器打开看板")

    def _act(service: str, op: str):
        def run():
            msg = _mgr.start(service) if op == "start" else _mgr.stop(service)
            _notify(msg)
            rebuild()
        threading.Thread(target=run, daemon=True).start()

    def _govern_then(action: str, note: str = ""):
        def run():
            try:
                _notify(_govern(action, note))
            except Exception as e:
                _notify(f"治理失败：{e}")
            rebuild()
        threading.Thread(target=run, daemon=True).start()

    def _exit():
        _mgr.stop_all()
        icon.stop()

    def _notify(text: str):
        try:
            icon.notify(text, "LKL-Trade")
        except Exception:
            pass

    def _auto_refresh():
        while True:
            time.sleep(3)
            rebuild()

    def _autostart():
        time.sleep(1.5)
        for n in ("sup", "dash"):
            try:
                _notify(_mgr.start(n))
            except Exception as e:
                _notify(f"{n} 自动启动失败：{e}")
        rebuild()

    threading.Thread(target=_auto_refresh, daemon=True).start()
    threading.Thread(target=_autostart, daemon=True).start()
    rebuild()
    icon.run()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "health":
        return health()
    if os.name != "nt":
        print("托盘仅支持 Windows；本机请用 'lkl sup' / 'lkl dash'")
        return 1
    _LOG.mkdir(parents=True, exist_ok=True)
    _run_tray()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())