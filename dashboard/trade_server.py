from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dashboard.trade_state import state
from dashboard.sys_state import state as sys_state
from lkl.broker import alerts, governor, recon, schedule, session

_HTML = Path(__file__).with_name("trade_index.html")

_ACTS = ("status", "dry", "arm", "halt", "resume")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _HTML.read_bytes())
        elif self.path == "/api/state":
            self._send(200, "application/json",
                       json.dumps(state(), ensure_ascii=False, default=str).encode("utf-8"))
        elif self.path == "/api/sys":
            self._send(200, "application/json",
                       json.dumps(sys_state(), ensure_ascii=False, default=str).encode("utf-8"))
        elif self.path == "/api/alerts":
            recs = alerts.list_alerts(200)
            self._send(200, "application/json",
                       json.dumps({"summary": alerts.summary(), "recs": recs},
                                  ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/api/recon"):
            d = self.path.partition("?")[2] or None
            body = json.dumps(reconcile_state(d), ensure_ascii=False, default=str)
            self._send(200, "application/json", body.encode("utf-8"))
        elif self.path == "/api/meta":
            now = session.now()
            m = {"now": now.isoformat(timespec="seconds"),
                 "refresh": schedule.refresh_sec(now),
                 "window": schedule.in_read_window(now)}
            self._send(200, "application/json", json.dumps(m).encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self) -> None:
        """治理操作：POST /api/govern  body {action, reason}。"""
        if not self.path.startswith("/api/govern"):
            self._send(404, "text/plain", b"not found")
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

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass  # 静默访问日志


def reconcile_state(for_date: str | None = None):
    try:
        return recon.reconcile(for_date)
    except Exception as e:
        return {"for_date": for_date or "", "error": f"{type(e).__name__}: {e}",
                "summary": {"ok": 0, "warn": 0, "total": 0}, "rows": []}


def run(argv: list[str]) -> int:
    port = int(argv[0]) if argv and argv[0].isdigit() else 8200
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"trade 看板: http://127.0.0.1:{port}  Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0