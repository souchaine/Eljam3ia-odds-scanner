"""A localhost data bridge between the browser and the retro-settlement pipeline.

worldfootball is behind Cloudflare, so the FETCHING has to happen in a real browser. Everything
else -- fixture matching, validation -- belongs in tested Python. Passing thousands of fixtures
through the agent's context to bridge the two would be both expensive and untestable, so the
browser POSTs raw payloads here instead and Python picks them up off disk.

Deliberately narrow:
- binds 127.0.0.1 only, never a routable interface;
- every path carries a random per-session token, so a stray page cannot post into the staging area;
- writes only into `<staging>/`, under filenames validated against a strict pattern;
- serves only what it was given. No shell, no eval, no path traversal.

Usage:
    py tools/score_bridge.py --staging output/.retro_staging --port 8787
"""

import argparse
import json
import re
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
STAGING = Path("output/.retro_staging")
TOKEN = ""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass                                    # the server is chatty; the driver reports instead

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _parts(self):
        bits = [p for p in self.path.split("?")[0].split("/") if p]
        if len(bits) < 3 or bits[0] != "t" or not secrets.compare_digest(bits[1], TOKEN):
            return None
        return bits[2:]

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        parts = self._parts()
        if not parts:
            return self._send(403, b'{"error":"bad token"}')
        if parts[0] == "fetchlist":
            f = STAGING / "fetchlist.json"
            return self._send(200, f.read_bytes() if f.exists() else b"[]")
        if parts[0] == "ping":
            return self._send(200, b'{"ok":true}')
        self._send(404, b'{"error":"no such endpoint"}')

    def do_POST(self):
        parts = self._parts()
        if not parts or len(parts) < 2:
            return self._send(403, b'{"error":"bad token"}')
        kind, key = parts[0], parts[1]
        if kind not in ("index", "reports", "verify") or not SAFE_KEY.match(key):
            return self._send(400, b'{"error":"bad target"}')
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"[]")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, b'{"error":"bad json"}')
        out = STAGING / kind
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")
        self._send(200, json.dumps({"stored": len(payload)}).encode())


def main() -> int:
    global STAGING, TOKEN
    ap = argparse.ArgumentParser(description="Localhost bridge for retro score collection.")
    ap.add_argument("--staging", default="output/.retro_staging")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    STAGING = Path(args.staging)
    STAGING.mkdir(parents=True, exist_ok=True)
    token_file = STAGING / "token.txt"
    TOKEN = token_file.read_text(encoding="utf-8").strip() if token_file.exists() \
        else secrets.token_urlsafe(16)
    token_file.write_text(TOKEN, encoding="utf-8")

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"bridge on http://127.0.0.1:{args.port}/t/{TOKEN}/  staging={STAGING}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
