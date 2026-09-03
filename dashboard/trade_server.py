"""trade 看板 HTTP 服务（stdlib http.server 零依赖）：页面 + /api/state。"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dashboard.trade_state import state

_HTML = Path(__file__).with_name("trade_index.html")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _HTML.read_bytes())
        elif self.path == "/api/state":
            body = json.dumps(state(), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json", body)
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
    """lkl dash [port=8200]：本地看板 127.0.0.1。"""
    port = int(argv[0]) if argv and argv[0].isdigit() else 8200
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"trade 看板: http://127.0.0.1:{port}  Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0