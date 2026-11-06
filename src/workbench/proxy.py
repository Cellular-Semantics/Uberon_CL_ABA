"""Single entry point for all per-KB Owlery backends.

  GET /kbs              JSON list of KBs whose backend is running
  *   /kbs/<kb>/...     forwarded to that KB's Owlery
  *   /docs/...         forwarded to any running backend (Owlery API docs)
  GET /                 JSON status

usage: python -m workbench.proxy ROOT PORT
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
       "proxy-authorization", "proxy-authenticate", "host", "content-length"}


def backends() -> dict[str, int]:
    f = ROOT / "run" / "state.json"
    if not f.exists():
        return {}
    st = json.loads(f.read_text())
    return {n: b["port"] for n, b in st.get("backends", {}).items()}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, obj):
        body = json.dumps(obj, indent=1).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        bs = backends()
        if path == "/kbs":
            return None, sorted(bs)
        if path == "":
            return None, {"kbs": {n: f"http://localhost:{p}" for n, p in sorted(bs.items())},
                          "usage": "/kbs/<kb>/subclasses?object=<class expression>"}
        parts = path.split("/")
        if len(parts) >= 3 and parts[1] == "kbs":
            name = urllib.request.unquote(parts[2])
            if name not in bs:
                return None, (404, {"error": f"KB {name!r} not served", "kbs": sorted(bs)})
            return bs[name], None
        if bs:
            return next(iter(bs.values())), None
        return None, (503, {"error": "no KBs served"})

    def _forward(self):
        port, local = self._route()
        if port is None:
            code, obj = local if isinstance(local, tuple) else (200, local)
            return self._json(code, obj)
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n) if n else None
        req = urllib.request.Request(f"http://localhost:{port}{self.path}", data=data,
                                     method=self.command)
        for k, v in self.headers.items():
            if k.lower() not in HOP:
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=None) as r:
                code, headers, body = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            code, headers, body = e.code, e.headers, e.read()
        except Exception as e:  # backend down or still loading
            return self._json(502, {"error": f"backend :{port}: {e}"})
        self.send_response(code)
        for k, v in headers.items():
            if k.lower() not in HOP:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _forward

    def log_message(self, fmt, *args):
        sys.stdout.write("%s %s\n" % (self.log_date_time_string(), fmt % args))
        sys.stdout.flush()


if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8090
    ThreadingHTTPServer(("localhost", port), Handler).serve_forever()
