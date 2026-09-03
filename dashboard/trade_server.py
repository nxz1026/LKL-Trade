from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dashboard.trade_state import state
from dashboard.sys_state import state as sys_state
from lkl.broker import alerts, fileio, governor, recon, schedule, session, tradeops

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
        elif self.path.startswith("/api/versions"):
            d = self.path.partition("?")[2] or None
            self._send(200, "application/json",
                       json.dumps(versions_view(d), ensure_ascii=False, default=str).encode("utf-8"))
        elif self.path.startswith("/api/archive"):
            d = self.path.partition("?")[2] or None
            self._send(200, "application/json",
                       json.dumps(archive_view(d), ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/api/preview"):
            d = self.path.partition("?")[2] or None
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    tradeops.preview(d)
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


def versions_view(for_date: str | None = None) -> dict:
    """当日 decisions 全部本地版本：文件/时间/是否当前生效。"""
    import json as _j
    from pathlib import Path
    for_date = for_date or session.now().date().isoformat()
    rows = []
    for p in fileio.versions("decisions"):
        try:
            obj = _j.loads(p.read_text(encoding="utf-8"))
        except Exception:
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


def run(argv: list[str]) -> int:
    port = int(argv[0]) if argv and argv[0].isdigit() else 8200
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"trade 看板: http://127.0.0.1:{port}  Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0