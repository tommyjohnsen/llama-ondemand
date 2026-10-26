#!/usr/bin/env python3
# PROVENANCE
# written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
# modified-by: codex (gpt-5.6-sol, codex-cli 0.154.0) | 2026-10-26 | session public8-fix-20261026 | provenance block added
# END PROVENANCE
"""A stand-in for llama-server used by the end-to-end test: same flags, same four endpoints."""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
alias = args[args.index("--alias") + 1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send({"status": "ok"})
        elif self.path == "/v1/models":
            self._send({"data": [{"id": alias}]})
        elif self.path == "/slots":
            self._send([{"id": 0, "is_processing": False}])
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(length) or b"{}")
        text = "echo: " + req["messages"][-1]["content"]
        self._send({"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2}})


ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
