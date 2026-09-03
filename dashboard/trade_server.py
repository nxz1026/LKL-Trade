from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dashboard.trade_state import state
from dashboard.sys_state import state as sys_state
from lkl.broker import schedule, session

_HTML = Path(__file__).with_name("trade_index.html")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _HTML.read_bytes())
        elif self.path == "/api/state":
            body = json.dumps(state(), ensure_ascii=False, default=str).encode("utf-8")
            self._send(200, "application/json", body)
        elif self.path == "/api/sys":
            body = json.dumps(sys_state(), ensure_ascii=False, default=str).encode("utf-8")
            self._send(200, "application/json", body)
        elif self.path == "/api/meta":
            now = session.now()
            m = {"now": now.isoformat(timespec="seconds"),
                 "refresh": schedule.refresh_sec(now),
                 "window": schedule.in_read_window(now)}
            self._send(200, "application/json", json.dumps(m).encode("utf-8"))
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass  # 静默访问日志

def run(argv: list[str]) -> int:
    port = int(argv[0]) if argv and argv[0].isdigit() else 8200
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"trade 看板: http://127.0.0.1:{port}  Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
