from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dashboard.trade_state import state
from dashboard.sys_state import state as sys_state
from lkl.broker import alerts, config, doctor, fileio, governor, recon, schedule, session, tradeops

log = logging.getLogger("lkl.dash")

_HTML = Path(__file__).with_name("trade_index.html")

_ACTS = ("status", "dry", "arm", "halt", "resume")

# 本地回环治理令牌：写 exchange_dir/.dash_token 供运维读取；POST /api/govern 必须携带
# （防本机进程/浏览器恶意页面触发 arm/halt 等资金级操作）
_TOKEN = secrets.token_hex(16)


def _persist_token() -> None:
    try:
        p = fileio.directory() / ".dash_token"
        p.parent.mkdir(parents=True, exist_ok=True)
        fileio.atomic_write(p, _TOKEN)
    except OSError:
        pass


def _query_date(path: str) -> str | None:
    """解析 ?d=YYYY-MM-DD；兼容旧式裸值 ?YYYY-MM-DD。"""
    q = urlparse(path).query
    if not q:
        return None
    vals = parse_qs(q).get("d")
    return vals[0] if vals else q.strip() or None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            self._get()
        except Exception as e:
            if self.path.startswith("/api/"):
                self._send(200, "application/json",
                           json.dumps({"error": f"{type(e).__name__}: {e}"},
                                      ensure_ascii=False).encode("utf-8"))
            else:
                self._send(500, "text/plain; charset=utf-8",
                           f"internal error: {type(e).__name__}: {e}".encode("utf-8"))

    def _get(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _HTML.read_bytes())
        elif self.path == "/api/state":
            self._send(200, "application/json",
                       json.dumps(state(), ensure_ascii=False, default=str).encode("utf-8"))
        elif self.path == "/api/sys":
            self._send(200, "application/json",
                       json.dumps(sys_state(), ensure_ascii=False, default=str).encode("utf-8"))
        elif self.path == "/api/token":
            self._send(200, "application/json", json.dumps({"token": _TOKEN}).encode("utf-8"))
        elif self.path.startswith("/api/versions"):
            self._send(200, "application/json",
                       json.dumps(versions_view(_query_date(self.path)), ensure_ascii=False,
                                  default=str).encode("utf-8"))
        elif self.path.startswith("/api/archive"):
            self._send(200, "application/json",
                       json.dumps(archive_view(_query_date(self.path)), ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/api/preview"):
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    tradeops.preview(_query_date(self.path))
                    err = ""
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"
            self._send(200, "application/json",
                       json.dumps({"text": buf.getvalue().strip(), "error": err},
                                  ensure_ascii=False).encode("utf-8"))
        elif self.path == "/api/alerts":
            recs = alerts.list_alerts(200)
            self._send(200, "application/json",
                       json.dumps({"summary": alerts.summary(), "recs": recs},
                                  ensure_ascii=False).encode("utf-8"))
        elif self.path == "/api/risk_limits":
            self._send(200, "application/json",
                       json.dumps({"limits": config.risk_limits()},
                                  ensure_ascii=False).encode("utf-8"))
        elif self.path == "/api/doctor":
            self._send(200, "application/json",
                       json.dumps(doctor.table(), ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/api/recon"):
            self._send(200, "application/json",
                       json.dumps(reconcile_state(_query_date(self.path)),
                                  ensure_ascii=False, default=str).encode("utf-8"))
        elif self.path == "/api/meta":
            now = session.now()
            m = {"now": now.isoformat(timespec="seconds"),
                 "refresh": schedule.refresh_sec(now),
                 "window": schedule.in_read_window(now)}
            self._send(200, "application/json", json.dumps(m).encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self) -> None:
        try:
            self._post()
        except Exception as e:
            self._send(500, "application/json",
                       json.dumps({"error": f"{type(e).__name__}: {e}"},
                                  ensure_ascii=False).encode("utf-8"))

    def _auth_ok(self) -> bool:
        """令牌 + Origin 校验（治理类 POST 共用）。"""
        if self.headers.get("X-Dash-Token", "") != _TOKEN:
            return False
        origin = self.headers.get("Origin", "")
        if origin and urlparse(origin).netloc != f"127.0.0.1:{self.server.server_port}":
            return False
        return True

    def _post(self) -> None:
        """治理操作：POST /api/govern、/api/risk_limits；需 X-Dash-Token。"""
        if self.path.startswith("/api/risk_limits"):
            self._post_risk_limits()
            return
        if not self.path.startswith("/api/govern"):
            self._send(404, "text/plain", b"not found")
            return
        if not self._auth_ok():
            self._send(403, "application/json",
                       json.dumps({"error": "缺少或错误 X-Dash-Token / Origin"}).encode("utf-8"))
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        action = body.get("action", "")
        if action not in _ACTS:
            self._send(400, "application/json",
                       json.dumps({"error": f"action 非法 {action!r}"}).encode())
            return
        msg = governor.run_cli(action, body.get("reason", ""))
        self._send(200, "application/json", json.dumps({"ok": True, "msg": msg}).encode())

    def _post_risk_limits(self) -> None:
        if not self._auth_ok():
            self._send(403, "application/json",
                       json.dumps({"error": "缺少或错误 X-Dash-Token / Origin"}).encode("utf-8"))
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        try:
            limits = config.set_risk_limits(body.get("limits", {}))
        except ValueError as e:
            self._send(400, "application/json",
                       json.dumps({"error": str(e)}).encode())
            return
        except OSError as e:
            self._send(500, "application/json",
                       json.dumps({"error": f"写入失败：{e}"}).encode())
            return
        alerts.emit("INFO", f"风控上限已修改: {limits}")
        self._send(200, "application/json",
                   json.dumps({"ok": True, "limits": limits}).encode())

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        """访问日志收敛：POST（治理操作）与 >=400 错误进日志；普通 GET 静默。"""
        try:
            code = int(args[1]) if len(args) > 1 and str(args[1]).isdigit() else 0
            if self.command == "POST" or code >= 400:
                log.warning("%s - %s", self.address_string(), fmt % args)
        except Exception:
            pass


def reconcile_state(for_date: str | None = None):
    try:
        return recon.reconcile(for_date)
    except Exception as e:
        return {"for_date": for_date or "", "error": f"{type(e).__name__}: {e}",
                "summary": {"ok": 0, "warn": 0, "total": 0}, "rows": []}


def versions_view(for_date: str | None = None) -> dict:
    """当日 decisions 全部本地版本：文件/时间/是否当前生效。"""
    for_date = for_date or session.now().date().isoformat()
    rows = []
    for p in fileio.versions("decisions"):
        obj = fileio.read_json_safe(p)
        if obj is None:
            continue
        if obj.get("for_date") != for_date:
            continue
        st = p.stat()
        from datetime import datetime
        rows.append({"file": p.name,
                     "mtime": datetime.fromtimestamp(st.st_mtime, session.TZ).isoformat(timespec="seconds"),
                     "size": st.st_size,
                     "active": p == fileio.latest("decisions"),
                     "archived": (fileio.directory() / "archive" / for_date / p.name).exists()
                                 or not p.exists()})
    return {"for_date": for_date, "versions": rows}


def archive_view(date: str | None = None) -> dict:
    """归档检索：archive/<date>/ 下文件清单。"""
    d = date or session.now().date().isoformat()
    base = fileio.directory() / "archive" / d
    names = sorted(x.name for x in base.glob("*.json")) if base.exists() else []
    return {"date": d, "archived": names, "count": len(names)}


def _open_reminder_loop(stop) -> None:
    """开市前提醒：距下一可交易起点 ≤5 分钟（且未在连续竞价中）推一次 WARN。

    推送走 alerts.notify（GM_ALERT_WEBHOOK 配置后可达外部；无配置仅留痕日志）。
    每一 next_open 时刻只提醒一次（sent 记录该起点），不重复轰炸。
    """
    sent = None
    while not stop.is_set():
        try:
            now = session.now()
            if not session.is_open(now):
                nxt = session.next_open(now)
                if nxt:
                    key = nxt.isoformat()
                    diff = (nxt - now).total_seconds()
                    if sent != key and 0 < diff <= 300:
                        sent = key
                        alerts.notify("WARN",
                                      f"距开市 {int(diff // 60)} 分钟（{nxt.strftime('%H:%M')}），请确认终端/账户就绪")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(15)


def run(argv: list[str]) -> int:
    port = int(argv[0]) if argv and argv[0].isdigit() else 8200
    _persist_token()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    stop = threading.Event()
    threading.Thread(target=_open_reminder_loop, args=(stop,), daemon=True).start()
    print(f"trade 看板: http://127.0.0.1:{port}  Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return 0