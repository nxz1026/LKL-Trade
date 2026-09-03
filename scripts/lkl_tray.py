"""LKL-Trade 系统托盘（Windows，零第三方依赖，ctypes+Win32）。

替代旧的两个 python 控制台任务：托盘隐藏托管 sup/dash（pythonw + CREATE_NO_WINDOW），
日志写 <repo>/logs/。开机自动拉起两者。

- 左键双击：打开看板；右键：状态/启动/停止/交易模式(演练·实盘·急停·解除)/退出。
- 通知用气泡(Shell_NotifyIcon NIM_MODIFY)；操作结果经气泡提示。
- 运行：pythonw scripts/lkl_tray.py（计划任务 LKLTray 开机拉起，无黑框）。
- 自检：python scripts/lkl_tray.py health。
- 测试钩子：LKL_TRAY_EXIT_MS=<毫秒> 到时自动退出（用于无人值守自测）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
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

_DASH_PORT = "8200"
_WM_APP = 0x8000
_NIM_ADD, _NIM_MODIFY = 0, 1
_NIF_MESSAGE, _NIF_ICON, _NIF_TIP, _NIF_INFO = 0x1, 0x2, 0x4, 0x10
_NIIF_INFO = 1
_TPM_RETURNCMD, _TPM_RIGHTBUTTON, _TPM_NONOTIFY = 0x100, 0x2, 0x80
_MF_SEPARATOR, _MF_GRAYED = 0x800, 0x1
_WM_RBUTTONUP, _WM_LBUTTONDBLCLK, _WM_DESTROY = 0x0205, 0x0203, 0x0002
_IDI_APPLICATION = 32512

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

_LRESULT = ctypes.c_ssize_t  # LONG_PTR（wintypes 无 LRESULT）
WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HANDLE),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT),
        ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uTimeout", wt.UINT), ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wt.DWORD), ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wt.HICON),
    ]


def _bind(ftn, restype, *argtypes):
    ftn.restype = restype
    if argtypes:
        ftn.argtypes = list(argtypes)


_bind(user32.DefWindowProcW, _LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
_bind(user32.CreateWindowExW, wt.HWND, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR,
      wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p)
_bind(user32.RegisterClassW, ctypes.c_ushort, ctypes.POINTER(WNDCLASSW))
_bind(user32.CreatePopupMenu, wt.HMENU)
_bind(user32.AppendMenuW, wt.BOOL, wt.HMENU, wt.UINT, wt.UINT, wt.LPCWSTR)
_bind(user32.TrackPopupMenu, wt.UINT, wt.HMENU, wt.UINT, ctypes.c_int,
      ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p)
_bind(user32.DestroyMenu, wt.BOOL, wt.HMENU)
_bind(user32.GetCursorPos, wt.BOOL, ctypes.POINTER(wt.POINT))
_bind(user32.LoadIconW, wt.HICON, wt.HINSTANCE, ctypes.c_void_p)
_bind(user32.PeekMessageW, wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND,
      wt.UINT, wt.UINT, wt.UINT)
_bind(user32.TranslateMessage, wt.BOOL, ctypes.POINTER(wt.MSG))
_bind(user32.DispatchMessageW, _LRESULT, ctypes.POINTER(wt.MSG))
_bind(user32.PostMessageW, wt.BOOL, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
_bind(user32.PostQuitMessage, None, ctypes.c_int)
_bind(user32.SetForegroundWindow, wt.BOOL, wt.HWND)
kernel32 = ctypes.windll.kernel32
_bind(kernel32.GetModuleHandleW, wt.HINSTANCE, wt.LPCWSTR)
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]

_PYW = _REPO / ".venv-trade" / "Scripts" / "pythonw.exe"
_PY = _REPO / ".venv-trade" / "Scripts" / "python.exe"
_PY = _PY if _PY.exists() else Path(sys.executable)
_PYW = _PYW if _PYW.exists() else _PY
_SERVICES = {"sup": [_PYW, "-m", "lkl.main", "sup"],
             "dash": [_PYW, "-m", "lkl.main", "dash", _DASH_PORT]}


class TrayManager:
    def __init__(self):
        self.procs: dict[str, subprocess.Popen] = {}

    def start(self, name: str) -> str:
        if self.is_alive(name):
            return f"{name} 已在运行"
        _LOG.mkdir(parents=True, exist_ok=True)
        logf = open(_LOG / f"{name}.log", "ab", buffering=0)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.Popen(_SERVICES[name], cwd=str(_REPO),
                             stdin=subprocess.DEVNULL, stdout=logf,
                             stderr=logf, creationflags=flags)
        self.procs[name] = p
        time.sleep(0.8)
        return f"{name} 已启动（隐藏）" if self.is_alive(name) else f"{name} 启动失败，见 logs/{name}.log"

    def stop(self, name: str) -> str:
        """停服务：先 terminate，超时或服务经 venv stub 启动(父死 base 会孤儿)
        则 taskkill 树杀兜底，保证退出托盘时 sup/dash 真身一并消失。"""
        p = self.procs.get(name)
        pid = p.pid if p else 0
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=4)
            except subprocess.TimeoutExpired:
                p.kill()
        if pid:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, creationflags=flags, timeout=10)
            except Exception:
                pass   # 已退出则 taskkill 报不存在，忽略
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
_icon_data = {}


def _govern(action: str, note: str = "") -> str:
    from lkl.broker import governor
    return governor.run_cli(action, note)


def health() -> int:
    ok = True
    for label, cond in (("pythonw", Path(_PYW).exists()),
                        ("user32", True), ("shell32", True),
                        ("lkl", _import("lkl"))):
        print(("  ✓ " if cond else "  ✗ ") + label)
        ok = ok and cond
    return 0 if ok else 1


def _import(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


class Tray:
    def __init__(self):
        self.hwnd = None
        self._nid = NOTIFYICONDATAW()
        self._hicon = None
        self._cls_atom = None
        self._quit_ms = int(os.environ.get("LKL_TRAY_EXIT_MS", "0") or 0)
        self._started = time.monotonic()

    # ---- Win32 装配 ----
    def _register_class(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc = WNDPROC(self._proc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "LKLTrayWnd"
        wc.style = 0
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            raise ctypes.WinError(ctypes.get_last_error() or 87)
        self._cls_atom = atom
        self._hinst = hinst

    def _create_window(self) -> None:
        hwnd = user32.CreateWindowExW(
            0, "LKLTrayWnd", "LKL-Trade", 0,
            0, 0, 0, 0, None, None, self._hinst, None)  # 普通隐藏窗口(可前台化)，不进任务栏
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error() or 87)
        self.hwnd = hwnd

    def _add_icon(self) -> None:
        self._hicon = user32.LoadIconW(None, _IDI_APPLICATION)
        nid = self._nid
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        nid.uCallbackMessage = _WM_APP + 1
        nid.hIcon = self._hicon
        nid.szTip = "LKL-Trade（调度+看板）"
        if not shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid)):
            raise ctypes.WinError(ctypes.get_last_error() or 87)

    def notify(self, text: str) -> None:
        nid = self._nid
        nid.uFlags = _NIF_INFO | _NIF_ICON | _NIF_TIP
        nid.szInfoTitle = "LKL-Trade"
        nid.szInfo = text[:255]
        nid.dwInfoFlags = _NIIF_INFO
        nid.uTimeout = 4000
        shell32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(nid))

    # ---- 菜单 ----
    def _build_menu(self, actions: list) -> list:
        """actions: (text, enabled, callback|None)；返回 (hmenu, id_map)。"""
        hmenu = user32.CreatePopupMenu()
        id_map: dict[int, callable] = {}
        next_id = 1
        for text, enabled, cb in actions:
            if cb is None and text == "-":
                user32.AppendMenuW(hmenu, _MF_SEPARATOR, 0, None)
                continue
            flags = 0
            if not enabled:
                flags |= _MF_GRAYED
            user32.AppendMenuW(hmenu, flags, next_id, text)
            id_map[next_id] = cb if enabled else None
            next_id += 1
        return hmenu, id_map

    def _show_menu(self) -> None:
        st = _mgr.status()
        acts = [
            (f"调度 sup: {'运行中' if st['sup'] else '停止'}", False, None),
            (f"看板 dash: {'运行中' if st['dash'] else '停止'}", False, None),
            ("-", False, None),
            ("打开看板", True, lambda: self._safe("打开看板", _open_web)),
            ("-", False, None),
            ("启动调度 sup", True, lambda: self._run("sup", "start")),
            ("启动看板 dash", True, lambda: self._run("dash", "start")),
            ("停止调度 sup", True, lambda: self._run("sup", "stop")),
            ("停止看板 dash", True, lambda: self._run("dash", "stop")),
            ("-", False, None),
            ("演练 dry", True, lambda: self._govern("dry")),
            ("实盘 armed", True, lambda: self._govern("arm")),
            ("紧急停止", True, lambda: self._govern("halt", "托盘急停")),
            ("解除停止", True, lambda: self._govern("resume")),
            ("-", False, None),
            ("退出（停止服务）", True, self._exit),
        ]
        try:
            hmenu, id_map = self._build_menu(acts)
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(self.hwnd)   # 前台化，菜单才可交互
            chosen = user32.TrackPopupMenu(
                hmenu, _TPM_RETURNCMD | _TPM_RIGHTBUTTON | _TPM_NONOTIFY,
                pt.x, pt.y, 0, self.hwnd, None)
            user32.DestroyMenu(hmenu)
        except Exception:
            self._log_err()
            return
        if chosen and chosen in id_map and id_map[chosen]:
            cb = id_map[chosen]
            if cb is self._exit:
                cb()
            else:
                threading.Thread(target=cb, daemon=True).start()

    # ---- 动作 ----
    def _run(self, service: str, op: str) -> None:
        msg = _mgr.start(service) if op == "start" else _mgr.stop(service)
        self.notify(msg)

    def _govern(self, action: str, note: str = "") -> None:
        try:
            self.notify(_govern(action, note))
        except Exception as e:
            self.notify(f"治理失败：{e}")

    def _log_err(self) -> None:
        import traceback
        try:
            with open(_LOG / "lkl_tray.err", "a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except OSError:
            pass

    def _safe(self, label: str, fn) -> None:
        try:
            fn()
        except Exception as e:
            self.notify(f"{label}失败：{e}")

    def _exit(self) -> None:
        _mgr.stop_all()
        user32.PostMessageW(self.hwnd, _WM_DESTROY, 0, 0)

    # ---- 消息泵 ----
    def _proc(self, hwnd, msg, wp, lp):
        try:
            return self._proc_i(hwnd, msg, wp, lp)
        except Exception:
            return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _proc_i(self, hwnd, msg, wp, lp):
        if msg == _WM_APP + 1 and wp == 1:          # 托盘回调(uID=1)
            code = lp & 0xFFFF
            if code == _WM_RBUTTONUP:
                self._show_menu()      # 必须在窗口线程同步弹（TrackPopupMenu 同线程要求）
            elif code == _WM_LBUTTONDBLCLK:
                threading.Thread(target=_open_web, daemon=True).start()
            return 0
        if msg == _WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _autostart(self) -> None:
        for n in ("sup", "dash"):
            try:
                msg = _mgr.start(n)
                if "失败" in msg:
                    self.notify(msg)
            except Exception as e:
                self.notify(f"{n} 自动启动失败：{e}")

    def run(self) -> int:
        self._register_class()
        self._create_window()
        self._add_icon()
        threading.Thread(target=self._autostart, daemon=True).start()
        msg = wt.MSG()
        _WM_QUIT = 0x0012
        while True:
            if self._quit_ms and time.monotonic() - self._started > self._quit_ms / 1000:
                break
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                if msg.message == _WM_QUIT:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.15)
        _mgr.stop_all()
        if self._quit_ms:
            print("tray 自测运行结束（自动退出，服务已停止）", flush=True)
        return 0


def _open_web() -> None:
    webbrowser.open(f"http://127.0.0.1:{_DASH_PORT}")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "health":
        return health()
    if os.name != "nt":
        print("托盘仅支持 Windows；本机请用 'lkl sup' / 'lkl dash'")
        return 1
    _LOG.mkdir(parents=True, exist_ok=True)
    try:
        tray = Tray()
        return tray.run()
    except Exception:
        import traceback
        try:
            (_LOG / "lkl_tray.err").write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())