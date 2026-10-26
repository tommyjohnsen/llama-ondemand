# PROVENANCE (mirror of .provenance/ledger.jsonl; ledger wins)
# written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
# modified-by: codex/gpt-5.6-sol | 2026-10-26 | 4f14980 | non-loopback redirect regression test and provenance block added
# reviewed-by: claude-code/claude-opus-5-5 | 2026-10-26 | APPROVE_WITH_NITS
# reviewed-by: grok-build/grok-4.7 | 2026-10-26 | APPROVE_WITH_NITS
# END PROVENANCE
"""Response parsing and the loopback-only HTTP client."""
import contextlib
import http.server
import io
import json
import sys
import threading
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llama_ondemand.client import ClientError, ContextTooLarge, LlamaClient, parse_response, require_loopback, \
    strip_reasoning

BODY = {"choices": [{"message": {"content": "hi", "reasoning_content": "r"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        "timings": {"prompt_per_second": 100.0, "predicted_per_second": 20.0}}


class Response(io.BytesIO):
    pass


@contextlib.contextmanager
def redirect_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(307)
            self.send_header("Location", "http://192.0.2.1/should-not-be-requested")
            self.end_headers()

        def log_message(self, format, *args):
            pass

    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError as exc:
        raise unittest.SkipTest("local sockets unavailable") from exc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class ClientTests(unittest.TestCase):
    def test_parse_response(self):
        r = parse_response(json.dumps(BODY), 0.5)
        self.assertEqual((r.text, r.reasoning, r.prompt_n, r.completion_n, r.gen_tps, r.finish_reason),
                         ("hi", "r", 5, 2, 20.0, "stop"))
        for bad in ("", "{}", '{"choices": []}', '{"choices": [{"message": "x"}]}'):
            with self.subTest(bad=bad), self.assertRaises(ClientError):
                parse_response(bad, 1)

    def test_loopback_only(self):
        for ok in ("http://127.0.0.1:8091", "http://localhost:8091/", "http://[::1]:8091"):
            self.assertTrue(require_loopback(ok).startswith("http://"))
        for bad in ("https://127.0.0.1:8091", "http://192.0.2.1:8091", "http://u:p@127.0.0.1:8091",
                    "http://example.com", "http://127.0.0.1:8091/?q=1"):
            with self.subTest(bad=bad), self.assertRaises(ClientError):
                require_loopback(bad)

    def test_chat_posts_and_parses(self):
        seen = {}

        def opener(request, timeout):
            seen["url"], seen["body"] = request.full_url, json.loads(request.data)
            return Response(json.dumps(BODY).encode())

        r = LlamaClient("http://127.0.0.1:8091", model="m", opener=opener).chat([{"role": "user", "content": "q"}],
                                                                                max_tokens=4)
        self.assertEqual(r.text, "hi")
        self.assertEqual(seen["url"], "http://127.0.0.1:8091/v1/chat/completions")
        self.assertEqual((seen["body"]["model"], seen["body"]["max_tokens"], seen["body"]["stream"]), ("m", 4, False))

    def test_context_too_large_and_other_http_errors(self):
        def raiser(code, text):
            def opener(request, timeout):
                raise urllib.error.HTTPError(request.full_url, code, "x", {}, io.BytesIO(text.encode()))
            return opener

        with self.assertRaises(ContextTooLarge):
            LlamaClient("http://127.0.0.1:1", opener=raiser(400, "exceeds the context size")).chat([])
        with self.assertRaisesRegex(ClientError, "500"):
            LlamaClient("http://127.0.0.1:1", opener=raiser(500, "boom")).chat([])

    def test_chat_refuses_redirect_to_non_loopback(self):
        with redirect_server() as base_url:
            with self.assertRaisesRegex(ClientError, r"redirect refused \(HTTP 307\)"):
                LlamaClient(base_url, timeout=1).chat([])

    def test_strip_reasoning(self):
        self.assertEqual(strip_reasoning("<think>a</think>b"), "b")
        self.assertEqual(strip_reasoning("a</think>b"), "b")
        self.assertEqual(strip_reasoning("b<think>unterminated"), "b")


if __name__ == "__main__":
    unittest.main()
